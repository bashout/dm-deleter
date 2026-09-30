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
    cli.main()  # must return, not raise
    assert "No token provided" in capsys.readouterr().out
