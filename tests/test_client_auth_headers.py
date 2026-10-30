"""Headers per auth mode and the 401 error text."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import respx
from httpx import Response

from mattermost_mcp.auth import MattermostAuth
from mattermost_mcp.client import MattermostClient

_BASE = "https://mm.example.com/api/v4"
_TOKEN = MattermostAuth(url="https://mm.example.com", mode="token", access_token="pat-secret-123")
_COOKIE = MattermostAuth(url="https://mm.example.com", token="cookie-secret", csrf="csrf-1", user_id="u1")


def _client(auth: MattermostAuth) -> MattermostClient:
    with patch("mattermost_mcp.client.get_auth", return_value=auth):
        return MattermostClient()


@respx.mock
def test_token_mode_sends_bearer_only():
    route = respx.get(f"{_BASE}/users/me").mock(return_value=Response(200, json={"id": "u1"}))
    _client(_TOKEN)._get("/users/me")
    headers = route.calls.last.request.headers
    assert headers["Authorization"] == "Bearer pat-secret-123"
    assert "Cookie" not in headers
    assert "X-CSRF-Token" not in headers


@respx.mock
def test_cookie_mode_headers_unchanged():
    route = respx.get(f"{_BASE}/users/me").mock(return_value=Response(200, json={"id": "u1"}))
    _client(_COOKIE)._get("/users/me")
    headers = route.calls.last.request.headers
    assert headers["Cookie"] == "MMAUTHTOKEN=cookie-secret; MMUSERID=u1"
    assert headers["X-CSRF-Token"] == "csrf-1"
    assert "Authorization" not in headers


@respx.mock
def test_mode_switch_on_repull_leaves_no_stale_headers():
    route = respx.get(f"{_BASE}/users/me").mock(
        side_effect=[Response(401), Response(200, json={"id": "u1"})]
    )
    with patch("mattermost_mcp.client.get_auth", side_effect=[_COOKIE, _TOKEN]), \
         patch("mattermost_mcp.client.remote_enabled", return_value=True), \
         patch("mattermost_mcp.client.refresh_remote", return_value={"MATTERMOST_ACCESS_TOKEN": "x"}):
        client = MattermostClient()
        client._get("/users/me")
    headers = route.calls.last.request.headers
    assert headers["Authorization"] == "Bearer pat-secret-123"
    assert "Cookie" not in headers
    assert "X-CSRF-Token" not in headers


@respx.mock
def test_token_401_message():
    respx.get(f"{_BASE}/users/me").mock(return_value=Response(401))
    with pytest.raises(RuntimeError) as e:
        _client(_TOKEN)._get("/users/me")
    msg = str(e.value)
    assert "access token" in msg
    assert "Personal Access Tokens" in msg
    assert "pat-secret-123" not in msg


@respx.mock
def test_cookie_401_message_keeps_help(monkeypatch):
    monkeypatch.setenv("MATTERMOST_AUTH_HELP", "run rotate-cookie.sh")
    respx.get(f"{_BASE}/users/me").mock(return_value=Response(401))
    with pytest.raises(RuntimeError) as e:
        _client(_COOKIE)._get("/users/me")
    msg = str(e.value)
    assert "session cookies" in msg
    assert "run rotate-cookie.sh" in msg
    assert "cookie-secret" not in msg
