"""On-disk archive format shared by the archiver (writer) and viewer (reader).

An archive folder holds:

    meta.json          channel id + chat name (plus, for a merged archive,
                       the list of all channel ids and per-channel cursors)
    messages.jsonl      one message record per line
    manifest.jsonl      one attachment record per line
    attachments/        downloaded attachment files
    status.json         completion flag from the last run
"""


import json
from pathlib import Path


def minimal_message(msg):
    """Project a raw API message down to the minimal archival record."""
    return {
        "id": msg["id"],
        "author_id": msg["author"]["id"],
        "author": msg["author"].get("global_name") or msg["author"].get("username"),
        "timestamp": msg["timestamp"],
        "edited_timestamp": msg.get("edited_timestamp"),  # null = never edited
        "pinned": bool(msg.get("pinned")),  # pin state at archive time; older records read as unpinned
        "content": msg.get("content", ""),
        "type": msg.get("type", 0),
        "reply_to": (msg.get("message_reference") or {}).get("message_id"),
        "attachment_ids": [a["id"] for a in msg.get("attachments") or []],
    }


def read_meta(folder):
    """meta.json contents, or {} when missing or unreadable."""
    try:
        return json.loads((Path(folder) / "meta.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_meta(folder, meta):
    """Atomically rewrite meta.json (temp file + rename), like the manifest."""
    path = Path(folder) / "meta.json"
    tmp_path = path.with_name(path.name + ".part")
    tmp_path.write_text(json.dumps(meta) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def read_channel_cursors(folder):
    """Per-channel resume cursors of a merged archive: channel id -> id of the
    newest message archived for that channel. Empty for archives that were
    never merged (single-channel, cursor-less by design)."""
    cursors = read_meta(folder).get("channel_cursors")
    if not isinstance(cursors, dict):
        return {}
    return {str(channel): str(cursor) for channel, cursor in cursors.items()}


def list_archives(archive_dir):
    """All archive folders directly under archive_dir (a meta.json marks an
    archive), sorted by name. Used by the CLI to offer merge targets."""
    try:
        children = sorted(Path(archive_dir).iterdir())
    except OSError:
        return []
    return [path for path in children
            if path.is_dir() and (path / "meta.json").is_file()]


def find_existing_archive(channel_id, archive_dir):
    """Locate the most recent archive of this channel in the archival folder
    (resume target). A merged archive matches when the channel is any of its
    recorded channels. Recency is judged by messages.jsonl mtime — it updates on
    every resume append, unlike the folder's own mtime — falling back to the
    folder mtime for archives that never wrote a message."""
    matches = []
    try:
        children = sorted(Path(archive_dir).iterdir())
    except OSError:
        return None
    for path in children:
        meta = path / "meta.json"
        if not path.is_dir() or not meta.exists():
            continue
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        channels = [str(data.get("channel_id"))] if data.get("channel_id") else []
        channels += [str(c) for c in data.get("channel_ids") or []]
        if str(channel_id) not in channels:
            continue
        marker = path / "messages.jsonl"
        try:
            mtime = (marker if marker.exists() else path).stat().st_mtime
        except OSError:
            continue
        matches.append((mtime, path))
    return max(matches, key=lambda m: m[0], default=(0, None))[1]


def load_message_records(path):
    """Load message records from messages.jsonl, truncating any partial tail line
    left behind by a hard kill (a partial line is always the last line written)."""
    records = []
    valid_end = 0
    if path.exists():
        with open(path, "rb") as f:
            for raw in f:
                try:
                    records.append(json.loads(raw))
                except json.JSONDecodeError:
                    break
                valid_end += len(raw)
        if valid_end < path.stat().st_size:
            with open(path, "r+b") as f:
                f.truncate(valid_end)
    return records


def read_archive_status(folder):
    """The completion flag recorded by the last run: True (finished), False
    (interrupted or fetch failed), or None when no flag was ever written."""
    try:
        data = json.loads((Path(folder) / "status.json").read_text(encoding="utf-8"))
        return bool(data.get("complete"))
    except (OSError, ValueError, AttributeError):
        return None


def mark_archive_status(folder, complete):
    """Record whether the archive run finished, so the next resume and the user
    can tell a complete archive from a partial one."""
    try:
        (Path(folder) / "status.json").write_text(
            json.dumps({"complete": complete}) + "\n", encoding="utf-8")
    except OSError:
        pass  # the flag is advisory; the archive data itself is unaffected
