"""Getting a fresh session after a 401: re-read the session file, or sign in again."""

from __future__ import annotations

import contextlib

import pytest
import respx
from httpx import Response

from mattermost_mcp import browser_login, session
from mattermost_mcp.client import MattermostClient

URL = "https://mm.example.com"
ME = f"{URL}/api/v4/users/me"


def _me_route(valid_token: str):
    def handler(request):
        ok = f"MMAUTHTOKEN={valid_token}" in request.headers.get("Cookie", "")
        return Response(200, json={"id": "u1", "username": "alice"}) if ok else Response(401)

    return respx.get(ME).mock(side_effect=handler)


@respx.mock
def test_newer_token_in_session_file_is_picked_up(monkeypatch):
    session.save(URL, token="old")
    client = MattermostClient()
    session.save(URL, token="new")  # another process signed in again
    monkeypatch.setattr(browser_login, "login", lambda *a, **k: pytest.fail("no browser expected"))
    _me_route("new")
    assert client._get("/users/me")["username"] == "alice"


@respx.mock
def test_auto_login_signs_in_again(monkeypatch):
    monkeypatch.setenv("MATTERMOST_AUTO_LOGIN", "1")
    session.save(URL, token="old")
    client = MattermostClient()
    calls = []

    def fake_login(url, timeout):
        calls.append(url)
        session.save(url, token="fresh")
        return {"username": "alice"}

    monkeypatch.setattr(browser_login, "login", fake_login)
    _me_route("fresh")
    assert client._get("/users/me")["username"] == "alice"
    assert calls == [URL]


@respx.mock
def test_auto_login_off_points_to_login_command(monkeypatch):
    session.save(URL, token="old")
    client = MattermostClient()
    monkeypatch.setattr(browser_login, "login", lambda *a, **k: pytest.fail("no browser expected"))
    _me_route("never")
    with pytest.raises(RuntimeError, match="mattermost-mcp-server login"):
        client._get("/users/me")


@respx.mock
def test_waiter_on_lock_reuses_session_saved_by_other_process(monkeypatch):
    monkeypatch.setenv("MATTERMOST_AUTO_LOGIN", "1")
    session.save(URL, token="old")
    client = MattermostClient()

    @contextlib.contextmanager
    def lock_held_by_other_process():
        session.save(URL, token="theirs")  # they finished signing in while we waited
        yield

    monkeypatch.setattr(session, "login_lock", lock_held_by_other_process)
    monkeypatch.setattr(browser_login, "login", lambda *a, **k: pytest.fail("should reuse their session"))
    route = _me_route("theirs")
    # The first try uses "old" (401); by the time we hold the lock the file is new.
    monkeypatch.setattr(session, "load", _load_old_until_locked())
    assert client._get("/users/me")["username"] == "alice"
    assert route.call_count == 2


def _load_old_until_locked():
    real = session.load
    state = {"n": 0}

    def load():
        state["n"] += 1
        data = real()
        # The plain re-read before taking the lock still sees the old token.
        if state["n"] == 1:
            return {**data, "MATTERMOST_TOKEN": "old"}
        return data

    return load


@respx.mock
def test_failed_auto_login_is_not_retried_every_call(monkeypatch):
    monkeypatch.setenv("MATTERMOST_AUTO_LOGIN", "1")
    session.save(URL, token="old")
    client = MattermostClient()
    calls = []

    def failing_login(url, timeout):
        calls.append(url)
        raise session.SessionError("Timed out after 300s waiting for you to sign in.")

    monkeypatch.setattr(browser_login, "login", failing_login)
    _me_route("never")
    for _ in range(3):
        with pytest.raises(RuntimeError, match="mattermost-mcp-server login"):
            client._get("/users/me")
    assert len(calls) == 1


@respx.mock
def test_startup_without_credentials_signs_in(monkeypatch):
    monkeypatch.setenv("MATTERMOST_AUTO_LOGIN", "1")
    monkeypatch.setenv("MATTERMOST_URL", URL)
    monkeypatch.setattr("mattermost_mcp.auth._keychain", _no_keychain)

    def fake_login(url, timeout):
        session.save(url, token="fresh")
        return {"username": "alice"}

    monkeypatch.setattr(browser_login, "login", fake_login)
    _me_route("fresh")
    assert MattermostClient()._get("/users/me")["username"] == "alice"


def _no_keychain(account, required=True):
    if required:
        raise RuntimeError(f"Keychain secret not found: account={account}")
    return ""


@respx.mock
def test_session_for_another_server_is_not_adopted(monkeypatch):
    session.save(URL, token="old")
    client = MattermostClient()
    client._me = {"id": "u1", "username": "alice"}
    session.save("https://other.example.com", token="new")  # `login --url other` elsewhere
    _me_route("never")
    with pytest.raises(RuntimeError, match="401"):
        client._get("/users/me")
    assert client._auth.url == URL


@respx.mock
def test_swap_forgets_cached_user(monkeypatch):
    session.save(URL, token="old")
    client = MattermostClient()
    client._me = {"id": "u1", "username": "alice"}
    session.save(URL, token="new", user_id="u2")
    _me_route("new")
    client._get("/users/me")
    assert client._me is None or client._me.get("username") == "alice"
    assert client._auth.token == "new"


@respx.mock
def test_requests_use_the_url_of_their_own_session():
    session.save(URL, token="tok")
    client = MattermostClient()
    assert not hasattr(client, "_base")
    _me_route("tok")
    client._get("/users/me")


def test_explicit_token_mode_never_auto_logs_in(monkeypatch):
    monkeypatch.setenv("MATTERMOST_AUTO_LOGIN", "1")
    monkeypatch.setenv("MATTERMOST_AUTH_MODE", "token")
    monkeypatch.setenv("MATTERMOST_URL", URL)
    monkeypatch.setattr("mattermost_mcp.auth._keychain", _no_keychain)
    monkeypatch.setattr(browser_login, "login", lambda *a, **k: pytest.fail("pointless sign-in"))
    with pytest.raises(RuntimeError, match="MATTERMOST_ACCESS_TOKEN"):
        MattermostClient()


@respx.mock
def test_unexpected_login_crash_counts_as_failed_sign_in(monkeypatch):
    monkeypatch.setenv("MATTERMOST_AUTO_LOGIN", "1")
    session.save(URL, token="old")
    client = MattermostClient()
    calls = []

    def crash(url, timeout):
        calls.append(1)
        raise OSError("browser binary vanished")

    monkeypatch.setattr(browser_login, "login", crash)
    _me_route("never")
    for _ in range(2):
        with pytest.raises(RuntimeError, match="401"):
            client._get("/users/me")
    assert len(calls) == 1
