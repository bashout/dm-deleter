"""Shared helpers and fixtures for building synthetic archives."""

import json

import pytest


def make_archive(root, name="chat", channel_id="42", chat="tester",
                  records=None, manifest=None):
    """Create a synthetic archive folder on disk; returns its Path."""
    folder = root / name
    (folder / "attachments").mkdir(parents=True)
    (folder / "meta.json").write_text(
        json.dumps({"channel_id": channel_id, "chat": chat}) + "\n", encoding="utf-8")
    with open(folder / "messages.jsonl", "w", encoding="utf-8") as f:
        for record in records or []:
            f.write(json.dumps(record) + "\n")
    with open(folder / "manifest.jsonl", "w", encoding="utf-8") as f:
        for entry in manifest or []:
            f.write(json.dumps(entry) + "\n")
    return folder


def message_record(i, content="hello", author="alice", attachments=None,
                   reply_to=None, edited=False):
    """A minimal_message-shaped record for day i of January 2026."""
    return {
        "id": str(i),
        "author_id": "7",
        "author": author,
        "timestamp": f"2026-01-{i:02d}T00:00:00+00:00",
        "edited_timestamp": f"2026-01-{i:02d}T12:00:00+00:00" if edited else None,
        "content": content,
        "type": 0,
        "reply_to": reply_to,
        "attachment_ids": attachments or [],
    }


def attachment_entry(folder=None, seq=1, message_id="4", attachment_id="a1",
                     filename="pic.png", status="ok"):
    """A manifest entry; also writes the attachment file when folder is given."""
    local_path = f"attachments/{seq:04d}_{message_id}_{filename}"
    if status == "ok" and folder is not None:
        (folder / local_path).write_bytes(b"\x89PNGdata")
    return {
        "seq": seq,
        "message_id": message_id,
        "attachment_id": attachment_id,
        "filename": filename,
        "url": None,
        "local_path": local_path if status == "ok" else None,
        "size": 9 if status == "ok" else None,
        "status": status,
    }


@pytest.fixture
def archive(tmp_path):
    """One archive folder (name 'chat') under tmp_path: 5 messages, 1 attachment.

    Message 2 replies to 1 and is edited; 3 holds a link; 4 holds the
    attachment; 5 has a 200-char content for truncation checks.
    """
    records = [
        message_record(1),
        message_record(2, reply_to="1", edited=True),
        message_record(3, content="see https://example.com"),
        message_record(4, attachments=["a1"]),
        message_record(5, content="x" * 200),
    ]
    folder = make_archive(tmp_path, records=records)
    entry = attachment_entry(folder=folder)
    (folder / "manifest.jsonl").write_text(json.dumps(entry) + "\n", encoding="utf-8")
    return folder
