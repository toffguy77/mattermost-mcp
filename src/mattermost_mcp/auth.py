"""Read Mattermost credentials.

Cookie mode only. Session cookies are taken from a logged-in browser
(DevTools -> Application -> Cookies -> your Mattermost host):

  MATTERMOST_URL=https://mattermost.example.com
  MATTERMOST_TOKEN=<MMAUTHTOKEN cookie>
  MATTERMOST_CSRF=<MMCSRF cookie>
  MATTERMOST_USER_ID=<MMUSERID cookie>   # optional

Cookies rather than a personal access token because some deployments put a
reverse proxy in front of Mattermost that strips the Authorization header,
and PATs are often disabled by admins anyway.

Sources, first non-empty value wins, resolved per field:

  1. MATTERMOST_* environment variables.

  2. A cookie host: a flat KEY=VALUE export on another machine, pulled over
     ssh and cached locally. This lets several machines share one cookie that
     is rotated in a single place. Off unless MATTERMOST_COOKIE_HOST is set.

  3. OS keychain (macOS Keychain / `pass` on Linux) — manual bootstrap.

Cookie host settings (all optional):

  MATTERMOST_COOKIE_HOST         ssh host alias; unset/"off" disables the source,
                                 "local" reads MATTERMOST_COOKIE_PATH on this machine
  MATTERMOST_COOKIE_PATH         export path, relative to $HOME on the host
                                 (default: .config/mattermost-mcp/cookie.env)
  MATTERMOST_COOKIE_CACHE        local cache file
                                 (default: ~/.cache/mattermost-mcp/cookie.cache)
  MATTERMOST_COOKIE_TTL          cache lifetime in seconds (default: 900)
  MATTERMOST_COOKIE_SSH_TIMEOUT  ssh timeout in seconds (default: 10)

Keychain fallback: same keys without the MATTERMOST_ prefix, lowercased, as
accounts under service MATTERMOST_KEYCHAIN_SERVICE (default: mattermost-mcp):

  macOS:  security add-generic-password -s mattermost-mcp -a <account> -w <value>
  Linux:  pass insert mattermost-mcp/<account>
"""

from __future__ import annotations

import dataclasses
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

_DEFAULT_SERVICE = "mattermost-mcp"

# The only fields a cookie host may supply. Anything else in the export is
# ignored: the file must not be able to smuggle arbitrary env into the process.
_REMOTE_KEYS = (
    "MATTERMOST_URL",
    "MATTERMOST_TOKEN",
    "MATTERMOST_CSRF",
    "MATTERMOST_USER_ID",
)

_DISABLED_HOSTS = {"", "off", "none", "no", "0"}


@dataclasses.dataclass
class MattermostAuth:
    url: str
    token: str
    csrf: str = ""
    user_id: str = ""
    mode: str = "cookie"  # legacy field, always "cookie"


def _env(key: str) -> str:
    return os.environ.get(key, "").strip()


def _service() -> str:
    return _env("MATTERMOST_KEYCHAIN_SERVICE") or _DEFAULT_SERVICE


# ---------------------------------------------------------------------------
# Keychain / pass
# ---------------------------------------------------------------------------

def _keychain_get_macos(account: str, required: bool = True) -> str:
    service = _service()
    result = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        if not required:
            return ""
        raise RuntimeError(
            f"Keychain secret not found: service={service} account={account}\n"
            f"  security add-generic-password -s {service} -a {account} -w <value>"
        )
    return result.stdout.strip()


def _keychain_get_pass(account: str, required: bool = True) -> str:
    pass_key = f"{_service()}/{account}"
    result = subprocess.run(["pass", "show", pass_key], capture_output=True, text=True)
    if result.returncode != 0:
        if not required:
            return ""
        raise RuntimeError(
            f"pass secret not found: {pass_key}\n"
            f"  pass insert {pass_key}"
        )
    return result.stdout.strip().splitlines()[0]


def _keychain(account: str, required: bool = True) -> str:
    if sys.platform == "darwin":
        return _keychain_get_macos(account, required=required)
    return _keychain_get_pass(account, required=required)


# ---------------------------------------------------------------------------
# Cookie host — pull over ssh, cache locally
# ---------------------------------------------------------------------------

def _remote_host() -> str:
    return _env("MATTERMOST_COOKIE_HOST")


def _remote_path() -> str:
    return _env("MATTERMOST_COOKIE_PATH") or ".config/mattermost-mcp/cookie.env"


def _cache_path() -> Path:
    override = _env("MATTERMOST_COOKIE_CACHE")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".cache" / "mattermost-mcp" / "cookie.cache"


def _int_env(key: str, default: int) -> int:
    try:
        return int(_env(key) or default)
    except ValueError:
        return default


def _cache_ttl() -> int:
    return _int_env("MATTERMOST_COOKIE_TTL", 900)


def _ssh_timeout() -> int:
    return _int_env("MATTERMOST_COOKIE_SSH_TIMEOUT", 10)


def parse_cookie_env(blob: str) -> dict[str, str]:
    """Parse the flat KEY=VALUE export into a dict, keeping only known keys.

    Deliberately not a dotenv parser: no `export `, no interpolation, no
    multiline values. Cookie values never contain newlines, so whatever
    rotates the cookie on the host only has to emit `KEY=VALUE` lines.
    """
    out: dict[str, str] = {}
    for raw in blob.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key in _REMOTE_KEYS:
            value = value.strip().strip("'\"")
            if value:
                out[key] = value
    return out


def _cache_read(max_age: int | None) -> dict[str, str]:
    path = _cache_path()
    try:
        stat = path.stat()
    except OSError:
        return {}
    if max_age is not None and (time.time() - stat.st_mtime) > max_age:
        return {}
    try:
        return parse_cookie_env(path.read_text())
    except OSError:
        return {}


def _cache_write(creds: dict[str, str]) -> None:
    path = _cache_path()
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp.unlink(missing_ok=True)
        # 0600 from the first byte: chmod after write leaves a window where
        # the cookie is world-readable under a permissive umask.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "w") as f:
            f.write("".join(f"{k}={creds[k]}\n" for k in _REMOTE_KEYS if creds.get(k)))
        os.replace(tmp, path)
    except OSError:
        # A cookie we can't cache is still a cookie we can use — the only cost
        # is an ssh round-trip on the next start.
        try:
            tmp.unlink()
        except OSError:
            pass


def _log_remote_failure(detail: str) -> None:
    """Why the cookie host was skipped, on stderr.

    Silence here is expensive: the client falls back to keychain and the user
    sees a generic "secret not found" that says nothing about ssh. A GUI-
    launched MCP child inherits no shell environment, so the usual cause is a
    missing SSH_AUTH_SOCK or an unreadable key — invisible unless we say so.
    stderr, not stdout: stdout is the MCP stdio channel.
    """
    print(f"[mattermost-mcp] cookie host unavailable: {detail}", file=sys.stderr, flush=True)


def _fetch_remote() -> dict[str, str]:
    host = _remote_host()
    if host.lower() in _DISABLED_HOSTS:
        return {}

    path = _remote_path()
    if host.lower() == "local":
        try:
            return parse_cookie_env(Path(path).expanduser().read_text())
        except OSError:
            return {}

    timeout = _ssh_timeout()
    cmd = [
        "ssh",
        # BatchMode: a missing/locked key must fail fast, never sit at a
        # passphrase prompt — this runs inside the MCP stdio handshake.
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={timeout}",
        host,
        f"cat -- {shlex.quote(path)}",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)
    except (OSError, subprocess.SubprocessError) as e:
        _log_remote_failure(f"ssh could not run: {e}")
        return {}
    if result.returncode != 0:
        _log_remote_failure(
            f"ssh {host} exited {result.returncode}: {(result.stderr or '').strip()[:400]}"
        )
        return {}
    creds = parse_cookie_env(result.stdout)
    if not creds:
        _log_remote_failure(f"{host}:{path} produced no MATTERMOST_* lines")
    return creds


def remote_creds(*, force: bool = False) -> dict[str, str]:
    """Cookies from the cookie host, cached for MATTERMOST_COOKIE_TTL seconds.

    force=True skips the cache (used after a 401, when the cached cookie is
    known to be dead). If the host is unreachable, a stale cache still beats
    no credentials at all — the caller finds out via 401, not via a hang.
    """
    if not remote_enabled():
        # Turning the source off must also disown its cache — otherwise "off"
        # silently keeps serving the last cookie it ever pulled.
        return {}
    if not force:
        cached = _cache_read(_cache_ttl())
        if cached:
            return cached
    fresh = _fetch_remote()
    if fresh:
        _cache_write(fresh)
        return fresh
    return _cache_read(None)


def refresh_remote() -> dict[str, str]:
    """Re-pull from the cookie host, ignoring the cache. Called on 401."""
    return remote_creds(force=True)


def remote_enabled() -> bool:
    return _remote_host().lower() not in _DISABLED_HOSTS


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def get_auth() -> MattermostAuth:
    """Return cookie-mode auth config. PAT/Bearer is no longer supported."""
    remote: dict[str, str] | None = None

    def _from_remote(key: str) -> str:
        nonlocal remote
        if remote is None:
            remote = remote_creds()
        return remote.get(key, "")

    def _pick(env_key: str, account: str, required: bool = True) -> str:
        value = _env(env_key)
        if value:
            return value
        value = _from_remote(env_key)
        if value:
            return value
        try:
            return _keychain(account, required=required)
        except RuntimeError as e:
            if not remote_enabled():
                raise
            raise RuntimeError(
                f"{e}\n"
                f"  ...and the cookie host ({_remote_host()}:{_remote_path()}) gave "
                f"nothing either — check `ssh {_remote_host()} cat {_remote_path()}`."
            ) from e

    url = _pick("MATTERMOST_URL", "url").rstrip("/")
    token = _pick("MATTERMOST_TOKEN", "token")
    csrf = _pick("MATTERMOST_CSRF", "csrf", required=False)
    user_id = _pick("MATTERMOST_USER_ID", "user_id", required=False)
    return MattermostAuth(url=url, token=token, csrf=csrf, user_id=user_id)


# Legacy shim used by tests
def get_credentials() -> tuple[str, str]:
    auth = get_auth()
    return auth.url, auth.token
