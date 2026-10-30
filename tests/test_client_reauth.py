"""A 401 must re-pull the cookie from the host and replay the request once."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import respx
from httpx import Response

from mattermost_mcp.auth import MattermostAuth
from mattermost_mcp.client import MattermostClient

_STALE = MattermostAuth(url="https://mm.example.com", token="stale", csrf="c1", user_id="u1")
_FRESH = MattermostAuth(url="https://mm.example.com", token="fresh", csrf="c2", user_id="u1")


@respx.mock
def test_401_repulls_cookie_and_retries():
    route = respx.get("https://mm.example.com/api/v4/users/me").mock(
        side_effect=[Response(401), Response(200, json={"id": "u1", "username": "alice"})]
    )
    with patch("mattermost_mcp.client.get_auth", side_effect=[_STALE, _FRESH]):
        with patch("mattermost_mcp.client.remote_enabled", return_value=True):
            with patch("mattermost_mcp.client.refresh_remote", return_value={"MATTERMOST_TOKEN": "fresh"}) as refresh:
                client = MattermostClient()
                assert client._get("/users/me")["username"] == "alice"

    assert refresh.call_count == 1
    assert route.call_count == 2
    # The replay must carry the new cookie, not the dead one.
    assert route.calls[0].request.headers["Cookie"].startswith("MMAUTHTOKEN=stale")
    assert route.calls[1].request.headers["Cookie"].startswith("MMAUTHTOKEN=fresh")
    assert route.calls[1].request.headers["X-CSRF-Token"] == "c2"


@respx.mock
def test_401_with_unchanged_cookie_raises_instead_of_looping():
    route = respx.get("https://mm.example.com/api/v4/users/me").mock(return_value=Response(401))
    with patch("mattermost_mcp.client.get_auth", side_effect=[_STALE, _STALE]):
        with patch("mattermost_mcp.client.remote_enabled", return_value=True):
            with patch("mattermost_mcp.client.refresh_remote", return_value={"MATTERMOST_TOKEN": "stale"}):
                client = MattermostClient()
                with pytest.raises(RuntimeError, match="invalid or expired"):
                    client._get("/users/me")
    assert route.call_count == 1


@respx.mock
def test_401_without_cookie_host_does_not_shell_out():
    respx.get("https://mm.example.com/api/v4/users/me").mock(return_value=Response(401))
    with patch("mattermost_mcp.client.get_auth", return_value=_STALE):
        with patch("mattermost_mcp.client.remote_enabled", return_value=False):
            with patch("mattermost_mcp.client.refresh_remote", side_effect=AssertionError("must not pull")):
                client = MattermostClient()
                with pytest.raises(RuntimeError, match="invalid or expired"):
                    client._get("/users/me")


@respx.mock
def test_second_401_does_not_repull_again():
    respx.get("https://mm.example.com/api/v4/users/me").mock(return_value=Response(401))
    with patch("mattermost_mcp.client.get_auth", side_effect=[_STALE, _FRESH]):
        with patch("mattermost_mcp.client.remote_enabled", return_value=True):
            with patch("mattermost_mcp.client.refresh_remote", return_value={"MATTERMOST_TOKEN": "fresh"}) as refresh:
                client = MattermostClient()
                for _ in range(2):
                    with pytest.raises(RuntimeError, match="invalid or expired"):
                        client._get("/users/me")
    assert refresh.call_count == 1


@respx.mock
def test_401_message_appends_deployment_hint(monkeypatch):
    monkeypatch.setenv("MATTERMOST_AUTH_HELP", "Run the rotate-cookie job.")
    respx.get("https://mm.example.com/api/v4/users/me").mock(return_value=Response(401))
    with patch("mattermost_mcp.client.get_auth", return_value=_STALE):
        with patch("mattermost_mcp.client.remote_enabled", return_value=False):
            client = MattermostClient()
            with pytest.raises(RuntimeError, match="rotate-cookie job"):
                client._get("/users/me")


@pytest.mark.parametrize(("value", "expected"), [(None, True), ("1", True), ("0", False), ("false", False)])
def test_trust_env_knob(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("MATTERMOST_TRUST_ENV", raising=False)
    else:
        monkeypatch.setenv("MATTERMOST_TRUST_ENV", value)
    with patch("mattermost_mcp.client.get_auth", return_value=_STALE):
        client = MattermostClient()
    assert client._http.trust_env is expected
