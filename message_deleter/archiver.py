"""Archive writing: stream a chat to disk and resume interrupted runs."""


import json
import re
import time
from datetime import datetime
from pathlib import Path

from message_deleter.api import ATTACHMENT_DELAY, HistoryFetchError
from message_deleter.archive_format import (
    find_existing_archive,
    load_message_records,
    mark_archive_status,
    minimal_message,
    read_archive_status,
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


def archive_chat(tool, channel_id, channel_label, archive_dir):
    """Archive the chat as a stream: fetch forward from the beginning of the
    conversation, write each message as it arrives, and resume an existing archive
    directory for this channel if one is already present."""
    channel_id = str(channel_id)
    archive_dir = Path(archive_dir)
    folder = find_existing_archive(channel_id, archive_dir)
    resumed = folder is not None
    if folder:
        records = load_message_records(folder / "messages.jsonl")
        archived_ids = {r["id"] for r in records}
        after_id = records[-1]["id"] if records else "0"
        entries = compact_manifest(folder)
        recorded = {e["attachment_id"]: e for e in entries}
        seq = max((e["seq"] for e in entries), default=0)
        note = "" if read_archive_status(folder) is not False else " (previous run did not finish)"
        print(f"\nResuming archive: {folder}/ ({len(archived_ids)} messages already saved{note})")
    else:
        date_part = datetime.now().strftime("%d-%m-%y")
        folder = archive_dir / f"{sanitize_filename(channel_label, 'chat')}-archive-{date_part}"
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
                dest = att_dir / f"{seq:04d}_{message_id}_{sanitize_filename(att.get('filename', 'attachment'))}"
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
                    continue

                for att in msg.get("attachments") or []:
                    if already_saved(recorded.get(att.get("id"))):
                        continue
                    save_attachment(att, msg["id"])

                jf.write(json.dumps(minimal_message(msg)) + "\n")
                mf.flush()
                jf.flush()
                archived_ids.add(msg["id"])
                count = len(archived_ids)
                print(f"\r[{count} msgs] this run: {saved} saved, {failed} failed", end='')

        print()
        compact_manifest(folder)
        mark_archive_status(folder, True)
        print(f"Done. {folder}/ now holds {count} messages.")
        return folder
    except HistoryFetchError as exc:
        mark_archive_status(folder, False)
        print(f"\n\nFetch failed ({exc}); the archive is incomplete.")
        print(f"Rerun the archive for the same chat to resume: {folder}/")
    except KeyboardInterrupt:
        mark_archive_status(folder, False)
        print(f"\n\nInterrupted. Rerun the archive for the same chat to resume: {folder}/")
