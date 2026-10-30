"""Auth mode selection: access token (Bearer) vs browser cookies."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from mattermost_mcp import auth


class _FakeKeychain:
    """Stands in for macOS Keychain / pass; records every lookup."""

    def __init__(self, values: dict[str, str]):
        self.values = values
        self.calls: list[str] = []

    def __call__(self, account: str, required: bool = True) -> str:
        self.calls.append(account)
        value = self.values.get(account, "")
        if not value and required:
            raise RuntimeError(f"Keychain secret not found: account={account}")
        return value


@pytest.fixture
def keychain():
    fake = _FakeKeychain({})
    with patch("mattermost_mcp.auth._keychain", fake):
        yield fake


def _local_host(monkeypatch, tmp_path, body: str):
    export = tmp_path / "cookie.env"
    export.write_text(body)
    monkeypatch.setenv("MATTERMOST_COOKIE_HOST", "local")
    monkeypatch.setenv("MATTERMOST_COOKIE_PATH", str(export))


def test_env_access_token_selects_token_mode(monkeypatch, keychain):
    monkeypatch.setenv("MATTERMOST_URL", "https://mm.example.com/")
    monkeypatch.setenv("MATTERMOST_ACCESS_TOKEN", "pat-1")
    a = auth.get_auth()
    assert a.mode == "token"
    assert a.access_token == "pat-1"
    assert a.url == "https://mm.example.com"
    assert keychain.calls == []


def test_env_cookie_keeps_cookie_mode(monkeypatch, keychain):
    monkeypatch.setenv("MATTERMOST_URL", "https://mm")
    monkeypatch.setenv("MATTERMOST_TOKEN", "cookie-1")
    monkeypatch.setenv("MATTERMOST_CSRF", "csrf-1")
    a = auth.get_auth()
    assert (a.mode, a.token, a.csrf) == ("cookie", "cookie-1", "csrf-1")


def test_env_cookie_beats_keychain_token(monkeypatch, keychain):
    keychain.values["access_token"] = "pat-from-keychain"
    monkeypatch.setenv("MATTERMOST_URL", "https://mm")
    monkeypatch.setenv("MATTERMOST_TOKEN", "cookie-1")
    a = auth.get_auth()
    assert a.mode == "cookie"
    assert a.token == "cookie-1"
    assert "access_token" not in keychain.calls


def test_both_in_env_prefers_token(monkeypatch, keychain):
    monkeypatch.setenv("MATTERMOST_URL", "https://mm")
    monkeypatch.setenv("MATTERMOST_TOKEN", "cookie-1")
    monkeypatch.setenv("MATTERMOST_ACCESS_TOKEN", "pat-1")
    assert auth.get_auth().mode == "token"


def test_explicit_cookie_mode_wins(monkeypatch, keychain):
    monkeypatch.setenv("MATTERMOST_URL", "https://mm")
    monkeypatch.setenv("MATTERMOST_TOKEN", "cookie-1")
    monkeypatch.setenv("MATTERMOST_ACCESS_TOKEN", "pat-1")
    monkeypatch.setenv("MATTERMOST_AUTH_MODE", "Cookie")
    a = auth.get_auth()
    assert (a.mode, a.token) == ("cookie", "cookie-1")


def test_explicit_token_mode_reads_keychain(monkeypatch, keychain):
    keychain.values.update({"url": "https://mm", "access_token": "pat-kc"})
    monkeypatch.setenv("MATTERMOST_AUTH_MODE", "token")
    a = auth.get_auth()
    assert (a.mode, a.access_token, a.url) == ("token", "pat-kc", "https://mm")


def test_keychain_only_token_is_detected(monkeypatch, keychain):
    keychain.values.update({"url": "https://mm", "access_token": "pat-kc"})
    assert auth.get_auth().mode == "token"


def test_keychain_only_cookie_is_detected(monkeypatch, keychain):
    keychain.values.update({"url": "https://mm", "token": "cookie-kc"})
    a = auth.get_auth()
    assert (a.mode, a.token) == ("cookie", "cookie-kc")


def test_invalid_mode_lists_allowed_values(monkeypatch, keychain):
    monkeypatch.setenv("MATTERMOST_URL", "https://mm")
    monkeypatch.setenv("MATTERMOST_ACCESS_TOKEN", "pat-1")
    monkeypatch.setenv("MATTERMOST_AUTH_MODE", "oauth")
    with pytest.raises(RuntimeError) as e:
        auth.get_auth()
    assert "token" in str(e.value) and "cookie" in str(e.value)


def test_token_mode_without_token_names_variables(monkeypatch, keychain):
    monkeypatch.setenv("MATTERMOST_URL", "https://mm")
    monkeypatch.setenv("MATTERMOST_AUTH_MODE", "token")
    with pytest.raises(RuntimeError, match="MATTERMOST_ACCESS_TOKEN"):
        auth.get_auth()


def test_nothing_configured_names_variables(monkeypatch, keychain):
    with pytest.raises(RuntimeError) as e:
        auth.get_auth()
    msg = str(e.value)
    assert "MATTERMOST_URL" in msg
    assert "MATTERMOST_ACCESS_TOKEN" in msg


def test_cookie_host_supplies_access_token(monkeypatch, tmp_path, keychain):
    _local_host(monkeypatch, tmp_path, "MATTERMOST_URL=https://mm\nMATTERMOST_ACCESS_TOKEN=pat-remote\n")
    a = auth.get_auth()
    assert (a.mode, a.access_token) == ("token", "pat-remote")


def test_env_cookie_beats_cookie_host_token(monkeypatch, tmp_path, keychain):
    _local_host(monkeypatch, tmp_path, "MATTERMOST_ACCESS_TOKEN=pat-remote\n")
    monkeypatch.setenv("MATTERMOST_URL", "https://mm")
    monkeypatch.setenv("MATTERMOST_TOKEN", "cookie-1")
    assert auth.get_auth().mode == "cookie"


def test_cookie_host_cannot_set_policy(monkeypatch, tmp_path):
    parsed = auth.parse_cookie_env(
        "MATTERMOST_ACCESS_TOKEN=pat\nMATTERMOST_AUTH_MODE=cookie\nMATTERMOST_ENABLE_WRITE=1\n"
    )
    assert parsed == {"MATTERMOST_ACCESS_TOKEN": "pat"}


def test_legacy_constructor_means_cookie_mode():
    a = auth.MattermostAuth(url="https://mm", token="t", csrf="c", user_id="u")
    assert a.mode == "cookie"
    assert a.access_token == ""
