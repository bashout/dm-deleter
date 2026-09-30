"""The on-disk archive contract shared by archiver and viewer."""

import json
import os

from message_guillotine import archive_format


def test_minimal_message_projects_fields():
    raw = {
        "id": "1",
        "author": {"id": "7", "username": "alice", "global_name": "Alice"},
        "timestamp": "2026-01-01T00:00:00+00:00",
        "edited_timestamp": None,
        "content": "hi",
        "type": 0,
        "message_reference": {"message_id": "2"},
        "attachments": [{"id": "a1"}, {"id": "a2"}],
    }
    assert archive_format.minimal_message(raw) == {
        "id": "1",
        "author_id": "7",
        "author": "Alice",  # global_name wins over username
        "timestamp": "2026-01-01T00:00:00+00:00",
        "edited_timestamp": None,
        "content": "hi",
        "type": 0,
        "reply_to": "2",
        "attachment_ids": ["a1", "a2"],
    }


def test_load_message_records_truncates_partial_tail(tmp_path):
    path = tmp_path / "messages.jsonl"
    path.write_text(json.dumps({"id": "1"}) + "\n" + '{"id": "2", "tru', encoding="utf-8")
    assert [r["id"] for r in archive_format.load_message_records(path)] == ["1"]
    assert path.read_text(encoding="utf-8").count("\n") == 1  # tail truncated on disk


def test_load_message_records_missing_file(tmp_path):
    assert archive_format.load_message_records(tmp_path / "nope.jsonl") == []


def test_find_existing_archive_matches_channel(tmp_path):
    from tests.conftest import make_archive

    make_archive(tmp_path, name="other-chat", channel_id="43",
                 records=[{"id": "1", "author": "a", "timestamp": "2026-01-01T00:00:00+00:00"}])
    mine = make_archive(tmp_path, name="my-chat", channel_id="42",
                        records=[{"id": "1", "author": "a", "timestamp": "2026-01-01T00:00:00+00:00"}])
    assert archive_format.find_existing_archive("42", tmp_path) == mine
    assert archive_format.find_existing_archive("44", tmp_path) is None


def test_find_existing_archive_prefers_message_file_mtime(tmp_path):
    from tests.conftest import make_archive

    record = [{"id": "1", "author": "a", "timestamp": "2026-01-01T00:00:00+00:00"}]
    older = make_archive(tmp_path, name="older", channel_id="42", records=record)
    newer = make_archive(tmp_path, name="newer", channel_id="42", records=record)
    # newer folder mtime, but older messages.jsonl mtime
    os.utime(newer, (2000000000, 2000000000))
    os.utime(older / "messages.jsonl", (2000000000, 2000000000))
    os.utime(older, (1000000000, 1000000000))
    os.utime(newer / "messages.jsonl", (1000000000, 1000000000))
    assert archive_format.find_existing_archive("42", tmp_path) == older


def test_find_existing_archive_missing_dir(tmp_path):
    assert archive_format.find_existing_archive("42", tmp_path / "nope") is None


def test_status_roundtrip(tmp_path):
    folder = tmp_path
    assert archive_format.read_archive_status(folder) is None  # never written
    archive_format.mark_archive_status(folder, True)
    assert archive_format.read_archive_status(folder) is True
    archive_format.mark_archive_status(folder, False)
    assert archive_format.read_archive_status(folder) is False


def test_status_corrupted_file(tmp_path):
    (tmp_path / "status.json").write_text("not json", encoding="utf-8")
    assert archive_format.read_archive_status(tmp_path) is None
