"""Unit tests for MattermostClient using respx to mock httpx."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
import respx
from httpx import Response

from mattermost_mcp.auth import MattermostAuth
from mattermost_mcp.client import MattermostClient

_TEST_AUTH = MattermostAuth(url="https://mm.example.com", token="test-token", csrf="test-csrf", user_id="test-uid")


def _make_client() -> MattermostClient:
    with patch("mattermost_mcp.client.get_auth", return_value=_TEST_AUTH):
        return MattermostClient()


# ------------------------------------------------------------------
# Auth
# ------------------------------------------------------------------

def test_auth_missing_keychain_raises():
    with patch("mattermost_mcp.auth._keychain", side_effect=RuntimeError("secret not found")):
        with pytest.raises(RuntimeError, match="secret not found"):
            MattermostClient()


def test_auth_missing_includes_bootstrap_command():
    import sys
    platform = "darwin"
    with patch("mattermost_mcp.auth.sys") as mock_sys:
        mock_sys.platform = platform
        with patch("mattermost_mcp.auth.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            with pytest.raises(RuntimeError) as exc_info:
                from mattermost_mcp.auth import _keychain_get_macos
                _keychain_get_macos("token")
    assert "security add-generic-password" in str(exc_info.value)


# ------------------------------------------------------------------
# list_channels
# ------------------------------------------------------------------

@respx.mock
def test_list_channels():
    client = _make_client()
    client._me = {"id": "user1", "username": "testuser"}

    respx.get("https://mm.example.com/api/v4/users/user1/teams").mock(
        return_value=Response(200, json=[{"id": "team1", "name": "main"}])
    )
    respx.get("https://mm.example.com/api/v4/users/user1/teams/team1/channels").mock(
        return_value=Response(200, json=[
            {"id": "ch1", "name": "general", "display_name": "General", "type": "O", "last_post_at": 1000},
        ])
    )
    respx.get("https://mm.example.com/api/v4/users/user1/channels").mock(
        return_value=Response(200, json=[])
    )

    channels = client.list_channels()
    assert len(channels) == 1
    assert channels[0].name == "general"
    assert channels[0].type == "O"


# ------------------------------------------------------------------
# get_channel_posts
# ------------------------------------------------------------------

@respx.mock
def test_get_channel_posts():
    client = _make_client()
    client._me = {"id": "user1", "username": "testuser"}

    post_data = {
        "id": "p1",
        "channel_id": "ch1",
        "user_id": "user1",
        "create_at": 1700000000000,
        "message": "Hello world",
        "metadata": {"sender_name": "@testuser"},
    }
    respx.get("https://mm.example.com/api/v4/channels/ch1/posts").mock(
        return_value=Response(200, json={"order": ["p1"], "posts": {"p1": post_data}})
    )

    posts = client.get_channel_posts("ch1", limit=10)
    assert len(posts) == 1
    assert posts[0].message == "Hello world"
    assert posts[0].username == "@testuser"


@respx.mock
def test_get_channel_posts_since():
    client = _make_client()
    client._me = {"id": "user1", "username": "testuser"}

    respx.get("https://mm.example.com/api/v4/channels/ch1/posts").mock(
        return_value=Response(200, json={"order": [], "posts": {}})
    )

    posts = client.get_channel_posts("ch1", since="2026-01-01T00:00:00", limit=10)
    assert posts == []
    # Verify 'since' param was included
    assert "since" in str(respx.calls.last.request.url)


@respx.mock
def test_get_channel_posts_forbidden():
    client = _make_client()
    respx.get("https://mm.example.com/api/v4/channels/secret/posts").mock(
        return_value=Response(403)
    )
    with pytest.raises(RuntimeError, match="Access denied"):
        client.get_channel_posts("secret")


# ------------------------------------------------------------------
# get_thread
# ------------------------------------------------------------------

@respx.mock
def test_get_thread():
    client = _make_client()
    client._me = {"id": "user1", "username": "testuser"}

    root = {"id": "p1", "channel_id": "ch1", "user_id": "user1", "create_at": 1000, "message": "Root", "metadata": {}}
    reply = {"id": "p2", "channel_id": "ch1", "user_id": "user2", "create_at": 2000, "message": "Reply", "root_id": "p1", "metadata": {}}

    respx.get("https://mm.example.com/api/v4/posts/p1/thread").mock(
        return_value=Response(200, json={"order": ["p1", "p2"], "posts": {"p1": root, "p2": reply}})
    )
    respx.post("https://mm.example.com/api/v4/users/ids").mock(
        return_value=Response(200, json=[{"id": "user2", "username": "other"}])
    )

    thread = client.get_thread("p1")
    assert thread.root.message == "Root"
    assert len(thread.replies) == 1
    assert thread.replies[0].message == "Reply"


@respx.mock
def test_get_thread_no_replies():
    client = _make_client()
    client._me = {"id": "user1", "username": "testuser"}

    root = {"id": "p1", "channel_id": "ch1", "user_id": "user1", "create_at": 1000, "message": "Solo", "metadata": {}}
    respx.get("https://mm.example.com/api/v4/posts/p1/thread").mock(
        return_value=Response(200, json={"order": ["p1"], "posts": {"p1": root}})
    )

    thread = client.get_thread("p1")
    assert thread.root.id == "p1"
    assert thread.replies == []


# ------------------------------------------------------------------
# search_posts
# ------------------------------------------------------------------

@respx.mock
def test_search_posts_empty():
    client = _make_client()
    client._me = {"id": "user1", "username": "testuser"}

    respx.get("https://mm.example.com/api/v4/users/user1/teams").mock(
        return_value=Response(200, json=[{"id": "team1"}])
    )
    respx.post("https://mm.example.com/api/v4/teams/team1/posts/search").mock(
        return_value=Response(200, json={"order": [], "posts": {}})
    )
    results = client.search_posts("nonexistent query xyz", include_muted=True)
    assert results == []


@respx.mock
def test_search_posts_with_results():
    client = _make_client()
    client._me = {"id": "user1", "username": "testuser"}

    respx.get("https://mm.example.com/api/v4/users/user1/teams").mock(
        return_value=Response(200, json=[{"id": "team1"}])
    )
    post = {"id": "p1", "channel_id": "ch1", "user_id": "user1", "create_at": 1000, "message": "release notes here", "metadata": {}}
    respx.post("https://mm.example.com/api/v4/teams/team1/posts/search").mock(
        return_value=Response(200, json={"order": ["p1"], "posts": {"p1": post}})
    )

    results = client.search_posts("release notes", include_muted=True)
    assert len(results) == 1
    assert "release notes" in results[0].message


@respx.mock
def test_search_posts_filters_muted_by_default():
    client = _make_client()
    client._me = {"id": "user1", "username": "testuser"}

    respx.get("https://mm.example.com/api/v4/users/user1/teams").mock(
        return_value=Response(200, json=[{"id": "team1"}])
    )
    posts = {
        "p_loud": {"id": "p_loud", "channel_id": "ch_loud", "user_id": "u", "create_at": 1, "message": "release notes loud", "metadata": {}},
        "p_quiet": {"id": "p_quiet", "channel_id": "ch_muted", "user_id": "u", "create_at": 2, "message": "release notes quiet", "metadata": {}},
    }
    respx.post("https://mm.example.com/api/v4/teams/team1/posts/search").mock(
        return_value=Response(200, json={"order": ["p_loud", "p_quiet"], "posts": posts})
    )
    respx.get("https://mm.example.com/api/v4/users/user1/teams/team1/channels").mock(
        return_value=Response(200, json=[
            {"id": "ch_loud", "name": "loud", "display_name": "Loud", "type": "O", "last_post_at": 0},
            {"id": "ch_muted", "name": "muted", "display_name": "Muted", "type": "O", "last_post_at": 0},
        ])
    )
    respx.get("https://mm.example.com/api/v4/users/user1/channels").mock(
        return_value=Response(200, json=[])
    )
    respx.get("https://mm.example.com/api/v4/users/user1/teams/team1/channels/members").mock(
        return_value=Response(200, json=[
            {"channel_id": "ch_loud", "notify_props": {"mark_unread": "all"}},
            {"channel_id": "ch_muted", "notify_props": {"mark_unread": "mention"}},
        ])
    )
    respx.get("https://mm.example.com/api/v4/users/user1/teams/team1/channels/categories").mock(
        return_value=Response(200, json={"categories": []})
    )

    results = client.search_posts("release notes")  # default: include_muted=False
    assert [p.channel_id for p in results] == ["ch_loud"]


# ------------------------------------------------------------------
# get_user
# ------------------------------------------------------------------

@respx.mock
def test_get_user():
    client = _make_client()
    respx.get("https://mm.example.com/api/v4/users/username/ivanov").mock(
        return_value=Response(200, json={
            "id": "uid1", "username": "ivanov", "first_name": "Ivan",
            "last_name": "Ivanov", "email": "ivanov@example.com", "status": "online",
        })
    )
    user = client.get_user("ivanov")
    assert user.username == "ivanov"
    assert user.first_name == "Ivan"
    assert user.status == "online"


@respx.mock
def test_get_user_not_found():
    client = _make_client()
    respx.get("https://mm.example.com/api/v4/users/username/ghost").mock(
        return_value=Response(404)
    )
    with pytest.raises(RuntimeError, match="User not found: @ghost"):
        client.get_user("ghost")


# ------------------------------------------------------------------
# get_unread
# ------------------------------------------------------------------

@respx.mock
def test_get_unread_empty():
    client = _make_client()
    client._me = {"id": "user1", "username": "testuser"}

    respx.get("https://mm.example.com/api/v4/users/user1/teams").mock(
        return_value=Response(200, json=[{"id": "team1"}])
    )
    respx.get("https://mm.example.com/api/v4/users/user1/teams/team1/channels/members").mock(
        return_value=Response(200, json=[
            {"channel_id": "ch1", "msg_count": 0, "mention_count": 0},
        ])
    )

    result = client.get_unread()
    assert result == []


# ------------------------------------------------------------------
# 401 handling
# ------------------------------------------------------------------

@respx.mock
def test_401_raises_readable_error():
    client = _make_client()
    respx.get("https://mm.example.com/api/v4/users/me").mock(
        return_value=Response(401)
    )
    with pytest.raises(RuntimeError, match="invalid or expired"):
        client._me_user()


@respx.mock
def test_path_arguments_are_quoted():
    client = _make_client()
    route = respx.get("https://mm.example.com/api/v4/posts/..%2Fusers%2Fme/thread").mock(
        return_value=Response(200, json={"order": [], "posts": {}})
    )
    try:
        client.get_thread(post_id="../users/me")
    except Exception:
        pass
    assert route.called
