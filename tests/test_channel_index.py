"""Channel metadata snapshot: one walk, cached, shared by several tools."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import respx
from httpx import Response

from mattermost_mcp.auth import MattermostAuth
from mattermost_mcp.client import MattermostClient

_BASE = "https://mm.example.com/api/v4"
_AUTH = MattermostAuth(url="https://mm.example.com", mode="token", access_token="pat")


def _client() -> MattermostClient:
    with patch("mattermost_mcp.client.get_auth", return_value=_AUTH):
        c = MattermostClient()
    c._me = {"id": "u1", "username": "me"}
    return c


def _mock_workspace(router=respx):
    router.get(f"{_BASE}/users/u1/teams").mock(
        return_value=Response(200, json=[{"id": "t1", "name": "main"}, {"id": "t2", "name": "side"}])
    )
    dm = {"id": "dm1", "name": "u1__u2", "display_name": "", "type": "D", "team_id": "",
          "total_msg_count": 5, "total_msg_count_root": 5, "last_post_at": 3}
    for tid, cid in (("t1", "c1"), ("t2", "c2")):
        router.get(f"{_BASE}/users/u1/teams/{tid}/channels").mock(
            return_value=Response(200, json=[
                {"id": cid, "name": f"n-{cid}", "display_name": f"D {cid}", "type": "O", "team_id": tid,
                 "total_msg_count": 10, "total_msg_count_root": 8, "last_post_at": 1},
                dm,
            ])
        )
        router.get(f"{_BASE}/users/u1/teams/{tid}/channels/members").mock(
            return_value=Response(200, json=[
                {"channel_id": cid, "msg_count": 10, "msg_count_root": 6, "mention_count": 1,
                 "mention_count_root": 1, "notify_props": {"mark_unread": "all"}},
                {"channel_id": "dm1", "msg_count": 5, "msg_count_root": 5, "mention_count": 0,
                 "mention_count_root": 0, "notify_props": {}},
            ])
        )
        router.get(f"{_BASE}/users/u1/teams/{tid}/channels/categories").mock(
            return_value=Response(200, json={"categories": [
                {"display_name": "Favorites", "channel_ids": [cid]},
            ]})
        )
    router.get(f"{_BASE}/users/u1/channels").mock(return_value=Response(200, json=[dm]))


@respx.mock
def test_snapshot_collects_channels_once():
    _mock_workspace()
    index = _client()._channel_index()
    assert set(index.channels) == {"c1", "c2", "dm1"}
    assert index.category["c1"] == "Favorites"
    assert index.unread("c1") == 2  # root counts: 8 total - 6 viewed
    assert index.mentions("c1") == 1
    assert index.unread("dm1") == 0


@respx.mock
def test_snapshot_is_cached_within_ttl():
    _mock_workspace()
    client = _client()
    client._channel_index()
    calls = len(respx.calls)
    client._channel_index()
    client.list_channels()
    client.get_unread()
    assert len(respx.calls) == calls


@respx.mock
def test_ttl_zero_refetches(monkeypatch):
    monkeypatch.setenv("MATTERMOST_CACHE_TTL", "0")
    _mock_workspace()
    client = _client()
    client._channel_index()
    calls = len(respx.calls)
    client._channel_index()
    assert len(respx.calls) > calls


@respx.mock
def test_get_unread_makes_no_per_channel_requests():
    _mock_workspace()
    single = respx.get(url__regex=rf"{_BASE}/channels/[^/]+$").mock(return_value=Response(200, json={}))
    result = _client().get_unread()
    assert not single.called
    assert result == [
        {"channel_id": "c1", "channel_name": "D c1", "msg_count": 2, "mention_count": 1,
         "muted": False, "category": "Favorites"},
        {"channel_id": "c2", "channel_name": "D c2", "msg_count": 2, "mention_count": 1,
         "muted": False, "category": "Favorites"},
    ]


@respx.mock
def test_list_channels_reports_unread_count():
    _mock_workspace()
    by_id = {c.id: c for c in _client().list_channels()}
    assert by_id["c1"].unread_count == 2
    assert by_id["dm1"].unread_count == 0
    assert len(by_id) == 3  # the DM shows up once, not once per team


@respx.mock
def test_members_failure_is_an_error_not_zero_unread():
    _mock_workspace()
    respx.get(f"{_BASE}/users/u1/teams/t1/channels/members").mock(return_value=Response(500))
    client = _client()
    with pytest.raises(RuntimeError, match="membership"):
        client.get_unread()
    assert client._index is None  # nothing degraded got cached


@respx.mock
def test_invalidation_during_build_is_not_overwritten():
    _mock_workspace()
    client = _client()
    real_build = client._build_index

    def build_then_write():
        index = real_build()
        client.invalidate_cache()  # a write lands while the snapshot was being built
        return index

    client._build_index = build_then_write
    client._channel_index()
    assert client._index is None
