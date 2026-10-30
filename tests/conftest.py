"""Shared fixtures.

The cookie host source in auth.py shells out to `ssh`. Nothing in the unit
suite may do that — a developer machine with a live `cookiebox` alias would make
tests pass for the wrong reason, and a machine without one would pay a DNS
timeout per test. So the source is off by default and each test that exercises
it turns it on explicitly, pointed at a tmp file.

Likewise a developer's own MATTERMOST_* credentials must not leak into tests.
"""

from __future__ import annotations

import pytest

_AUTH_VARS = (
    "MATTERMOST_URL",
    "MATTERMOST_TOKEN",
    "MATTERMOST_CSRF",
    "MATTERMOST_USER_ID",
    "MATTERMOST_ACCESS_TOKEN",
    "MATTERMOST_AUTH_MODE",
    "MATTERMOST_ENABLE_WRITE",
    "MATTERMOST_CACHE_TTL",
    "MATTERMOST_AUTH_HELP",
    "MATTERMOST_AUTO_LOGIN",
    "MATTERMOST_BROWSER",
    "MATTERMOST_BROWSER_ARGS",
    "MATTERMOST_LOGIN_TIMEOUT",
)


@pytest.fixture(autouse=True)
def _no_cookie_host(monkeypatch, tmp_path):
    monkeypatch.setenv("MATTERMOST_COOKIE_HOST", "off")
    monkeypatch.setenv("MATTERMOST_COOKIE_CACHE", str(tmp_path / "cookie.cache"))
    # Never read or write the developer's real saved session or browser profile.
    monkeypatch.setenv("MATTERMOST_SESSION_FILE", str(tmp_path / "session.env"))
    monkeypatch.setenv("MATTERMOST_BROWSER_PROFILE", str(tmp_path / "browser-profile"))
    for var in _AUTH_VARS:
        monkeypatch.delenv(var, raising=False)
