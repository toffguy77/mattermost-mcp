"""Sign in through a real browser and take the session cookies from it.

Runs an installed Chromium-family browser (Chrome, Chromium, Edge, Brave)
with its own profile and the DevTools protocol on a random loopback port,
opens <url>/login, and polls the browser's cookie jar until it holds an
MMAUTHTOKEN that Mattermost accepts. Whatever the user does in between —
password, SSO, MFA — is between them and their identity provider.

The profile persists, so an identity-provider session usually survives and a
later sign-in completes without any typing.
"""

from __future__ import annotations

import contextlib
import itertools
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

import httpx

from . import session
from .session import SessionError

_COOKIES = ("MMAUTHTOKEN", "MMCSRF", "MMUSERID")

_PATH_NAMES = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "microsoft-edge",
    "microsoft-edge-stable",
    "brave-browser",
)

_MAC_APPS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
)

_WIN_APPS = (
    r"Google\Chrome\Application\chrome.exe",
    r"Microsoft\Edge\Application\msedge.exe",
    r"BraveSoftware\Brave-Browser\Application\brave.exe",
    r"Chromium\Application\chrome.exe",
)


def _candidates() -> list[str]:
    found: list[str] = []
    if sys.platform == "darwin":
        found += [p for p in _MAC_APPS if Path(p).exists()]
        found += [str(Path.home()) + p for p in _MAC_APPS if Path(str(Path.home()) + p).exists()]
    elif sys.platform == "win32":
        roots = [os.environ.get(k, "") for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        found += [str(Path(r) / a) for r in roots if r for a in _WIN_APPS if (Path(r) / a).exists()]
    found += [p for p in (shutil.which(n) for n in _PATH_NAMES) if p]
    return found


def find_browser() -> str:
    override = os.environ.get("MATTERMOST_BROWSER", "").strip()
    if override:
        if Path(override).expanduser().exists():
            return str(Path(override).expanduser())
        raise SessionError(f"MATTERMOST_BROWSER points to {override}, which does not exist.")
    found = _candidates()
    if found:
        return found[0]
    raise SessionError(
        "No Chromium-family browser found (looked for " + ", ".join(_PATH_NAMES) + " and the "
        "standard Chrome/Edge/Brave install locations). Set MATTERMOST_BROWSER to the browser's "
        "executable, or sign in with `login --password` or `login --from-firefox`."
    )


def read_devtools_port(
    profile: Path,
    timeout: float = 30,
    sleep: Callable[[float], None] = time.sleep,
    alive: Callable[[], bool] = lambda: True,
) -> int:
    """Chrome writes the port it picked for --remote-debugging-port=0 here."""
    path = Path(profile) / "DevToolsActivePort"
    waited = 0.0
    while waited <= timeout:
        try:
            first = path.read_text().splitlines()[0].strip()
            if first:
                return int(first)
        except (OSError, IndexError, ValueError):
            pass
        if not alive():
            raise SessionError("The browser exited before it opened its DevTools port.")
        sleep(0.2)
        waited += 0.2
    raise SessionError("The browser did not open its DevTools port in time.")


def browser_ws_url(port: int) -> str:
    # Loopback only, never through a proxy.
    with httpx.Client(timeout=5.0, trust_env=False) as http:
        return http.get(f"http://127.0.0.1:{port}/json/version").json()["webSocketDebuggerUrl"]


class CdpBrowser:
    """The two DevTools calls we need, over the browser-level websocket."""

    def __init__(self, ws_url: str):
        from websockets.sync.client import connect

        self._stack = contextlib.ExitStack()
        self._ws = self._stack.enter_context(connect(ws_url, max_size=None, open_timeout=10))
        self._ids = itertools.count(1)

    def _call(self, method: str, params: dict | None = None) -> dict:
        msg_id = next(self._ids)
        self._ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        while True:
            reply = json.loads(self._ws.recv(timeout=10))
            if reply.get("id") == msg_id:
                if "error" in reply:
                    raise SessionError(f"Browser refused {method}: {reply['error'].get('message')}")
                return reply.get("result", {})

    def get_cookies(self) -> list[dict]:
        return self._call("Storage.getCookies").get("cookies", [])

    def close(self) -> None:
        try:
            self._call("Browser.close")
        except Exception:
            pass
        try:
            self._stack.close()
        except Exception:
            pass


def _domain_matches(domain: str, host: str) -> bool:
    domain = domain.lstrip(".").lower()
    host = host.lower()
    return host == domain or host.endswith("." + domain)


def pick_session_cookies(cookies: list[dict], host: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for c in cookies:
        if c.get("name") in _COOKIES and c.get("value") and _domain_matches(c.get("domain", ""), host):
            out.setdefault(c["name"], c["value"])
    return out


def wait_for_session(
    browser,
    host: str,
    verify: Callable[[str, str, str], dict],
    timeout: float,
    now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    alive: Callable[[], bool] = lambda: True,
    interval: float = 1.0,
) -> tuple[dict[str, str], dict]:
    """Poll the cookie jar until Mattermost accepts an MMAUTHTOKEN.

    A persistent profile may still hold an expired token, so each distinct
    value is verified once and rejected values are skipped.
    """
    deadline = now() + timeout
    tried: set[str] = set()
    while now() < deadline:
        if not alive():
            raise SessionError("The browser was closed before sign-in finished.")
        try:
            cookies = pick_session_cookies(browser.get_cookies(), host)
        except SessionError:
            raise
        except Exception:
            # The websocket goes away when the user closes the window.
            if not alive():
                raise SessionError("The browser was closed before sign-in finished.") from None
            cookies = {}
        token = cookies.get("MMAUTHTOKEN", "")
        if token and token not in tried:
            tried.add(token)
            try:
                user = verify(token, cookies.get("MMCSRF", ""), cookies.get("MMUSERID", ""))
                return cookies, user
            except SessionError:
                pass
        sleep(interval)
    raise SessionError(f"Timed out after {int(timeout)}s waiting for you to sign in.")


def _launch(exe: str, profile: Path, url: str):
    stale = profile / "DevToolsActivePort"
    stale.unlink(missing_ok=True)
    args = [
        exe,
        f"--user-data-dir={profile}",
        "--remote-debugging-port=0",
        "--remote-debugging-address=127.0.0.1",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
    ]
    extra = os.environ.get("MATTERMOST_BROWSER_ARGS", "").split()
    proc = subprocess.Popen(
        [*args, *extra, url],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        port = read_devtools_port(profile, alive=lambda: proc.poll() is None)
        return proc, CdpBrowser(browser_ws_url(port))
    except BaseException:
        proc.terminate()
        raise


def login(url: str, timeout: float = 300) -> dict:
    """Run the browser sign-in, save the session, return the user."""
    url = url.rstrip("/")
    host = urlparse(url).hostname or ""
    if not host:
        raise SessionError(f"Not a server URL: {url!r}")
    proc, browser = _launch(find_browser(), session.profile_dir(), f"{url}/login")
    try:
        cookies, user = wait_for_session(
            browser,
            host,
            lambda token, csrf, uid: session.verify(url, token, csrf, uid),
            timeout=timeout,
            alive=lambda: proc.poll() is None,
        )
    finally:
        browser.close()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.terminate()
    session.save(url, cookies["MMAUTHTOKEN"], cookies.get("MMCSRF", ""), cookies.get("MMUSERID", ""))
    return user
