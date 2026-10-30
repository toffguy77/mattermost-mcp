"""Cookie-host source: parsing, caching, and resolution order."""

from __future__ import annotations

import os
import time
from unittest.mock import patch

import pytest

from mattermost_mcp import auth


def _local_host(monkeypatch, tmp_path, body: str):
    """Point the cookie host at a local file instead of ssh."""
    export = tmp_path / "mattermost_cookie.env"
    export.write_text(body)
    monkeypatch.setenv("MATTERMOST_COOKIE_HOST", "local")
    monkeypatch.setenv("MATTERMOST_COOKIE_PATH", str(export))
    return export


# ------------------------------------------------------------------
# parse_cookie_env
# ------------------------------------------------------------------

def test_parse_keeps_known_keys_only():
    parsed = auth.parse_cookie_env(
        "# comment\n"
        "MATTERMOST_URL=https://mm.example.com\n"
        "MATTERMOST_TOKEN=tok\n"
        "PATH=/evil\n"
        "\n"
        "MATTERMOST_CSRF='csrf'\n"
    )
    assert parsed == {
        "MATTERMOST_URL": "https://mm.example.com",
        "MATTERMOST_TOKEN": "tok",
        "MATTERMOST_CSRF": "csrf",
    }


def test_parse_drops_empty_values():
    assert auth.parse_cookie_env("MATTERMOST_TOKEN=\nMATTERMOST_CSRF=x") == {"MATTERMOST_CSRF": "x"}


# ------------------------------------------------------------------
# remote_creds / cache
# ------------------------------------------------------------------

def test_disabled_host_returns_nothing(monkeypatch):
    monkeypatch.setenv("MATTERMOST_COOKIE_HOST", "off")
    assert auth.remote_creds() == {}
    assert auth.remote_enabled() is False


def test_disabled_host_also_disowns_its_cache(monkeypatch, tmp_path):
    _local_host(monkeypatch, tmp_path, "MATTERMOST_URL=https://mm\nMATTERMOST_TOKEN=t1\n")
    assert auth.remote_creds()["MATTERMOST_TOKEN"] == "t1"  # warm the cache
    monkeypatch.setenv("MATTERMOST_COOKIE_HOST", "off")
    # Otherwise "off" would silently keep serving the last cookie ever pulled.
    assert auth.remote_creds() == {}


def test_local_host_is_read_and_cached(monkeypatch, tmp_path):
    export = _local_host(monkeypatch, tmp_path, "MATTERMOST_URL=https://mm\nMATTERMOST_TOKEN=t1\n")
    assert auth.remote_creds()["MATTERMOST_TOKEN"] == "t1"

    # Source changed, but the cache is still warm — we must not re-read.
    export.write_text("MATTERMOST_URL=https://mm\nMATTERMOST_TOKEN=t2\n")
    assert auth.remote_creds()["MATTERMOST_TOKEN"] == "t1"

    # force=True is what a 401 triggers.
    assert auth.refresh_remote()["MATTERMOST_TOKEN"] == "t2"
    assert auth.remote_creds()["MATTERMOST_TOKEN"] == "t2"


def test_expired_cache_is_refetched(monkeypatch, tmp_path):
    _local_host(monkeypatch, tmp_path, "MATTERMOST_URL=https://mm\nMATTERMOST_TOKEN=t1\n")
    monkeypatch.setenv("MATTERMOST_COOKIE_TTL", "0")
    assert auth.remote_creds()["MATTERMOST_TOKEN"] == "t1"

    cache = auth._cache_path()
    os.utime(cache, (time.time() - 10_000, time.time() - 10_000))
    with patch.object(auth, "_fetch_remote", return_value={"MATTERMOST_TOKEN": "fresh"}) as fetch:
        assert auth.remote_creds()["MATTERMOST_TOKEN"] == "fresh"
    assert fetch.called


def test_stale_cache_survives_an_unreachable_host(monkeypatch, tmp_path):
    _local_host(monkeypatch, tmp_path, "MATTERMOST_URL=https://mm\nMATTERMOST_TOKEN=t1\n")
    auth.remote_creds()  # warm the cache

    monkeypatch.setenv("MATTERMOST_COOKIE_TTL", "0")
    with patch.object(auth, "_fetch_remote", return_value={}):
        # A dead cookie beats no cookie: the caller learns the truth from a 401,
        # not from a confusing "credentials missing" at startup.
        assert auth.remote_creds()["MATTERMOST_TOKEN"] == "t1"


def test_ssh_failure_is_not_fatal(monkeypatch):
    monkeypatch.setenv("MATTERMOST_COOKIE_HOST", "cookiebox")
    with patch.object(auth.subprocess, "run", side_effect=OSError("ssh missing")):
        assert auth._fetch_remote() == {}


def test_ssh_failure_explains_itself_on_stderr(monkeypatch, capsys):
    monkeypatch.setenv("MATTERMOST_COOKIE_HOST", "cookiebox")
    with patch.object(auth.subprocess, "run") as run:
        run.return_value.returncode = 255
        run.return_value.stdout = ""
        run.return_value.stderr = "Permission denied (publickey)."
        assert auth._fetch_remote() == {}
    err = capsys.readouterr().err
    # Without this the user only ever sees the keychain error and has no idea
    # ssh was even attempted.
    assert "cookie host unavailable" in err
    assert "Permission denied (publickey)" in err


def test_empty_export_is_reported(monkeypatch, capsys):
    monkeypatch.setenv("MATTERMOST_COOKIE_HOST", "cookiebox")
    with patch.object(auth.subprocess, "run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "# nothing useful here\n"
        run.return_value.stderr = ""
        assert auth._fetch_remote() == {}
    assert "no MATTERMOST_* lines" in capsys.readouterr().err


def test_ssh_command_is_batchmode_and_quoted(monkeypatch):
    monkeypatch.setenv("MATTERMOST_COOKIE_HOST", "nuc")
    monkeypatch.setenv("MATTERMOST_COOKIE_PATH", "a b/cookie.env")
    with patch.object(auth.subprocess, "run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "MATTERMOST_TOKEN=x"
        auth._fetch_remote()
    cmd = run.call_args[0][0]
    assert cmd[0] == "ssh"
    assert "BatchMode=yes" in cmd
    assert cmd[-2] == "nuc"
    assert cmd[-1] == "cat -- 'a b/cookie.env'"


# ------------------------------------------------------------------
# get_auth resolution order
# ------------------------------------------------------------------

def _keychain_forbidden_for_required():
    """Keychain stub that fails loudly only where it must not be reached.

    Optional fields legitimately fall through to keychain when neither env nor
    the cookie host carries them — that per-field fallback is the point of the
    resolution order, not a leak.
    """
    seen: list[str] = []

    def _kc(account: str, required: bool = True) -> str:
        seen.append(account)
        if required:
            raise AssertionError(f"keychain must not be reached for required field {account!r}")
        return f"kc-{account}"

    return _kc, seen


def test_env_wins_over_cookie_host(monkeypatch, tmp_path):
    _local_host(monkeypatch, tmp_path, "MATTERMOST_URL=https://remote\nMATTERMOST_TOKEN=remote-tok\n")
    monkeypatch.setenv("MATTERMOST_URL", "https://env")
    monkeypatch.setenv("MATTERMOST_TOKEN", "env-tok")
    kc, seen = _keychain_forbidden_for_required()
    with patch.object(auth, "_keychain", side_effect=kc):
        got = auth.get_auth()
    assert (got.url, got.token) == ("https://env", "env-tok")
    assert seen == ["csrf", "user_id"]


def test_cookie_host_wins_over_keychain(monkeypatch, tmp_path):
    _local_host(
        monkeypatch, tmp_path,
        "MATTERMOST_URL=https://remote\nMATTERMOST_TOKEN=remote-tok\nMATTERMOST_CSRF=remote-csrf\n",
    )
    monkeypatch.delenv("MATTERMOST_URL", raising=False)
    monkeypatch.delenv("MATTERMOST_TOKEN", raising=False)
    monkeypatch.delenv("MATTERMOST_CSRF", raising=False)
    kc, seen = _keychain_forbidden_for_required()
    with patch.object(auth, "_keychain", side_effect=kc):
        got = auth.get_auth()
    assert (got.url, got.token, got.csrf) == ("https://remote", "remote-tok", "remote-csrf")
    # csrf came from the host, so only user_id was left for keychain.
    assert seen == ["user_id"]


def test_keychain_fills_fields_the_host_omits(monkeypatch, tmp_path):
    _local_host(monkeypatch, tmp_path, "MATTERMOST_URL=https://remote\nMATTERMOST_TOKEN=remote-tok\n")
    monkeypatch.delenv("MATTERMOST_CSRF", raising=False)
    with patch.object(auth, "_keychain", return_value="kc") as kc:
        got = auth.get_auth()
    assert got.csrf == "kc"
    assert {c.args[0] for c in kc.call_args_list} == {"csrf", "user_id"}


def test_missing_everywhere_names_the_cookie_host(monkeypatch):
    monkeypatch.setenv("MATTERMOST_COOKIE_HOST", "cookiebox")
    monkeypatch.delenv("MATTERMOST_TOKEN", raising=False)
    monkeypatch.delenv("MATTERMOST_URL", raising=False)
    with patch.object(auth, "_fetch_remote", return_value={}):
        with patch.object(auth, "_keychain", side_effect=RuntimeError("Keychain secret not found")):
            with pytest.raises(RuntimeError) as excinfo:
                auth.get_auth()
    msg = str(excinfo.value)
    assert "Keychain secret not found" in msg
    assert "cookiebox" in msg


# ------------------------------------------------------------------
# Defaults and knobs
# ------------------------------------------------------------------

def test_cookie_host_is_off_by_default(monkeypatch):
    monkeypatch.delenv("MATTERMOST_COOKIE_HOST", raising=False)
    assert auth.remote_enabled() is False
    with patch.object(auth.subprocess, "run", side_effect=AssertionError("must not ssh")):
        assert auth.remote_creds() == {}


def test_keychain_service_is_configurable(monkeypatch):
    monkeypatch.setenv("MATTERMOST_KEYCHAIN_SERVICE", "work.mattermost")
    monkeypatch.setattr(auth.sys, "platform", "linux")
    with patch.object(auth.subprocess, "run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "secret\n"
        assert auth._keychain("token") == "secret"
    assert run.call_args[0][0] == ["pass", "show", "work.mattermost/token"]


def test_keychain_service_default(monkeypatch):
    monkeypatch.delenv("MATTERMOST_KEYCHAIN_SERVICE", raising=False)
    monkeypatch.setattr(auth.sys, "platform", "darwin")
    with patch.object(auth.subprocess, "run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "secret\n"
        auth._keychain("token")
    cmd = run.call_args[0][0]
    assert cmd[cmd.index("-s") + 1] == "mattermost-mcp"


def test_cache_file_is_private(monkeypatch, tmp_path):
    _local_host(monkeypatch, tmp_path, "MATTERMOST_URL=https://mm\nMATTERMOST_TOKEN=t1\n")
    auth.remote_creds()
    assert (auth._cache_path().stat().st_mode & 0o777) == 0o600
