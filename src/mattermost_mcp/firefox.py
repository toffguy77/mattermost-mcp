"""Import a signed-in Mattermost session from a Firefox profile.

Firefox keeps cookies unencrypted in cookies.sqlite. The database is locked
while Firefox runs, so a copy is read instead.
"""

from __future__ import annotations

import configparser
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from . import session
from .browser_login import pick_session_cookies
from .session import SessionError


def base_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Firefox"
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", "")) / "Mozilla" / "Firefox"
    return Path.home() / ".mozilla" / "firefox"


def default_profile(base: Path | None = None) -> Path:
    base = Path(base) if base else base_dir()
    ini = configparser.ConfigParser()
    if not ini.read(base / "profiles.ini"):
        raise SessionError(f"No Firefox profiles found in {base}; pass --profile.")

    def resolve(section) -> Path:
        path = section["Path"]
        return base / path if section.get("IsRelative", "1") == "1" else Path(path)

    # The profile Firefox actually starts with is recorded per install.
    for name in ini.sections():
        if name.startswith("Install") and ini[name].get("Default"):
            return base / ini[name]["Default"]
    for name in ini.sections():
        if name.startswith("Profile") and ini[name].get("Default") == "1":
            return resolve(ini[name])
    profiles = [ini[n] for n in ini.sections() if n.startswith("Profile")]
    if profiles:
        return resolve(profiles[0])
    raise SessionError(f"No Firefox profiles found in {base}; pass --profile.")


def _read_cookies(profile: Path) -> list[dict]:
    src = profile / "cookies.sqlite"
    if not src.exists():
        raise SessionError(f"No cookies.sqlite in Firefox profile {profile}.")
    with tempfile.TemporaryDirectory() as tmp:
        dst = Path(tmp) / "cookies.sqlite"
        try:
            # WAL first: copying it after the main file could pair a newer
            # log with an older database.
            wal = profile / "cookies.sqlite-wal"
            if wal.exists():
                shutil.copy2(wal, Path(tmp) / "cookies.sqlite-wal")
            shutil.copy2(src, dst)
            db = sqlite3.connect(dst)
            try:
                # Default container, normal windows only: no originAttributes.
                rows = db.execute(
                    "SELECT name, value, host FROM moz_cookies "
                    "WHERE name IN ('MMAUTHTOKEN', 'MMCSRF', 'MMUSERID') AND originAttributes = ''"
                ).fetchall()
            finally:
                db.close()
        except (OSError, sqlite3.Error) as e:
            raise SessionError(f"Could not read Firefox cookies in {profile}: {e}") from None
    return [{"name": n, "value": v, "domain": h} for n, v, h in rows]


def import_session(url: str, profile: Path | None = None, base_dir: Path | None = None) -> dict:
    url = url.rstrip("/")
    host = urlparse(url).hostname or ""
    profile = Path(profile) if profile else default_profile(base_dir)
    cookies = pick_session_cookies(_read_cookies(profile), host)
    if "MMAUTHTOKEN" not in cookies:
        raise SessionError(
            f"No Mattermost session for {host} in Firefox profile {profile}. Sign in there first."
        )
    token, csrf, user_id = cookies["MMAUTHTOKEN"], cookies.get("MMCSRF", ""), cookies.get("MMUSERID", "")
    user = session.verify(url, token, csrf, user_id)
    session.save(url, token, csrf, user_id)
    return user
