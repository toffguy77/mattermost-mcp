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
    # msg_count is what the user has *viewed*; unread = channel total - viewed.
    respx.get("https://mm.example.com/api/v4/users/user1/teams/team1/channels").mock(
        return_value=Response(200, json=[
            {"id": "ch1", "name": "general", "display_name": "General", "type": "O", "total_msg_count": 40},
        ])
    )
    respx.get("https://mm.example.com/api/v4/users/user1/teams/team1/channels/members").mock(
        return_value=Response(200, json=[
            {"channel_id": "ch1", "msg_count": 40, "mention_count": 0},
        ])
    )

    result = client.get_unread()
    assert result == []


@respx.mock
def test_get_unread_counts_total_minus_viewed():
    client = _make_client()
    client._me = {"id": "user1", "username": "testuser"}

    respx.get("https://mm.example.com/api/v4/users/user1/teams").mock(
        return_value=Response(200, json=[{"id": "team1"}])
    )
    respx.get("https://mm.example.com/api/v4/users/user1/teams/team1/channels").mock(
        return_value=Response(200, json=[
            {"id": "ch1", "name": "general", "display_name": "General", "type": "O",
             "total_msg_count": 50, "total_msg_count_root": 42},
        ])
    )
    respx.get("https://mm.example.com/api/v4/users/user1/teams/team1/channels/members").mock(
        return_value=Response(200, json=[
            {"channel_id": "ch1", "msg_count": 45, "msg_count_root": 40,
             "mention_count": 0, "mention_count_root": 0},
        ])
    )

    assert client.get_unread() == [{
        "channel_id": "ch1", "channel_name": "General", "msg_count": 2,
        "mention_count": 0, "muted": False, "category": None,
    }]


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


@pytest.mark.parametrize("bad", ["", ".", ".."])
def test_dot_segments_are_refused(bad):
    client = _make_client()
    with pytest.raises(ValueError, match="invalid path argument"):
        client.get_thread(post_id=bad)


# ------------------------------------------------------------------
# search fixes
# ------------------------------------------------------------------

def _p(pid, cid, at, msg="hit"):
    return {"id": pid, "channel_id": cid, "user_id": "user1", "create_at": at, "message": msg, "metadata": {}}


@respx.mock
def test_search_scoped_to_public_channel_uses_name_and_filters():
    client = _make_client()
    client._me = {"id": "user1", "username": "testuser"}
    respx.get("https://mm.example.com/api/v4/channels/ch1").mock(
        return_value=Response(200, json={"id": "ch1", "name": "general", "type": "O", "team_id": "team1"})
    )
    search = respx.post("https://mm.example.com/api/v4/teams/team1/posts/search").mock(
        return_value=Response(200, json={"order": ["a", "b"], "posts": {"a": _p("a", "ch1", 2), "b": _p("b", "other", 3)}})
    )
    results = client.search_posts("deploy", channel_id="ch1")
    assert [p.id for p in results] == ["a"]
    assert json.loads(search.calls.last.request.content)["terms"] == "in:general deploy"


@respx.mock
def test_search_scoped_to_dm_searches_all_teams_and_filters():
    client = _make_client()
    client._me = {"id": "user1", "username": "testuser"}
    respx.get("https://mm.example.com/api/v4/channels/dm1").mock(
        return_value=Response(200, json={"id": "dm1", "name": "user1__user2", "type": "D", "team_id": ""})
    )
    respx.get("https://mm.example.com/api/v4/users/user1/teams").mock(
        return_value=Response(200, json=[{"id": "team1"}])
    )
    respx.post("https://mm.example.com/api/v4/teams/team1/posts/search").mock(
        return_value=Response(200, json={"order": ["a", "b"], "posts": {"a": _p("a", "dm1", 2), "b": _p("b", "x", 3)}})
    )
    assert [p.id for p in client.search_posts("deploy", channel_id="dm1")] == ["a"]


@respx.mock
def test_search_dedupes_across_teams_and_sorts_newest_first():
    client = _make_client()
    client._me = {"id": "user1", "username": "testuser"}
    respx.get("https://mm.example.com/api/v4/users/user1/teams").mock(
        return_value=Response(200, json=[{"id": "team1"}, {"id": "team2"}])
    )
    dm = _p("dm_post", "dm1", 5)
    respx.post("https://mm.example.com/api/v4/teams/team1/posts/search").mock(
        return_value=Response(200, json={"order": ["old", "dm_post"], "posts": {"old": _p("old", "c1", 1), "dm_post": dm}})
    )
    respx.post("https://mm.example.com/api/v4/teams/team2/posts/search").mock(
        return_value=Response(200, json={"order": ["dm_post", "new"], "posts": {"dm_post": dm, "new": _p("new", "c2", 9)}})
    )
    results = client.search_posts("hit", include_muted=True)
    assert [p.id for p in results] == ["new", "dm_post", "old"]


@respx.mock
def test_mentions_filter_since_before_limit():
    client = _make_client()
    client._me = {"id": "user1", "username": "testuser"}
    respx.get("https://mm.example.com/api/v4/users/user1/teams").mock(
        return_value=Response(200, json=[{"id": "team1"}])
    )
    # 25 old mentions, 5 recent ones; the server returns them oldest first.
    posts = {f"p{i}": _p(f"p{i}", "c1", 1_000 + i) for i in range(25)}
    posts.update({f"r{i}": _p(f"r{i}", "c1", 1_700_000_000_000 + i) for i in range(5)})
    respx.post("https://mm.example.com/api/v4/teams/team1/posts/search").mock(
        return_value=Response(200, json={"order": list(posts), "posts": posts})
    )
    results = client.get_mentions(since="2023-11-14T00:00:00Z", limit=3)
    assert [p.id for p in results] == ["r4", "r3", "r2"]


@respx.mock
def test_enrichment_does_not_swallow_401():
    client = _make_client()
    client._me = {"id": "user1", "username": "testuser"}
    respx.get("https://mm.example.com/api/v4/channels/ch1/posts").mock(
        return_value=Response(200, json={"order": ["p1"], "posts": {"p1": _p("p1", "ch1", 1)}})
    )
    respx.post("https://mm.example.com/api/v4/users/ids").mock(return_value=Response(401))
    with pytest.raises(RuntimeError, match="401"):
        client.get_channel_posts("ch1")


@respx.mock
def test_enrichment_other_errors_degrade_quietly():
    client = _make_client()
    client._me = {"id": "user1", "username": "testuser"}
    respx.get("https://mm.example.com/api/v4/channels/ch1/posts").mock(
        return_value=Response(200, json={"order": ["p1"], "posts": {"p1": _p("p1", "ch1", 1)}})
    )
    respx.post("https://mm.example.com/api/v4/users/ids").mock(return_value=Response(500))
    assert client.get_channel_posts("ch1")[0].username == "user1"


# ------------------------------------------------------------------
# new read tools
# ------------------------------------------------------------------

@respx.mock
def test_get_me_reports_capabilities():
    client = _make_client()
    respx.get("https://mm.example.com/api/v4/users/me").mock(
        return_value=Response(200, json={"id": "u1", "username": "me", "first_name": "M", "last_name": "E",
                                         "email": "me@x", "nickname": "", "position": "dev"})
    )
    me = client.get_me()
    assert me["username"] == "me"
    assert me["auth_mode"] == "cookie"
    assert me["write_enabled"] is False


@respx.mock
def test_list_teams():
    client = _make_client()
    client._me = {"id": "user1", "username": "testuser"}
    respx.get("https://mm.example.com/api/v4/users/user1/teams").mock(
        return_value=Response(200, json=[{"id": "t1", "name": "main", "display_name": "Main", "extra": 1}])
    )
    assert client.list_teams() == [{"id": "t1", "name": "main", "display_name": "Main"}]


@respx.mock
def test_get_post():
    client = _make_client()
    respx.get("https://mm.example.com/api/v4/posts/p1").mock(
        return_value=Response(200, json=_p("p1", "c1", 5, "hello") | {"metadata": {"sender_name": "@bob"}})
    )
    post = client.get_post("p1")
    assert (post.id, post.message, post.username) == ("p1", "hello", "@bob")


_CHANNEL = {"id": "c1", "name": "town-square", "display_name": "Town Square", "type": "O",
            "team_id": "t1", "header": "h", "purpose": "p", "total_msg_count": 3}


@respx.mock
def test_get_channel_by_id():
    client = _make_client()
    respx.get("https://mm.example.com/api/v4/channels/c1").mock(return_value=Response(200, json=_CHANNEL))
    ch = client.get_channel(channel_id="c1")
    assert ch == {"id": "c1", "name": "town-square", "display_name": "Town Square", "type": "O",
                  "team_id": "t1", "header": "h", "purpose": "p"}


@respx.mock
def test_get_channel_by_team_id_and_name():
    client = _make_client()
    respx.get("https://mm.example.com/api/v4/teams/t1/channels/name/town-square").mock(
        return_value=Response(200, json=_CHANNEL)
    )
    assert client.get_channel(team_id="t1", name="town-square")["id"] == "c1"


@respx.mock
def test_get_channel_by_team_name_and_name():
    client = _make_client()
    respx.get("https://mm.example.com/api/v4/teams/name/main/channels/name/town-square").mock(
        return_value=Response(200, json=_CHANNEL)
    )
    assert client.get_channel(team_name="main", name="town-square")["id"] == "c1"


@respx.mock
def test_get_channel_by_name_only_looks_in_my_channels():
    client = _make_client()
    client._me = {"id": "user1", "username": "testuser"}
    respx.get("https://mm.example.com/api/v4/users/user1/teams").mock(
        return_value=Response(200, json=[{"id": "t1"}])
    )
    respx.get("https://mm.example.com/api/v4/users/user1/teams/t1/channels").mock(
        return_value=Response(200, json=[_CHANNEL])
    )
    respx.get("https://mm.example.com/api/v4/users/user1/channels").mock(return_value=Response(200, json=[]))
    assert client.get_channel(name="town-square")["id"] == "c1"


def test_get_channel_requires_arguments():
    with pytest.raises(ValueError, match="channel_id"):
        _make_client().get_channel()


@respx.mock
def test_search_users():
    client = _make_client()
    route = respx.post("https://mm.example.com/api/v4/users/search").mock(
        return_value=Response(200, json=[
            {"id": f"u{i}", "username": f"ali{i}", "first_name": "", "last_name": "", "email": ""} for i in range(5)
        ])
    )
    users = client.search_users("ali", limit=2)
    assert [u.username for u in users] == ["ali0", "ali1"]
    assert json.loads(route.calls.last.request.content)["term"] == "ali"


@respx.mock
def test_get_pinned_posts():
    client = _make_client()
    respx.get("https://mm.example.com/api/v4/channels/c1/pinned").mock(
        return_value=Response(200, json={"order": ["a"], "posts": {"a": _p("a", "c1", 1) | {"metadata": {"sender_name": "@x"}}}})
    )
    assert [p.id for p in client.get_pinned_posts("c1")] == ["a"]


@respx.mock
def test_get_file_info():
    client = _make_client()
    respx.get("https://mm.example.com/api/v4/files/f1/info").mock(
        return_value=Response(200, json={"id": "f1", "name": "a.pdf", "extension": "pdf", "size": 10,
                                         "mime_type": "application/pdf", "post_id": "p", "channel_id": "c",
                                         "user_id": "u"})
    )
    assert client.get_file_info("f1") == {"id": "f1", "name": "a.pdf", "extension": "pdf", "size": 10,
                                          "mime_type": "application/pdf", "post_id": "p", "channel_id": "c"}


@respx.mock
def test_get_channel_posts_before():
    client = _make_client()
    route = respx.get("https://mm.example.com/api/v4/channels/c1/posts").mock(
        return_value=Response(200, json={"order": [], "posts": {}})
    )
    client.get_channel_posts("c1", before="p9")
    assert route.calls.last.request.url.params["before"] == "p9"


@respx.mock
def test_get_direct_messages_before():
    client = _make_client()
    client._me = {"id": "user1", "username": "testuser"}
    respx.get("https://mm.example.com/api/v4/users/username/bob").mock(
        return_value=Response(200, json={"id": "u2", "username": "bob", "first_name": "", "last_name": "", "email": ""})
    )
    respx.post("https://mm.example.com/api/v4/channels/direct").mock(return_value=Response(201, json={"id": "dm"}))
    route = respx.get("https://mm.example.com/api/v4/channels/dm/posts").mock(
        return_value=Response(200, json={"order": [], "posts": {}})
    )
    client.get_direct_messages("bob", before="p9")
    assert route.calls.last.request.url.params["before"] == "p9"
