"""The saved session: Mattermost session cookies obtained by `login`.

Stored as KEY=VALUE lines (the cookie host format) in MATTERMOST_SESSION_FILE,
default ~/.config/mattermost-mcp/session.env, mode 0600. The browser profile
used for sign-in lives next to it (MATTERMOST_BROWSER_PROFILE), mode 0700.
"""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
import time
from pathlib import Path

import httpx

_KEYS = ("MATTERMOST_URL", "MATTERMOST_TOKEN", "MATTERMOST_CSRF", "MATTERMOST_USER_ID")


class SessionError(RuntimeError):
    """Signing in or verifying a session failed. Never carries secrets."""


class SessionRejected(SessionError):
    """The server answered 401: this session is not (or no longer) valid."""


def _config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME", "").strip()
    return (Path(base) if base else Path.home() / ".config") / "mattermost-mcp"


def session_path() -> Path:
    override = os.environ.get("MATTERMOST_SESSION_FILE", "").strip()
    return Path(override).expanduser() if override else _config_dir() / "session.env"


def profile_dir() -> Path:
    """The browser profile for sign-in, created private (0700)."""
    override = os.environ.get("MATTERMOST_BROWSER_PROFILE", "").strip()
    path = Path(override).expanduser() if override else _config_dir() / "browser-profile"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def write_private(path: Path, text: str) -> None:
    """Write a secret file atomically, 0600 from the first byte."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # A unique name per writer (mkstemp: O_EXCL, 0600), so two concurrent
    # sign-ins cannot trip over each other's temporary file.
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def load() -> dict[str, str]:
    from .auth import parse_cookie_env  # auth imports this module

    try:
        return parse_cookie_env(session_path().read_text())
    except OSError:
        return {}


def save(url: str, token: str, csrf: str = "", user_id: str = "") -> Path:
    values = dict(zip(_KEYS, (url.rstrip("/"), token, csrf, user_id), strict=True))
    path = session_path()
    write_private(path, "".join(f"{k}={v}\n" for k, v in values.items() if v))
    return path


def delete() -> bool:
    try:
        session_path().unlink()
        return True
    except FileNotFoundError:
        return False


def cookie_headers(token: str, csrf: str = "", user_id: str = "") -> dict[str, str]:
    cookie = f"MMAUTHTOKEN={token}"
    if user_id:
        cookie += f"; MMUSERID={user_id}"
    headers = {"Cookie": cookie}
    if csrf:
        headers["X-CSRF-Token"] = csrf
    return headers


def http_client() -> httpx.Client:
    trust = os.environ.get("MATTERMOST_TRUST_ENV", "1").strip().lower() not in {"0", "false", "no", "off"}
    return httpx.Client(timeout=30.0, trust_env=trust)


def verify(url: str, token: str, csrf: str = "", user_id: str = "") -> dict:
    """Return /users/me for these cookies, or raise SessionError."""
    url = url.rstrip("/")
    try:
        with http_client() as http:
            r = http.get(f"{url}/api/v4/users/me", headers=cookie_headers(token, csrf, user_id))
    except httpx.HTTPError as e:
        raise SessionError(f"Could not reach {url}: {type(e).__name__}") from None
    if r.status_code == 401:
        raise SessionRejected(f"{url} rejected the session (401).")
    if r.status_code != 200:
        raise SessionError(f"{url} answered {r.status_code} to /api/v4/users/me.")
    return r.json()


@contextlib.contextmanager
def login_lock():
    """Inter-process lock so several servers share one sign-in window."""
    path = session_path().with_name(session_path().name + ".lock")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with open(path, "a+") as f:
        if sys.platform == "win32":
            import msvcrt

            f.seek(0)
            # LK_LOCK gives up after ~10 s; another process may be in a
            # five-minute sign-in, so wait for as long as it takes.
            while True:
                try:
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.5)
            try:
                yield
            finally:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
