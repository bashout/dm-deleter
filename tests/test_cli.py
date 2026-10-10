"""Interactive CLI helpers."""

from datetime import datetime, timezone

from message_guillotine import cli


def test_parse_datetime_blank_is_none(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "")
    assert cli.parse_datetime("date: ") is None


def test_parse_datetime_accepted_formats(monkeypatch):
    answers = iter(["2026-01-02", "2026-01-02 03:04", "01/03/2026",
                    "2026-01-02T05:06:07+00:00"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert cli.parse_datetime("d") == datetime(2026, 1, 2)
    assert cli.parse_datetime("d") == datetime(2026, 1, 2, 3, 4)
    assert cli.parse_datetime("d") == datetime(2026, 1, 3)
    assert cli.parse_datetime("d") == datetime(2026, 1, 2, 5, 6, 7,
                                               tzinfo=timezone.utc)


def test_parse_datetime_retries_on_invalid_input(monkeypatch, capsys):
    answers = iter(["nonsense", "2026-01-02"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert cli.parse_datetime("d") == datetime(2026, 1, 2)
    assert "Invalid format" in capsys.readouterr().out


def test_select_dm_user_returns_choice(monkeypatch):
    class StubTool:
        def get_dm_channels(self):
            return [{"id": "1", "recipients": []}]

        def get_all_dm_users(self):
            return [{"id": "9", "username": "bob", "discriminator": "0001",
                     "global_name": "Bob", "channel_id": "1", "last_message_id": "5"}]

    monkeypatch.setattr("builtins.input", lambda _: "1")
    user = cli.select_dm_user(StubTool())
    assert user["id"] == "9"


def test_select_dm_user_cancel(monkeypatch):
    class StubTool:
        def get_dm_channels(self):
            return [{"id": "1", "recipients": []}]

        def get_all_dm_users(self):
            return [{"id": "9", "username": "bob", "discriminator": "0001",
                     "global_name": "", "channel_id": "1", "last_message_id": "5"}]

    monkeypatch.setattr("builtins.input", lambda _: "0")
    assert cli.select_dm_user(StubTool()) is None


def test_main_without_token_exits(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _: "")
    cli.main([])  # must return, not raise
    assert "No token provided" in capsys.readouterr().out


def test_main_accepts_archive_dir_arg(monkeypatch, tmp_path, capsys):
    # The --archive-dir CLI arg reaches resolve_archive_dir as its explicit arg.
    seen = {}

    def fake_resolve(explicit=None):
        seen.setdefault("calls", []).append(explicit)
        return tmp_path / "resolved"

    class StubTool:
        def __init__(self, token):
            pass

        def get_current_user(self):
            return True

    monkeypatch.setattr(cli, "resolve_archive_dir", fake_resolve)
    monkeypatch.setattr(cli, "MessageGuillotine", StubTool)
    answers = iter(["token", "0"])  # token, then cancel at the mode menu
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    cli.main(["--archive-dir", str(tmp_path / "cli")])
    assert seen["calls"][0] == str(tmp_path / "cli")  # resolve_archive_dir converts to Path
    assert "Archival folder" in capsys.readouterr().out


def _make_archive(root, name="old", channel_id="42", chat="Old Chat"):
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "meta.json").write_text(
        f'{{"channel_id": "{channel_id}", "chat": "{chat}"}}\n', encoding="utf-8")
    (folder / "messages.jsonl").write_text("", encoding="utf-8")
    return folder


def test_pick_merge_target_skipped_when_chat_already_archived(monkeypatch, tmp_path):
    _make_archive(tmp_path)
    def fail(prompt):
        raise AssertionError("no prompt expected")
    monkeypatch.setattr("builtins.input", fail)
    assert cli.pick_merge_target("42", tmp_path) is None


def test_pick_merge_target_default_starts_new_archive(monkeypatch, tmp_path):
    _make_archive(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _: "1")
    assert cli.pick_merge_target("43", tmp_path) is None


def test_pick_merge_target_picks_archive(monkeypatch, tmp_path):
    folder = _make_archive(tmp_path)
    answers = iter(["2", "1"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert cli.pick_merge_target("43", tmp_path) == folder


def test_pick_merge_target_cancel_aborts_run(monkeypatch, tmp_path):
    _make_archive(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _: "0")
    assert cli.pick_merge_target("43", tmp_path) is False


def test_pick_merge_target_cancel_at_archive_list_aborts_run(monkeypatch, tmp_path):
    _make_archive(tmp_path)
    answers = iter(["2", "0"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert cli.pick_merge_target("43", tmp_path) is False


def test_pick_merge_target_invalid_pick_reprompts(monkeypatch, tmp_path):
    folder = _make_archive(tmp_path)
    answers = iter(["9", "x", "2", "1"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert cli.pick_merge_target("43", tmp_path) == folder


def test_pick_merge_target_invalid_first_choice_reprompts(monkeypatch, tmp_path):
    folder = _make_archive(tmp_path)
    answers = iter(["7", "nonsense", "2", "1"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert cli.pick_merge_target("43", tmp_path) == folder


def test_pick_merge_target_no_other_archives(monkeypatch, tmp_path):
    (tmp_path / "not-an-archive").mkdir()
    def fail(prompt):
        raise AssertionError("no prompt expected")
    monkeypatch.setattr("builtins.input", fail)
    assert cli.pick_merge_target("43", tmp_path) is None
