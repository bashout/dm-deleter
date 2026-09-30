"""Platform API client logic with a stubbed HTTP session."""

from datetime import datetime, timezone

import pytest

from message_deleter.api import HistoryFetchError, MessageDeleter


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, headers=None, text=""):
        self.status_code = status_code
        self._json = json_data if json_data is not None else []
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._json


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None):
        self.calls.append((url, params))
        return self.responses.pop(0)

    def update(self, headers):
        pass


def make_tool(responses):
    tool = MessageDeleter.__new__(MessageDeleter)  # no real session/headers
    tool.session = FakeSession(responses)
    tool.current_user = {"id": "7", "username": "me", "discriminator": "0001"}
    tool.dm_channels = []
    tool.guilds = []
    return tool


def api_message(i, author_id="7"):
    return {"id": str(i),
            "author": {"id": author_id},
            "timestamp": f"2026-01-0{i}T00:00:00+00:00"}


def test_get_guild_channels_filters_to_text_types():
    tool = make_tool([FakeResponse(json_data=[
        {"id": "1", "type": 0},    # text
        {"id": "2", "type": 2},    # voice, dropped
        {"id": "3", "type": 4},    # category, dropped
        {"id": "4", "type": 5},    # news, kept
    ])])
    assert [c["id"] for c in tool.get_guild_channels("99")] == ["1", "4"]


def test_get_guild_channels_empty_on_error():
    tool = make_tool([FakeResponse(status_code=403)])
    assert tool.get_guild_channels("99") == []


def test_get_all_dm_users_dedupes_and_excludes_self_and_bots():
    tool = make_tool([])
    tool.dm_channels = [
        {"id": "1", "recipients": [
            {"id": "9", "username": "bob", "discriminator": "0001", "global_name": "Bob"},
            {"id": "9", "username": "bob-dup", "discriminator": "0002", "global_name": ""},
        ]},
        {"id": "2", "recipients": [
            {"id": "7", "username": "me", "discriminator": "0001", "global_name": ""},
            {"id": "8", "username": "robot", "bot": True, "discriminator": "0000", "global_name": ""},
        ]},
    ]
    users = tool.get_all_dm_users()
    assert len(users) == 1  # deduped by id; self and bots excluded
    assert users[0]["id"] == "9"
    assert users[0]["username"] == "bob-dup"  # later recipients overwrite earlier ones
    assert users[0]["channel_id"] == "1"


def test_filter_messages_in_range_mine_only():
    tool = make_tool([])
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 3, tzinfo=timezone.utc)
    messages = [
        api_message(1, author_id="9"),
        api_message(2, author_id="7"),
        api_message(3, author_id="7"),
    ]
    filtered = tool.filter_messages_in_range(messages, start, end, my_only=True)
    assert [m["id"] for m in filtered] == ["2", "3"]
    everything = tool.filter_messages_in_range(messages, start, end, my_only=False)
    assert [m["id"] for m in everything] == ["1", "2", "3"]


def test_filter_messages_in_range_bounds():
    tool = make_tool([])
    start = datetime(2026, 1, 2, tzinfo=timezone.utc)
    end = datetime(2026, 1, 2, tzinfo=timezone.utc)
    messages = [api_message(1), api_message(2), api_message(3)]
    filtered = tool.filter_messages_in_range(messages, start, end, my_only=False)
    assert [m["id"] for m in filtered] == ["2"]


def test_fetch_page_fails_fast_on_auth_error():
    tool = make_tool([FakeResponse(status_code=401, text="nope")])
    with pytest.raises(HistoryFetchError):
        tool._fetch_page_with_retries("https://api.example", {})


def test_fetch_page_retries_on_rate_limit():
    tool = make_tool([
        FakeResponse(status_code=429, headers={"Retry-After": "1"}),
        FakeResponse(status_code=200, json_data=[]),
    ])
    resp = tool._fetch_page_with_retries("https://api.example", {})
    assert resp.status_code == 200


def test_get_channel_history_stops_on_short_page():
    page = [api_message(1), api_message(2)]
    tool = make_tool([FakeResponse(json_data=page)])
    assert [m["id"] for m in tool.get_channel_history("5", limit=100)] == ["1", "2"]
    assert tool.session.calls[0][1]["limit"] == 100
