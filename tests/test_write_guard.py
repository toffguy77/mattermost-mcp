"""With write mode off, nothing mutating may leave the process."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import respx
from httpx import Response

from mattermost_mcp.auth import MattermostAuth
from mattermost_mcp.client import MattermostClient

_BASE = "https://mm.example.com/api/v4"
_TOKEN = MattermostAuth(url="https://mm.example.com", mode="token", access_token="pat")
_COOKIE_NO_CSRF = MattermostAuth(url="https://mm.example.com", token="cookie")


def _client(auth=_TOKEN, **kw) -> MattermostClient:
    with patch("mattermost_mcp.client.get_auth", return_value=auth):
        return MattermostClient(**kw)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("PUT", "/posts/p1/patch"),
        ("DELETE", "/users/u1/posts/p1/reactions/thumbsup"),
        ("POST", "/posts"),
        ("POST", "/reactions"),
        ("POST", "/teams/t1/posts/search/../../../posts"),
    ],
)
@respx.mock(assert_all_called=False)
def test_guard_blocks_mutations_when_disabled(respx_mock, method, path):
    route = respx_mock.route().mock(return_value=Response(200, json={}))
    client = _client(write_enabled=False)
    with pytest.raises(RuntimeError, match="write mode is disabled"):
        client._request(method, path, json={})
    assert not route.called


@pytest.mark.parametrize(
    "path",
    ["/users/ids", "/users/search", "/teams/t1/posts/search", "/channels/direct"],
)
@respx.mock
def test_read_posts_allowed_when_disabled(path):
    route = respx.post(f"{_BASE}{path}").mock(return_value=Response(200, json=[]))
    _client(write_enabled=False)._request("POST", path, json=[])
    assert route.called


def test_write_disabled_by_default():
    assert _client().write_enabled is False


@pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
def test_env_enables_write(monkeypatch, value):
    monkeypatch.setenv("MATTERMOST_ENABLE_WRITE", value)
    assert _client().write_enabled is True


@respx.mock(assert_all_called=False)
def test_cookie_write_without_csrf_refused(respx_mock):
    route = respx_mock.route().mock(return_value=Response(201, json={}))
    client = _client(_COOKIE_NO_CSRF, write_enabled=True)
    with pytest.raises(RuntimeError, match="MATTERMOST_CSRF"):
        client._request("POST", "/posts", json={})
    assert not route.called


@respx.mock
def test_write_allowed_when_enabled():
    route = respx.post(f"{_BASE}/posts").mock(return_value=Response(201, json={"id": "p"}))
    assert _client(write_enabled=True)._request("POST", "/posts", json={})["id"] == "p"
    assert route.called
