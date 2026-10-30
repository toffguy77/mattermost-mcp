"""Write tools: posting, DMs, editing own posts, reactions."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
import respx
from httpx import Response

from mattermost_mcp.auth import MattermostAuth
from mattermost_mcp.client import MattermostClient

_BASE = "https://mm.example.com/api/v4"
_AUTH = MattermostAuth(url="https://mm.example.com", mode="token", access_token="pat")
_ME = {"id": "me1", "username": "me"}


def _client() -> MattermostClient:
    with patch("mattermost_mcp.client.get_auth", return_value=_AUTH):
        c = MattermostClient(write_enabled=True)
    c._me = dict(_ME)
    return c


def _post(pid="p1", user_id="me1", **kw):
    return {"id": pid, "channel_id": "c1", "user_id": user_id, "create_at": 1, "message": "m",
            "metadata": {}, **kw}


@respx.mock
def test_create_post_in_channel():
    route = respx.post(f"{_BASE}/posts").mock(return_value=Response(201, json=_post(message="hi")))
    post = _client().create_post("c1", "hi")
    assert json.loads(route.calls.last.request.content) == {"channel_id": "c1", "message": "hi"}
    assert post.message == "hi"
    assert post.username == "me"


@respx.mock
def test_create_post_reply():
    route = respx.post(f"{_BASE}/posts").mock(return_value=Response(201, json=_post(root_id="r1")))
    post = _client().create_post("c1", "hi", root_id="r1")
    assert json.loads(route.calls.last.request.content)["root_id"] == "r1"
    assert post.root_id == "r1"


@pytest.mark.parametrize("msg", ["", "   "])
@respx.mock(assert_all_called=False)
def test_create_post_rejects_empty(respx_mock, msg):
    route = respx_mock.route().mock(return_value=Response(201, json={}))
    with pytest.raises(ValueError, match="empty"):
        _client().create_post("c1", msg)
    assert not route.called


@respx.mock
def test_send_direct_message():
    respx.get(f"{_BASE}/users/username/alice").mock(
        return_value=Response(200, json={"id": "a1", "username": "alice", "first_name": "", "last_name": "", "email": ""})
    )
    direct = respx.post(f"{_BASE}/channels/direct").mock(return_value=Response(201, json={"id": "dm1"}))
    create = respx.post(f"{_BASE}/posts").mock(return_value=Response(201, json=_post(channel_id="dm1")))
    _client().send_direct_message("alice", "hi")
    assert json.loads(direct.calls.last.request.content) == ["me1", "a1"]
    assert json.loads(create.calls.last.request.content) == {"channel_id": "dm1", "message": "hi"}


@respx.mock(assert_all_called=False)
def test_send_direct_message_unknown_user(respx_mock):
    respx_mock.get(f"{_BASE}/users/username/ghost").mock(return_value=Response(404))
    create = respx_mock.post(f"{_BASE}/posts").mock(return_value=Response(201, json={}))
    with pytest.raises(RuntimeError, match="User not found: @ghost"):
        _client().send_direct_message("ghost", "hi")
    assert not create.called


@respx.mock
def test_update_own_post():
    respx.get(f"{_BASE}/posts/p1").mock(return_value=Response(200, json=_post()))
    patch_route = respx.put(f"{_BASE}/posts/p1/patch").mock(
        return_value=Response(200, json=_post(message="edited"))
    )
    post = _client().update_post("p1", "edited")
    assert json.loads(patch_route.calls.last.request.content) == {"message": "edited"}
    assert post.message == "edited"


@respx.mock(assert_all_called=False)
def test_update_foreign_post_refused(respx_mock):
    respx_mock.get(f"{_BASE}/posts/p1").mock(return_value=Response(200, json=_post(user_id="other")))
    put = respx_mock.put(f"{_BASE}/posts/p1/patch").mock(return_value=Response(200, json={}))
    with pytest.raises(RuntimeError, match="only edit your own"):
        _client().update_post("p1", "x")
    assert not put.called


@respx.mock
def test_add_reaction_strips_colons():
    route = respx.post(f"{_BASE}/reactions").mock(return_value=Response(201, json={}))
    _client().add_reaction("p1", ":thumbsup:")
    assert json.loads(route.calls.last.request.content) == {
        "user_id": "me1", "post_id": "p1", "emoji_name": "thumbsup",
    }


@respx.mock
def test_remove_reaction_treats_404_as_done():
    route = respx.delete(f"{_BASE}/users/me1/posts/p1/reactions/thumbsup").mock(return_value=Response(404))
    _client().remove_reaction("p1", "thumbsup")
    assert route.called


@respx.mock
def test_write_clears_snapshot_cache():
    respx.post(f"{_BASE}/posts").mock(return_value=Response(201, json=_post()))
    client = _client()
    client._index = object()  # pretend a snapshot is cached
    client.create_post("c1", "hi")
    assert client._index is None


def test_write_methods_refuse_when_disabled():
    with patch("mattermost_mcp.client.get_auth", return_value=_AUTH):
        client = MattermostClient(write_enabled=False)
    with pytest.raises(RuntimeError, match="write mode is disabled"):
        client.create_post("c1", "hi")
