"""Archive writing: filenames, manifest compaction, and archive_chat runs."""

import json

import pytest

from message_deleter import archive_format, archiver
from message_deleter.api import HistoryFetchError
from tests.conftest import make_archive


def api_message(i, attachments=()):
    return {
        "id": str(i),
        "author": {"id": "7", "username": "alice", "global_name": "Alice"},
        "timestamp": f"2026-01-{i:02d}T00:00:00+00:00",
        "content": f"msg {i}",
        "attachments": [
            {"id": f"a{i}", "filename": f"pic{i}.png", "url": f"https://cdn.example/{i}"}
        ] if attachments else [],
    }


class FakeTool:
    """MessageDeleter stand-in: yields canned history, no network."""

    def __init__(self, messages, fail_urls=(), fail_on=None):
        self.messages = sorted(messages, key=lambda m: int(m["id"]))
        self.fail_urls = set(fail_urls)
        self.fail_on = fail_on  # message id after which history fetch fails

    def download_attachment(self, url, dest_path):
        if url in self.fail_urls:
            return None
        dest_path.write_bytes(b"data")
        return 4

    def iter_channel_history(self, channel_id, after_id="0"):
        for msg in self.messages:
            if int(msg["id"]) > int(after_id):
                if self.fail_on is not None and int(msg["id"]) > self.fail_on:
                    raise HistoryFetchError("boom")
                yield msg


def records_of(folder):
    with open(folder / "messages.jsonl", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def manifest_of(folder):
    with open(folder / "manifest.jsonl", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def test_sanitize_filename():
    assert archiver.sanitize_filename("My Chat!.png") == "My_Chat_.png"
    assert archiver.sanitize_filename("  ..  ") == "file"  # empty after strip
    assert archiver.sanitize_filename("ok.txt") == "ok.txt"
    assert archiver.sanitize_filename("") == "file"


def test_compact_manifest_latest_wins(tmp_path):
    folder = make_archive(tmp_path, manifest=[
        {"attachment_id": "a1", "seq": 1, "status": "failed", "local_path": None},
        {"attachment_id": "a1", "seq": 1, "status": "ok", "local_path": "attachments/x"},
        {"attachment_id": "a2", "seq": 2, "status": "ok", "local_path": "attachments/y"},
    ])
    entries = archiver.compact_manifest(folder)
    assert len(entries) == 2
    assert entries[0] == {"attachment_id": "a1", "seq": 1, "status": "ok",
                          "local_path": "attachments/x"}
    assert entries[1]["attachment_id"] == "a2"
    # the rewritten manifest holds exactly the compacted entries
    assert manifest_of(folder) == entries
    assert not (folder / "manifest.jsonl.part").exists()


def test_archive_chat_new_run(tmp_path):
    tool = FakeTool([api_message(1), api_message(2, attachments=[True]), api_message(3)])
    folder = archiver.archive_chat(tool, "42", "My Chat", tmp_path / "archives")
    assert folder.parent == tmp_path / "archives"
    assert folder.name.startswith("My_Chat-archive-")
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    assert meta == {"channel_id": "42", "chat": "My Chat"}
    assert [r["id"] for r in records_of(folder)] == ["1", "2", "3"]  # oldest first
    entries = manifest_of(folder)
    assert len(entries) == 1 and entries[0]["status"] == "ok"
    assert (folder / entries[0]["local_path"]).is_file()
    assert archive_format.read_archive_status(folder) is True


def test_archive_chat_resumes_without_duplicates(tmp_path):
    archive_dir = tmp_path / "archives"
    tool = FakeTool([api_message(1), api_message(2), api_message(3)])
    first = archiver.archive_chat(tool, "42", "chat", archive_dir)
    second = archiver.archive_chat(tool, "42", "chat", archive_dir)
    assert second == first
    assert [r["id"] for r in records_of(second)] == ["1", "2", "3"]


def test_archive_chat_retries_failed_attachment(tmp_path):
    archive_dir = tmp_path / "archives"
    messages = [api_message(1, attachments=[True])]
    failing = FakeTool(messages, fail_urls=["https://cdn.example/1"])
    folder = archiver.archive_chat(failing, "42", "chat", archive_dir)
    assert manifest_of(folder)[0]["status"] == "failed"

    ok = FakeTool(messages)
    folder = archiver.archive_chat(ok, "42", "chat", archive_dir)
    entries = manifest_of(folder)
    assert len(entries) == 1 and entries[0]["status"] == "ok"
    assert (folder / entries[0]["local_path"]).is_file()


def test_archive_chat_marks_incomplete_on_fetch_failure(tmp_path):
    from message_deleter import archive_format

    archive_dir = tmp_path / "archives"
    tool = FakeTool([api_message(1), api_message(2), api_message(3)], fail_on=1)
    assert archiver.archive_chat(tool, "42", "chat", archive_dir) is None  # failed run
    folder = archive_format.find_existing_archive("42", archive_dir)
    assert archive_format.read_archive_status(folder) is False
    assert [r["id"] for r in records_of(folder)] == ["1"]  # pre-failure writes kept

    # a rerun with a healthy tool resumes and completes the archive
    folder = archiver.archive_chat(FakeTool(tool.messages), "42", "chat", archive_dir)
    assert archive_format.read_archive_status(folder) is True
    assert [r["id"] for r in records_of(folder)] == ["1", "2", "3"]


def test_archive_chat_separate_folder_per_channel(tmp_path):
    archive_dir = tmp_path / "archives"
    first = archiver.archive_chat(FakeTool([api_message(1)]), "42", "chat-a", archive_dir)
    second = archiver.archive_chat(FakeTool([api_message(1)]), "43", "chat-b", archive_dir)
    assert second != first
    meta = json.loads((second / "meta.json").read_text(encoding="utf-8"))
    assert meta["channel_id"] == "43"
