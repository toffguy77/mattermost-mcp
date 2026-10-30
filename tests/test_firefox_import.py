"""Import a signed-in session from a Firefox profile."""

from __future__ import annotations

import sqlite3

import pytest

from mattermost_mcp import firefox, session
from mattermost_mcp.session import SessionError


def _profile(tmp_path, cookies):
    base = tmp_path / "firefox"
    prof = base / "abcd.default-release"
    prof.mkdir(parents=True)
    (base / "profiles.ini").write_text(
        "[Install4F96D1932A9F858E]\nDefault=abcd.default-release\nLocked=1\n\n"
        "[Profile0]\nName=default-release\nIsRelative=1\nPath=abcd.default-release\n"
    )
    db = sqlite3.connect(prof / "cookies.sqlite")
    db.execute("CREATE TABLE moz_cookies (id INTEGER PRIMARY KEY, name TEXT, value TEXT, host TEXT, path TEXT, "
               "originAttributes TEXT NOT NULL DEFAULT '')")
    db.executemany("INSERT INTO moz_cookies (name, value, host, path, originAttributes) VALUES (?, ?, ?, '/', ?)",
                   [c if len(c) == 4 else (*c, "") for c in cookies])
    db.commit()
    db.close()
    return base


def test_default_profile_from_profiles_ini(tmp_path):
    base = _profile(tmp_path, [])
    assert firefox.default_profile(base) == base / "abcd.default-release"


def test_import_picks_host_cookies(tmp_path, monkeypatch):
    base = _profile(tmp_path, [
        ("MMAUTHTOKEN", "tok", "mm.example.com"),
        ("MMCSRF", "c", "mm.example.com"),
        ("MMUSERID", "u1", "mm.example.com"),
        ("MMAUTHTOKEN", "other", "chat.other.org"),
    ])
    monkeypatch.setattr(firefox.session, "verify", lambda url, token, csrf, uid: {"id": "u1", "username": "alice"})
    user = firefox.import_session("https://mm.example.com", base_dir=base)
    assert user["username"] == "alice"
    assert session.load()["MATTERMOST_TOKEN"] == "tok"


def test_import_without_session_fails(tmp_path):
    base = _profile(tmp_path, [("MMAUTHTOKEN", "other", "chat.other.org")])
    with pytest.raises(SessionError, match="No Mattermost session for mm.example.com"):
        firefox.import_session("https://mm.example.com", base_dir=base)


def test_explicit_profile_path(tmp_path, monkeypatch):
    base = _profile(tmp_path, [("MMAUTHTOKEN", "tok", "mm.example.com")])
    monkeypatch.setattr(firefox.session, "verify", lambda *a: {"id": "u1", "username": "alice"})
    firefox.import_session("https://mm.example.com", profile=base / "abcd.default-release")
    assert session.load()["MATTERMOST_TOKEN"] == "tok"


def test_container_and_private_cookies_are_ignored(tmp_path, monkeypatch):
    base = _profile(tmp_path, [
        ("MMAUTHTOKEN", "container", "mm.example.com", "^userContextId=2"),
        ("MMAUTHTOKEN", "main", "mm.example.com"),
    ])
    monkeypatch.setattr(firefox.session, "verify", lambda *a: {"id": "u1", "username": "alice"})
    firefox.import_session("https://mm.example.com", base_dir=base)
    assert session.load()["MATTERMOST_TOKEN"] == "main"


def test_unreadable_cookie_db_is_a_clean_error(tmp_path):
    prof = tmp_path / "p"
    prof.mkdir()
    (prof / "cookies.sqlite").write_text("not a database")
    with pytest.raises(SessionError, match="Firefox"):
        firefox.import_session("https://mm.example.com", profile=prof)
