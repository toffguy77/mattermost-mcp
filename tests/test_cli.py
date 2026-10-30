"""Command line: serve by default, plus login / status / logout."""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from mattermost_mcp import cli, session


def test_no_args_serves(monkeypatch):
    called = []
    monkeypatch.setattr(cli, "_serve", lambda: called.append("serve"))
    cli.main([])
    assert called == ["serve"]


def test_serve_subcommand(monkeypatch):
    called = []
    monkeypatch.setattr(cli, "_serve", lambda: called.append("serve"))
    cli.main(["serve"])
    assert called == ["serve"]


def test_help_lists_subcommands(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    for word in ("login", "status", "logout", "serve"):
        assert word in out


def test_login_browser_is_default(monkeypatch, capsys):
    seen = {}
    monkeypatch.setattr(cli.browser_login, "login", lambda url, timeout: seen.update(url=url, t=timeout) or
                        {"username": "alice"})
    cli.main(["login", "--url", "https://mm.example.com", "--timeout", "42"])
    assert seen == {"url": "https://mm.example.com", "t": 42}
    assert "Signed in as @alice" in capsys.readouterr().out


def test_login_url_from_env(monkeypatch):
    monkeypatch.setenv("MATTERMOST_URL", "https://env.example.com")
    seen = {}
    monkeypatch.setattr(cli.browser_login, "login", lambda url, timeout: seen.update(url=url) or {"username": "a"})
    cli.main(["login"])
    assert seen["url"] == "https://env.example.com"


def test_login_without_url_fails(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["login"])
    assert e.value.code != 0
    assert "--url" in capsys.readouterr().err


def test_login_password(monkeypatch):
    seen = {}

    def fake(url, login_id, password, prompt_mfa):
        seen.update(url=url, login_id=login_id, password=password)
        return {"username": "alice"}

    monkeypatch.setattr(cli.password_login, "login", fake)
    monkeypatch.setattr(cli, "_input", lambda prompt: "alice")
    monkeypatch.setattr(cli, "_getpass", lambda prompt: "pw")
    cli.main(["login", "--password", "--url", "https://mm"])
    assert seen == {"url": "https://mm", "login_id": "alice", "password": "pw"}


def test_login_firefox(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(cli.firefox, "import_session",
                        lambda url, profile=None: seen.update(url=url, profile=profile) or {"username": "a"})
    cli.main(["login", "--from-firefox", "--profile", str(tmp_path), "--url", "https://mm"])
    assert seen == {"url": "https://mm", "profile": tmp_path}


def test_login_failure_exits_nonzero(monkeypatch, capsys):
    def boom(url, timeout):
        raise session.SessionError("Timed out after 300s waiting for you to sign in.")

    monkeypatch.setattr(cli.browser_login, "login", boom)
    with pytest.raises(SystemExit) as e:
        cli.main(["login", "--url", "https://mm"])
    assert e.value.code == 1
    assert "Timed out" in capsys.readouterr().err


@respx.mock
def test_status_shows_user_without_secrets(capsys):
    session.save("https://mm.example.com", token="secret-session-token", csrf="secret-csrf", user_id="u1")
    respx.get("https://mm.example.com/api/v4/users/me").mock(
        return_value=Response(200, json={"id": "u1", "username": "alice"})
    )
    cli.main(["status"])
    out = capsys.readouterr().out
    assert "alice" in out
    assert "cookie" in out
    assert "session" in out
    assert "secret" not in out


def test_status_reports_missing_credentials(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["status"])
    assert e.value.code == 1
    assert "login" in capsys.readouterr().err


@respx.mock
def test_logout_revokes_and_deletes(tmp_path, capsys):
    session.save("https://mm.example.com", token="tok", csrf="c")
    revoke = respx.post("https://mm.example.com/api/v4/users/logout").mock(return_value=Response(200, json={}))
    profile = session.profile_dir()
    cli.main(["logout", "--forget-browser"])
    assert revoke.called
    assert revoke.calls.last.request.headers["X-CSRF-Token"] == "c"
    assert session.load() == {}
    assert not profile.exists()


@respx.mock
def test_logout_survives_unreachable_server(capsys):
    session.save("https://mm.example.com", token="tok")
    respx.post("https://mm.example.com/api/v4/users/logout").mock(return_value=Response(500))
    cli.main(["logout"])
    assert session.load() == {}


def test_logout_without_session(capsys):
    cli.main(["logout"])
    assert "No saved session" in capsys.readouterr().out
