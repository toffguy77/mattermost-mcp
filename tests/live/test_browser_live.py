"""Real browser sign-in against a local fake Mattermost.

Skipped unless MATTERMOST_TEST_BROWSER points to a Chromium-family binary:

    MATTERMOST_TEST_BROWSER=/path/to/chrome uv run pytest tests/live -v
"""

from __future__ import annotations

import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from mattermost_mcp import browser_login, session

BROWSER = os.environ.get("MATTERMOST_TEST_BROWSER", "")
pytestmark = pytest.mark.skipif(not BROWSER, reason="set MATTERMOST_TEST_BROWSER to run")


class _FakeMattermost(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.startswith("/login"):
            # "Signing in" is just loading the page: it sets the session cookies.
            self.send_response(200)
            self.send_header("Set-Cookie", "MMAUTHTOKEN=live-token; Path=/; HttpOnly")
            self.send_header("Set-Cookie", "MMCSRF=live-csrf; Path=/")
            self.send_header("Set-Cookie", "MMUSERID=live-user; Path=/")
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body>signed in</body></html>")
        elif self.path == "/api/v4/users/me":
            ok = "MMAUTHTOKEN=live-token" in (self.headers.get("Cookie") or "")
            self.send_response(200 if ok else 401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"id": "live-user", "username": "live"}' if ok else b"{}")
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture
def fake_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeMattermost)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_real_browser_sign_in(fake_server, monkeypatch):
    monkeypatch.setenv("MATTERMOST_BROWSER", BROWSER)
    monkeypatch.setenv("MATTERMOST_BROWSER_ARGS", "--headless=new --no-sandbox")
    user = browser_login.login(fake_server, timeout=60)
    assert user["username"] == "live"
    saved = session.load()
    assert saved["MATTERMOST_TOKEN"] == "live-token"
    assert saved["MATTERMOST_CSRF"] == "live-csrf"
    assert saved["MATTERMOST_USER_ID"] == "live-user"
