"""Shared fixtures.

The cookie host source in auth.py shells out to `ssh`. Nothing in the unit
suite may do that — a developer machine with a live `cookiebox` alias would make
tests pass for the wrong reason, and a machine without one would pay a DNS
timeout per test. So the source is off by default and each test that exercises
it turns it on explicitly, pointed at a tmp file.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_cookie_host(monkeypatch, tmp_path):
    monkeypatch.setenv("MATTERMOST_COOKIE_HOST", "off")
    monkeypatch.setenv("MATTERMOST_COOKIE_CACHE", str(tmp_path / "cookie.cache"))
