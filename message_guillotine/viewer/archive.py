"""Archive loading, filtering, search, and API payload builders.

Only the archive folder is read; nothing from the deleter side is imported.
The on-disk layout is documented in message_guillotine.archive_format."""


import bisect
import json
import mimetypes
import re
from collections import Counter
from pathlib import Path


SEARCH_MAX = 200
VIEW_CACHE_MAX = 32


LINK_RE = re.compile(r"https?://", re.IGNORECASE)


class Archive:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.meta = self._load_json(self.folder / "meta.json", default={})
        self.messages = self._load_jsonl(self.folder / "messages.jsonl")
        self.index_by_id = {m["id"]: i for i, m in enumerate(self.messages)}
        self.attachments_by_id = {}
        for entry in self._load_jsonl(self.folder / "manifest.jsonl"):
            if entry.get("attachment_id") and entry.get("local_path"):
                self.attachments_by_id[entry["attachment_id"]] = entry
        self.attachments = sorted(
            self.attachments_by_id.values(), key=lambda e: e.get("seq", 0)
        )
        self.mime_guesser = mimetypes.MimeTypes()
        # Lazily built, immutable-after-load filter indexes (archive is read-only)
        self._attachment_indices = None
        self._link_indices = None
        self._view_cache = {}
        self._attachment_records = None

    @staticmethod
    def _load_json(path, default=None):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {} if default is None else default

    @staticmethod
    def _load_jsonl(path):
        """Load JSONL records, dropping a partial tail line (same rule the
        archiver uses when resuming after a hard kill)."""
        records = []
        try:
            with open(path, "rb") as f:
                for raw in f:
                    try:
                        records.append(json.loads(raw))
                    except json.JSONDecodeError:
                        break
        except OSError:
            pass
        return records

    def attachment_name(self, entry):
        return Path(entry["local_path"]).name

    def attachment_mime(self, name):
        guessed, _ = self.mime_guesser.guess_type(name)
        return guessed or "application/octet-stream"

    def resolve(self, name):
        """Map a bare attachment filename to a real path inside the archive,
        refusing anything that escapes the attachments directory."""
        base = (self.folder / "attachments").resolve()
        candidate = (base / name).resolve()
        if candidate.parent != base or not candidate.is_file():
            return None
        return candidate

    # -- API payloads -------------------------------------------------------

    def meta_payload(self):
        return {
            "chat": self.meta.get("chat", "archive"),
            "channel_id": self.meta.get("channel_id"),
            "total_messages": len(self.messages),
            "total_attachments": len(self.attachments),
            "first_timestamp": self.messages[0]["timestamp"] if self.messages else None,
            "last_timestamp": self.messages[-1]["timestamp"] if self.messages else None,
        }

    def attachment_view(self, attachment_id):
        """Message-facing view of one attachment, or None if it is not on disk."""
        entry = self.attachments_by_id.get(str(attachment_id))
        if not entry:
            return None
        name = self.attachment_name(entry)
        if self.resolve(name) is None:
            return None
        return {
            "id": entry.get("attachment_id"),
            "filename": entry.get("filename") or name,
            "size": entry.get("size"),
            "url": "/media/" + name,
        }

    # -- filtered views ------------------------------------------------------
    # A "view" is the ordered list of archive indices matching the active
    # filters. None means the unfiltered full log. Timestamps are uniform UTC
    # ISO strings, so lexical comparison equals chronological comparison.

    def _indices_with_attachments(self):
        if self._attachment_indices is None:
            self._attachment_indices = frozenset(
                i for i, m in enumerate(self.messages) if m.get("attachment_ids")
            )
        return self._attachment_indices

    def _indices_with_links(self):
        if self._link_indices is None:
            self._link_indices = frozenset(
                i for i, m in enumerate(self.messages)
                if LINK_RE.search(m.get("content") or "")
            )
        return self._link_indices

    def filtered_view(self, filters):
        """indices (ascending) matching (date_from, date_to, has_attachment, has_link)."""
        cached = self._view_cache.get(filters)
        if cached is not None:
            return cached
        date_from, date_to, has_attachment, has_link = filters
        attachments = self._indices_with_attachments() if has_attachment else None
        links = self._indices_with_links() if has_link else None
        view = []
        for i, message in enumerate(self.messages):
            timestamp = message.get("timestamp") or ""
            if date_from and timestamp < date_from:
                continue
            if date_to and timestamp > date_to:
                continue
            if attachments is not None and i not in attachments:
                continue
            if links is not None and i not in links:
                continue
            view.append(i)
        if len(self._view_cache) >= VIEW_CACHE_MAX:
            self._view_cache.clear()
        self._view_cache[filters] = view
        return view

    def ordered_view(self, filters, reverse):
        """Filtered view or the full log (a range), in the requested direction."""
        if filters is None:
            return range(len(self.messages)) if not reverse else range(len(self.messages) - 1, -1, -1)
        view = self.filtered_view(filters)
        return view if not reverse else view[::-1]

    def anchor_position(self, message_id, filters, reverse):
        """Position of a message within the ordered view, or None if the
        message does not exist or is excluded by the filters."""
        index = self.index_by_id.get(str(message_id))
        if index is None:
            return None
        ascending = self.ordered_view(filters, False)
        position = bisect.bisect_left(ascending, index)
        if position >= len(ascending) or ascending[position] != index:
            return None
        return len(ascending) - 1 - position if reverse else position

    # -- API payloads --------------------------------------------------------

    def page_payload(self, start, count, filters=None, reverse=False):
        ordered = self.ordered_view(filters, reverse)
        total = len(ordered)
        if start < 0:  # negative counts back from the end of the view
            start = max(0, total + start)
        start = max(0, min(start, total))
        out = []
        for index in ordered[start:start + count]:
            message = self.messages[index]
            item = dict(message)
            item["seq"] = index  # position in the archive, not the platform message id
            item["attachments"] = [
                view
                for view in (self.attachment_view(a) for a in message.get("attachment_ids") or [])
                if view
            ]
            out.append(item)
        return {"total": total, "start": start, "messages": out}

    def anchor_payload(self, message_id, count, filters=None, reverse=False):
        position = self.anchor_position(message_id, filters, reverse)
        if position is None:
            return None
        start = max(0, position - count // 2)
        payload = self.page_payload(start, count, filters, reverse)
        payload["anchor_index"] = position
        return payload

    def resolve_payload(self, ids):
        out = {}
        for message_id in ids:
            index = self.index_by_id.get(str(message_id))
            if index is None:
                continue
            message = self.messages[index]
            out[message["id"]] = {
                "index": index,
                "author": message.get("author"),
                "content": (message.get("content") or "")[:140],
                "timestamp": message.get("timestamp"),
            }
        return out

    def search_payload(self, query, author=None, filters=None, limit=SEARCH_MAX):
        query = query.lower()
        author = author.lower() if author else None
        ordered = self.ordered_view(filters, False)
        hits = []
        # Most recent matches first: the view is ascending, scan it backwards.
        for index in reversed(ordered):
            message = self.messages[index]
            if author and (message.get("author") or "").lower() != author:
                continue
            if query not in (message.get("content") or "").lower():
                continue
            hits.append(
                {
                    "index": index,
                    "id": message["id"],
                    "author": message.get("author"),
                    "timestamp": message.get("timestamp"),
                    "content": message.get("content") or "",
                }
            )
            if len(hits) >= limit:
                break
        return {"query": query, "results": hits, "truncated": len(hits) >= limit}

    def attachment_records(self):
        """Attachments enriched with their message date, as
        (entry, year, date) tuples in seq order (built once)."""
        if self._attachment_records is None:
            records = []
            for entry in self.attachments:
                index = self.index_by_id.get(str(entry.get("message_id")))
                timestamp = self.messages[index].get("timestamp") if index is not None else None
                date = (timestamp or "")[:10] or None
                records.append((entry, (date or "?")[:4], date))
            self._attachment_records = records
        return self._attachment_records

    def attachment_year_counts(self):
        """Year -> attachment count, newest year first."""
        counts = Counter(year for _, year, _ in self.attachment_records())
        return [{"year": year, "count": counts[year]}
                for year in sorted(counts, reverse=True)]

    def attachments_payload(self, start, count, year=None):
        records = self.attachment_records()
        if year is not None:
            records = [r for r in records if r[1] == year]
        total = len(records)
        start = max(0, min(start, total))
        items = []
        for entry, _year, date in records[start:start + count]:
            name = self.attachment_name(entry)
            message_id = entry.get("message_id")
            items.append(
                {
                    "seq": entry.get("seq"),
                    "attachment_id": entry.get("attachment_id"),
                    "message_id": message_id,
                    "message_index": self.index_by_id.get(str(message_id)),
                    "filename": entry.get("filename"),
                    "size": entry.get("size"),
                    "date": date,
                    "url": "/media/" + name,
                }
            )
        return {"total": total, "start": start, "attachments": items}

    def stats_payload(self):
        authors = Counter()
        months = Counter()
        edited = 0
        replies = 0
        with_attachments = 0
        for message in self.messages:
            authors[message.get("author") or "unknown"] += 1
            months[(message.get("timestamp") or "")[:7]] += 1
            if message.get("edited_timestamp"):
                edited += 1
            if message.get("reply_to"):
                replies += 1
            if message.get("attachment_ids"):
                with_attachments += 1
        extensions = Counter()
        total_bytes = 0
        for entry in self.attachments:
            extensions[Path(entry.get("filename") or "").suffix.lower() or "?"] += 1
            total_bytes += entry.get("size") or 0
        return {
            "total_messages": len(self.messages),
            "total_attachments": len(self.attachments),
            "attachment_bytes": total_bytes,
            "authors": [{"name": name, "count": count} for name, count in authors.most_common()],
            "months": [{"month": month, "count": count} for month, count in sorted(months.items())],
            "edited": edited,
            "replies": replies,
            "with_attachments": with_attachments,
            "attachment_types": [{"ext": ext, "count": count} for ext, count in extensions.most_common()],
        }


def parse_filter_params(params):
    """Turn query params into a filter key, or None when nothing is filtered.

    Returns (date_from, date_to, has_attachment, has_link). Dates accept either
    YYYY-MM-DD or a full ISO timestamp; a bare end date includes that whole day.
    """
    date_from = (params.get("from") or [None])[0]
    date_to = (params.get("to") or [None])[0]
    if date_to and len(date_to) == 10:
        date_to += "T23:59:59.999999+00:00"
    has_attachment = (params.get("has_attachment") or ["false"])[0] == "true"
    has_link = (params.get("has_link") or ["false"])[0] == "true"
    if date_from or date_to or has_attachment or has_link:
        return (date_from, date_to, has_attachment, has_link)
    return None


def find_archives(root):
    """Archive folders directly under root (meta.json + messages.jsonl),
    most recently modified first."""
    archives = []
    try:
        children = sorted(Path(root).iterdir())
    except OSError:
        return archives
    for path in children:
        if not path.is_dir() or not (path / "meta.json").is_file():
            continue
        if not (path / "messages.jsonl").is_file():
            continue
        try:
            meta = json.loads((path / "meta.json").read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0
        archives.append({
            "name": path.name,
            "chat": meta.get("chat") or path.name,
            "channel_id": meta.get("channel_id"),
            "mtime": mtime,
        })
    archives.sort(key=lambda a: a["mtime"], reverse=True)
    return archives
