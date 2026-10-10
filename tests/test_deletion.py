"""Message deletion: rate limiting, permission aborts, and range filtering."""

from datetime import datetime

from message_guillotine import cli
from message_guillotine.api import RATE_LIMIT_DELAY, MessageGuillotine


class FakeResponse:
    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.headers = headers or {}


class FakeSession:
    """Yields canned delete responses in order; records every call."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def delete(self, url, timeout=None):
        self.calls.append(url)
        item = self.responses.pop(0)
        return item if isinstance(item, FakeResponse) else FakeResponse(item)


def make_tool(responses):
    tool = MessageGuillotine.__new__(MessageGuillotine)
    tool.current_user = {"id": "7"}
    tool.session = FakeSession(responses)
    return tool


def message(i, author_id="7", timestamp="2026-01-05T00:00:00+00:00"):
    return {"id": str(i), "author": {"id": author_id},
            "timestamp": timestamp, "content": f"msg {i}"}


def run_delete(monkeypatch, tool, count, confirm="y"):
    """Run delete_with_rate_limit over `count` canned messages, capturing
    every sleep instead of waiting. Returns the sleep durations."""
    sleeps = []
    monkeypatch.setattr("message_guillotine.api.time.sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr("builtins.input", lambda _: confirm)
    tool.delete_with_rate_limit([message(i) for i in range(1, count + 1)], "42")
    return sleeps


def test_delete_needs_confirmation(monkeypatch):
    tool = make_tool([204])
    run_delete(monkeypatch, tool, 1, confirm="n")
    assert tool.session.calls == []  # nothing sent without a 'y'


def test_delete_counts_and_paces(monkeypatch):
    tool = make_tool([204, 200])
    sleeps = run_delete(monkeypatch, tool, 2)
    assert len(tool.session.calls) == 2
    assert sleeps == [RATE_LIMIT_DELAY]  # paced between messages, none after the last


def test_delete_429_retries_after_retry_after(monkeypatch):
    tool = make_tool([FakeResponse(429, {"Retry-After": "7"}), 204])
    sleeps = run_delete(monkeypatch, tool, 1)
    assert len(tool.session.calls) == 2  # the same message retried
    assert 7.0 in sleeps


def test_delete_403_aborts_without_touching_the_rest(monkeypatch, capsys):
    tool = make_tool([204, 403, 204])
    sleeps = run_delete(monkeypatch, tool, 3)
    assert len(tool.session.calls) == 2  # first deleted, second 403, third untouched
    assert sleeps == [RATE_LIMIT_DELAY]  # one pace sleep, then aborted before msg 3
    out = capsys.readouterr().out
    assert "HTTP 403" in out
    assert "not allowed" in out


def test_delete_401_aborts(monkeypatch, capsys):
    tool = make_tool([401, 204])
    run_delete(monkeypatch, tool, 2)
    assert len(tool.session.calls) == 1
    assert "HTTP 401" in capsys.readouterr().out


def test_delete_unexpected_status_fails_message_but_continues(monkeypatch):
    tool = make_tool([500, 204])
    sleeps = run_delete(monkeypatch, tool, 2)
    assert len(tool.session.calls) == 2
    assert sleeps == [RATE_LIMIT_DELAY]  # a 500 fails the message, the run goes on


def test_filter_messages_in_range_my_only():
    tool = MessageGuillotine.__new__(MessageGuillotine)
    tool.current_user = {"id": "7"}
    messages = [
        message(1, author_id="999", timestamp="2026-01-05T00:00:00+00:00"),
        message(2, author_id="7", timestamp="2026-01-06T00:00:00+00:00"),
        message(3, author_id="7", timestamp="2026-01-07T00:00:00+00:00"),
    ]
    mine = tool.filter_messages_in_range(
        messages, datetime(2026, 1, 1), datetime(2026, 1, 31), my_only=True)
    assert [m["id"] for m in mine] == ["2", "3"]
    everything = tool.filter_messages_in_range(
        messages, datetime(2026, 1, 1), datetime(2026, 1, 31), my_only=False)
    assert [m["id"] for m in everything] == ["1", "2", "3"]


def _stub_tool():
    tool = MessageGuillotine.__new__(MessageGuillotine)
    tool.current_user = {"id": "7"}
    tool.guilds = [{"id": "g1", "name": "G"}]
    tool.get_guilds = lambda: True
    tool.get_guild_channels = lambda guild_id: [
        {"id": "c1", "name": "general", "type": 0}]
    tool.get_channel_history = lambda channel_id, limit=100: [
        message(1, author_id="7"), message(2, author_id="999")]
    return tool


def _run_server_deletion(monkeypatch, answers, tool):
    captured = {}

    def fake_delete(msgs, channel_id):
        captured["msgs"] = msgs
        captured["channel_id"] = channel_id

    tool.delete_with_rate_limit = fake_delete
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    cli.handle_server_deletion(tool)
    return captured


def test_server_deletion_deletes_only_own_messages(monkeypatch):
    tool = _stub_tool()
    # server pick, channel pick, start date, end date — no my-only prompt anymore
    captured = _run_server_deletion(monkeypatch, iter(["1", "1", "", ""]), tool)
    assert [m["id"] for m in captured["msgs"]] == ["1"]  # only mine, never others'
    assert captured["channel_id"] == "c1"
