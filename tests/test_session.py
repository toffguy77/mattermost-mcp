"""Saved session: storage and verification."""

from __future__ import annotations

import os
import stat

import pytest
import respx
from httpx import Response

from mattermost_mcp import session


def test_round_trip(tmp_path):
    session.save("https://mm.example.com/", token="tok", csrf="csrf", user_id="u1")
    assert session.load() == {
        "MATTERMOST_URL": "https://mm.example.com",
        "MATTERMOST_TOKEN": "tok",
        "MATTERMOST_CSRF": "csrf",
        "MATTERMOST_USER_ID": "u1",
    }


def test_missing_file_loads_empty():
    assert session.load() == {}


def test_file_and_directory_are_private(tmp_path, monkeypatch):
    path = tmp_path / "nested" / "session.env"
    monkeypatch.setenv("MATTERMOST_SESSION_FILE", str(path))
    os.umask(0o022)
    session.save("https://mm", token="tok")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_save_replaces_atomically(tmp_path):
    session.save("https://mm", token="one")
    session.save("https://mm", token="two")
    assert session.load()["MATTERMOST_TOKEN"] == "two"
    assert not list(tmp_path.glob("*.tmp"))


def test_delete():
    session.save("https://mm", token="tok")
    assert session.delete() is True
    assert session.load() == {}
    assert session.delete() is False


def test_profile_dir_is_private(tmp_path):
    path = session.profile_dir()
    assert path == tmp_path / "browser-profile"
    assert stat.S_IMODE(path.stat().st_mode) == 0o700


@respx.mock
def test_verify_returns_user_and_sends_cookies():
    route = respx.get("https://mm/api/v4/users/me").mock(
        return_value=Response(200, json={"id": "u1", "username": "alice"})
    )
    user = session.verify("https://mm", token="tok", csrf="c", user_id="u1")
    assert user["username"] == "alice"
    headers = route.calls.last.request.headers
    assert headers["Cookie"] == "MMAUTHTOKEN=tok; MMUSERID=u1"
    assert headers["X-CSRF-Token"] == "c"


@respx.mock
def test_verify_rejects_401_without_leaking():
    respx.get("https://mm/api/v4/users/me").mock(return_value=Response(401))
    with pytest.raises(session.SessionError) as e:
        session.verify("https://mm", token="secret-tok")
    assert "secret-tok" not in str(e.value)
