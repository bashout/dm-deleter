"""Archive writing: stream a chat to disk and resume interrupted runs."""


import json
import re
import time
from datetime import datetime
from pathlib import Path

from message_guillotine.api import ATTACHMENT_DELAY, HistoryFetchError
from message_guillotine.archive_format import (
    find_existing_archive,
    load_message_records,
    mark_archive_status,
    minimal_message,
    read_archive_status,
    read_channel_cursors,
    read_meta,
    write_meta,
)


def sanitize_filename(name, fallback="file"):
    """Strip characters that are unsafe in filenames."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return cleaned or fallback


def compact_manifest(folder):
    """Rewrite manifest.jsonl with one entry per attachment (latest wins, retries
    supersede earlier failures). The rewrite is atomic — written to a temp file
    and renamed into place — so a hard kill cannot leave a truncated manifest.
    Returns the compacted entries."""
    latest = {}
    path = folder / "manifest.jsonl"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    break
                latest[entry["attachment_id"]] = entry
    tmp_path = path.with_name(path.name + ".part")
    with open(tmp_path, "w", encoding="utf-8") as f:
        for entry in latest.values():
            f.write(json.dumps(entry) + "\n")
    tmp_path.replace(path)
    return list(latest.values())


def sort_message_records(folder):
    """Rewrite messages.jsonl in message-id order (ids are chronological
    snowflakes), so a merged archive still reads newest-last in the viewer.
    Atomic — written to a temp file and renamed into place — and skipped when
    the file is already sorted."""
    path = folder / "messages.jsonl"
    if not path.exists():
        return
    records = load_message_records(path)
    ids = [int(r["id"]) for r in records]
    if ids == sorted(ids):
        return
    records.sort(key=lambda r: int(r["id"]))
    tmp_path = path.with_name(path.name + ".part")
    with open(tmp_path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")
    tmp_path.replace(path)


def register_merged_channel(folder, channel_id):
    """Record channel_id as one of the channels archived in folder (a merge),
    with a resume cursor of 0 until its messages land — so even a hard kill
    mid-merge leaves a resumable archive. A legacy single-channel target also
    gets its original channel's cursor seeded from its newest record, keeping
    that channel's future resumes incremental."""
    folder = Path(folder)
    meta = read_meta(folder)
    ids = meta.get("channel_ids")
    if not isinstance(ids, list):
        ids = [str(meta["channel_id"])] if meta.get("channel_id") else []
    ids = [str(i) for i in ids]
    if channel_id not in ids:
        ids.append(channel_id)
    cursors = meta.get("channel_cursors")
    if not isinstance(cursors, dict):
        cursors = {}
        records = load_message_records(folder / "messages.jsonl")
        if records and ids and ids[0] != channel_id:
            cursors[ids[0]] = max(records, key=lambda r: int(r["id"]))["id"]
    meta["channel_ids"] = ids
    cursors.setdefault(channel_id, "0")
    meta["channel_cursors"] = cursors
    write_meta(folder, meta)


def update_channel_cursor(folder, channel_id, last_id):
    """Advance the channel's resume cursor to last_id (the newest message
    archived for it this run). No-op on archives without cursors."""
    if last_id is None:
        return
    meta = read_meta(folder)
    cursors = meta.get("channel_cursors")
    if not isinstance(cursors, dict):
        return
    cursors[channel_id] = str(last_id)
    write_meta(folder, meta)


def archive_chat(tool, channel_id, channel_label, archive_dir, merge_target=None):
    """Archive the chat as a stream: fetch forward from the beginning of the
    conversation, write each message as it arrives, and resume an existing archive
    directory for this channel if one is already present. With merge_target (an
    existing archive folder), a chat that has no archive of its own is merged into
    that folder instead of starting a new one."""
    channel_id = str(channel_id)
    archive_dir = Path(archive_dir)
    folder = find_existing_archive(channel_id, archive_dir)
    resumed = folder is not None
    last_id = None  # newest message id archived for this channel this run
    if folder:
        records = load_message_records(folder / "messages.jsonl")
        archived_ids = {r["id"] for r in records}
        cursors = read_channel_cursors(folder)
        if channel_id in cursors:
            after_id = cursors[channel_id]
        elif cursors:
            # merged archive, but this channel has no cursor yet: full fetch,
            # the id set keeps any overlap out
            after_id = "0"
        else:
            after_id = records[-1]["id"] if records else "0"
        entries = compact_manifest(folder)
        recorded = {e["attachment_id"]: e for e in entries}
        seq = max((e["seq"] for e in entries), default=0)
        note = "" if read_archive_status(folder) is not False else " (previous run did not finish)"
        print(f"\nResuming archive: {folder}/ ({len(archived_ids)} messages already saved{note})")
    elif merge_target is not None:
        folder = Path(merge_target)
        if not (folder / "meta.json").is_file() or not (folder / "messages.jsonl").is_file():
            print(f"\nCannot merge into {folder}: not a valid archive.")
            return None
        records = load_message_records(folder / "messages.jsonl")
        archived_ids = {r["id"] for r in records}
        # A different channel's history shares no message ids with the target;
        # fetch it from the beginning and let the id set drop any overlap.
        after_id = read_channel_cursors(folder).get(channel_id, "0")
        entries = compact_manifest(folder)
        recorded = {e["attachment_id"]: e for e in entries}
        seq = max((e["seq"] for e in entries), default=0)
        register_merged_channel(folder, channel_id)
        print(f"\nMerging into existing archive: {folder}/ "
              f"({len(archived_ids)} messages already saved)")
    else:
        date_part = datetime.now().strftime("%d-%m-%y")
        # Non-ASCII labels (emoji, Cyrillic, CJK, ...) all sanitize to the
        # same empty name, so chats would collide on one folder per day:
        # fall back to the channel id (a GUID) to keep them apart.
        label_part = sanitize_filename(channel_label, "") or f"chat-{channel_id}"
        folder = archive_dir / f"{label_part}-archive-{date_part}"
        # Same trap with ASCII labels: a same-named folder may already hold a
        # different chat. Never overwrite it — disambiguate with the channel id.
        if folder.exists():
            try:
                existing = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                existing = {}
            if existing.get("channel_id") != channel_id:
                folder = archive_dir / f"{label_part}-{channel_id}-archive-{date_part}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "meta.json").write_text(
            json.dumps({"channel_id": channel_id, "chat": channel_label}) + "\n",
            encoding="utf-8")
        archived_ids, after_id, recorded, seq = set(), "0", {}, 0
        print(f"\nStarting new archive: {folder}/")

    att_dir = folder / "attachments"
    for stale in att_dir.glob("*.part"):
        stale.unlink()

    def att_key(att):
        """Attachment id from a raw API attachment, or from a manifest entry on retry."""
        return att.get("id") or att.get("attachment_id")

    def manifest_entry(att, message_id, dest, size):
        return {
            "seq": seq,
            "message_id": message_id,
            "attachment_id": att_key(att),
            "filename": att.get("filename"),
            "url": att.get("url"),
            "local_path": f"attachments/{dest.name}" if size is not None else None,
            "size": size,
            "status": "ok" if size is not None else "failed",
        }

    saved = 0
    failed = 0
    count = len(archived_ids)

    try:
        with open(folder / "messages.jsonl", "a", encoding="utf-8") as jf, \
             open(folder / "manifest.jsonl", "a", encoding="utf-8") as mf:

            def save_attachment(att, message_id):
                nonlocal seq, saved, failed
                att_dir.mkdir(exist_ok=True)
                seq += 1
                # Non-ASCII filenames sanitize to nothing; fall back to the
                # attachment id (a GUID) instead of a shared "file" name.
                safe_name = sanitize_filename(att.get("filename") or "",
                                              f"att-{att_key(att)}")
                dest = att_dir / f"{seq:04d}_{message_id}_{safe_name}"
                size = tool.download_attachment(att.get("url"), dest)
                entry = manifest_entry(att, message_id, dest, size)
                mf.write(json.dumps(entry) + "\n")
                if size is None:
                    failed += 1
                else:
                    saved += 1
                recorded[att_key(att)] = entry
                time.sleep(ATTACHMENT_DELAY)

            def already_saved(entry):
                return (entry
                        and entry["status"] == "ok"
                        and entry["local_path"]
                        and (folder / entry["local_path"]).exists())

            if resumed:
                # Retry attachments that failed in a previous run (signed URLs may still be valid)
                for entry in list(recorded.values()):
                    if entry["status"] == "failed":
                        save_attachment(entry, entry["message_id"])

            for msg in tool.iter_channel_history(channel_id, after_id=after_id):
                if msg["id"] in archived_ids:
                    last_id = msg["id"]  # already archived: the cursor may advance
                    continue

                for att in msg.get("attachments") or []:
                    if already_saved(recorded.get(att.get("id"))):
                        continue
                    save_attachment(att, msg["id"])

                jf.write(json.dumps(minimal_message(msg)) + "\n")
                mf.flush()
                jf.flush()
                archived_ids.add(msg["id"])
                last_id = msg["id"]
                count = len(archived_ids)
                print(f"\r[{count} msgs] this run: {saved} saved, {failed} failed", end='')

        print()
        compact_manifest(folder)
        sort_message_records(folder)
        update_channel_cursor(folder, channel_id, last_id)
        mark_archive_status(folder, True)
        print(f"Done. {folder}/ now holds {count} messages.")
        return folder
    except HistoryFetchError as exc:
        sort_message_records(folder)
        mark_archive_status(folder, False)
        update_channel_cursor(folder, channel_id, last_id)
        print(f"\n\nFetch failed ({exc}); the archive is incomplete.")
        print(f"Rerun the archive for the same chat to resume: {folder}/")
    except KeyboardInterrupt:
        sort_message_records(folder)
        mark_archive_status(folder, False)
        update_channel_cursor(folder, channel_id, last_id)
        print(f"\n\nInterrupted. Rerun the archive for the same chat to resume: {folder}/")
