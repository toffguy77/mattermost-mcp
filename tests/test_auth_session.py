"""The saved session as a credential source."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from mattermost_mcp import auth, session


@pytest.fixture
def no_keychain():
    calls = []

    def fake(account, required=True):
        calls.append(account)
        if required:
            raise RuntimeError(f"Keychain secret not found: account={account}")
        return ""

    with patch("mattermost_mcp.auth._keychain", fake):
        yield calls


def test_zero_config_start_from_session(no_keychain):
    session.save("https://mm.example.com", token="sess", csrf="c", user_id="u1")
    a = auth.get_auth()
    assert (a.mode, a.url, a.token, a.csrf, a.user_id) == ("cookie", "https://mm.example.com", "sess", "c", "u1")
    assert no_keychain == []


def test_session_for_matching_env_url(monkeypatch, no_keychain):
    monkeypatch.setenv("MATTERMOST_URL", "https://mm.example.com/")
    session.save("https://mm.example.com", token="sess")
    assert auth.get_auth().token == "sess"


def test_session_for_other_server_is_ignored(monkeypatch, no_keychain):
    monkeypatch.setenv("MATTERMOST_URL", "https://other.example.com")
    session.save("https://mm.example.com", token="sess")
    with pytest.raises(RuntimeError):
        auth.get_auth()


def test_env_token_wins_over_session(monkeypatch, no_keychain):
    monkeypatch.setenv("MATTERMOST_URL", "https://mm.example.com")
    monkeypatch.setenv("MATTERMOST_ACCESS_TOKEN", "pat")
    session.save("https://mm.example.com", token="sess")
    a = auth.get_auth()
    assert (a.mode, a.access_token) == ("token", "pat")


def test_env_cookie_wins_over_session(monkeypatch, no_keychain):
    monkeypatch.setenv("MATTERMOST_URL", "https://mm.example.com")
    monkeypatch.setenv("MATTERMOST_TOKEN", "env-cookie")
    session.save("https://mm.example.com", token="sess", csrf="sess-csrf")
    a = auth.get_auth()
    assert a.token == "env-cookie"


def test_cookie_host_wins_over_session(monkeypatch, tmp_path, no_keychain):
    export = tmp_path / "cookie.env"
    export.write_text("MATTERMOST_URL=https://mm.example.com\nMATTERMOST_TOKEN=remote\n")
    monkeypatch.setenv("MATTERMOST_COOKIE_HOST", "local")
    monkeypatch.setenv("MATTERMOST_COOKIE_PATH", str(export))
    session.save("https://mm.example.com", token="sess")
    assert auth.get_auth().token == "remote"


def test_source_of_credentials_is_reported(no_keychain):
    session.save("https://mm.example.com", token="sess")
    assert auth.get_auth().source == "session"


def test_keychain_token_never_paired_with_session_url():
    # Keychain has a PAT but no URL; the session's URL must not be borrowed for it.
    def fake(account, required=True):
        if account == "access_token":
            return "kc-pat"
        if required:
            raise RuntimeError(f"Keychain secret not found: account={account}")
        return ""

    session.save("https://mm.example.com", token="sess")
    with patch("mattermost_mcp.auth._keychain", fake):
        a = auth.get_auth()
    # The session is the higher source, so it wins as a whole: cookie mode, its own server.
    assert (a.mode, a.url, a.token, a.access_token) == ("cookie", "https://mm.example.com", "sess", "")


def test_explicit_token_mode_never_uses_session(monkeypatch):
    monkeypatch.setenv("MATTERMOST_AUTH_MODE", "token")
    session.save("https://mm.example.com", token="sess")

    def fake(account, required=True):  # a PAT in the keychain, but no URL
        if account == "access_token":
            return "kc-pat"
        raise RuntimeError(f"Keychain secret not found: account={account}")

    with patch("mattermost_mcp.auth._keychain", fake), pytest.raises(RuntimeError, match="url"):
        auth.get_auth()


def test_session_fields_are_not_mixed_with_keychain():
    session.save("https://mm.example.com", token="sess")  # no CSRF saved

    def fake(account, required=True):
        return {"csrf": "kc-csrf", "user_id": "kc-user"}.get(account, "")

    with patch("mattermost_mcp.auth._keychain", fake):
        a = auth.get_auth()
    assert (a.token, a.csrf, a.user_id) == ("sess", "", "")
