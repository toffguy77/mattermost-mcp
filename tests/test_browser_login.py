"""Browser sign-in: discovery, DevTools port, and the wait-for-session loop."""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from mattermost_mcp import browser_login as bl
from mattermost_mcp import session
from mattermost_mcp.session import SessionError

# ------------------------------------------------------------------
# discovery
# ------------------------------------------------------------------


def test_env_browser_wins(monkeypatch, tmp_path):
    exe = tmp_path / "my-chrome"
    exe.write_text("")
    monkeypatch.setenv("MATTERMOST_BROWSER", str(exe))
    assert bl.find_browser() == str(exe)


def test_env_browser_must_exist(monkeypatch, tmp_path):
    monkeypatch.setenv("MATTERMOST_BROWSER", str(tmp_path / "missing"))
    with pytest.raises(SessionError, match="MATTERMOST_BROWSER"):
        bl.find_browser()


def test_path_candidate_found(monkeypatch):
    monkeypatch.setattr(bl.sys, "platform", "linux")
    monkeypatch.setattr(bl.shutil, "which", lambda n: "/usr/bin/chromium" if n == "chromium" else None)
    assert bl.find_browser() == "/usr/bin/chromium"


def test_no_browser_error_is_helpful(monkeypatch):
    monkeypatch.setattr(bl.sys, "platform", "linux")
    monkeypatch.setattr(bl.shutil, "which", lambda n: None)
    with pytest.raises(SessionError) as e:
        bl.find_browser()
    msg = str(e.value)
    for hint in ("google-chrome", "chromium", "MATTERMOST_BROWSER", "--password", "--from-firefox"):
        assert hint in msg


# ------------------------------------------------------------------
# DevTools endpoint
# ------------------------------------------------------------------


def test_devtools_port_waits_for_file(tmp_path):
    ticks = []

    def sleep(_):
        ticks.append(1)
        if len(ticks) == 2:
            (tmp_path / "DevToolsActivePort").write_text("41234\n/devtools/browser/abc\n")

    assert bl.read_devtools_port(tmp_path, timeout=5, sleep=sleep, alive=lambda: True) == 41234


def test_devtools_port_gives_up_when_browser_exits(tmp_path):
    with pytest.raises(SessionError, match="exited"):
        bl.read_devtools_port(tmp_path, timeout=5, sleep=lambda _: None, alive=lambda: False)


@respx.mock
def test_ws_url_from_json_version():
    respx.get("http://127.0.0.1:41234/json/version").mock(
        return_value=Response(200, json={"webSocketDebuggerUrl": "ws://127.0.0.1:41234/devtools/browser/abc"})
    )
    assert bl.browser_ws_url(41234) == "ws://127.0.0.1:41234/devtools/browser/abc"


# ------------------------------------------------------------------
# cookie selection
# ------------------------------------------------------------------


def _c(name, value, domain="mm.example.com"):
    return {"name": name, "value": value, "domain": domain}


def test_pick_takes_host_cookies_only():
    cookies = [
        _c("MMAUTHTOKEN", "evil", "other.example.org"),
        _c("MMAUTHTOKEN", "tok"),
        _c("MMCSRF", "csrf", ".example.com"),
        _c("MMUSERID", "u1"),
        _c("unrelated", "x"),
    ]
    assert bl.pick_session_cookies(cookies, "mm.example.com") == {"MMAUTHTOKEN": "tok", "MMUSERID": "u1"}


def test_pick_rejects_suffix_lookalike():
    assert bl.pick_session_cookies([_c("MMAUTHTOKEN", "x", "evilmm.example.com")], "mm.example.com") == {}


# ------------------------------------------------------------------
# wait loop
# ------------------------------------------------------------------


class FakeBrowser:
    def __init__(self, frames):
        self.frames = list(frames)
        self.closed = False

    def get_cookies(self):
        return self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]

    def close(self):
        self.closed = True


class Clock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_wait_returns_after_sign_in():
    browser = FakeBrowser([[], [], [_c("MMAUTHTOKEN", "tok"), _c("MMCSRF", "c"), _c("MMUSERID", "u1")]])
    clock = Clock()
    verified = []

    def verify(token, csrf, user_id):
        verified.append(token)
        return {"id": "u1", "username": "alice"}

    got = bl.wait_for_session(browser, "mm.example.com", verify, timeout=60,
                              now=clock.now, sleep=clock.sleep, alive=lambda: True)
    assert got == ({"MMAUTHTOKEN": "tok", "MMCSRF": "c", "MMUSERID": "u1"}, {"id": "u1", "username": "alice"})
    assert verified == ["tok"]


def test_wait_skips_stale_token_from_old_profile():
    browser = FakeBrowser([[_c("MMAUTHTOKEN", "stale")], [_c("MMAUTHTOKEN", "stale")], [_c("MMAUTHTOKEN", "fresh")]])
    clock = Clock()
    seen = []

    def verify(token, csrf, user_id):
        seen.append(token)
        if token == "stale":
            raise SessionError("rejected (401)")
        return {"id": "u1", "username": "alice"}

    cookies, user = bl.wait_for_session(browser, "mm.example.com", verify, timeout=60,
                                        now=clock.now, sleep=clock.sleep, alive=lambda: True)
    assert cookies["MMAUTHTOKEN"] == "fresh"
    assert seen == ["stale", "fresh"]  # each value is verified once


def test_wait_times_out():
    clock = Clock()
    with pytest.raises(SessionError, match="Timed out"):
        bl.wait_for_session(FakeBrowser([[]]), "mm.example.com", lambda *a: {}, timeout=10,
                            now=clock.now, sleep=clock.sleep, alive=lambda: True)


def test_wait_stops_when_browser_closed():
    clock = Clock()
    with pytest.raises(SessionError, match="closed"):
        bl.wait_for_session(FakeBrowser([[]]), "mm.example.com", lambda *a: {}, timeout=60,
                            now=clock.now, sleep=clock.sleep, alive=lambda: False)


# ------------------------------------------------------------------
# login orchestration
# ------------------------------------------------------------------


def test_login_saves_session_and_closes(monkeypatch):
    browser = FakeBrowser([[_c("MMAUTHTOKEN", "tok"), _c("MMCSRF", "c"), _c("MMUSERID", "u1")]])

    class FakeProc:
        def poll(self):
            return None

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

    launched = {}

    def fake_launch(exe, profile, url):
        launched.update(exe=exe, url=url, profile=profile)
        return FakeProc(), browser

    monkeypatch.setattr(bl, "find_browser", lambda: "/usr/bin/chromium")
    monkeypatch.setattr(bl, "_launch", fake_launch)
    monkeypatch.setattr(bl.session, "verify", lambda url, token, csrf, user_id: {"id": "u1", "username": "alice"})

    user = bl.login("https://mm.example.com/", timeout=30)
    assert user["username"] == "alice"
    assert launched["url"] == "https://mm.example.com/login"
    assert browser.closed
    assert session.load()["MATTERMOST_TOKEN"] == "tok"


def test_exact_host_cookies_beat_parent_domain():
    cookies = [
        _c("MMAUTHTOKEN", "tossed", ".example.com"),
        _c("MMUSERID", "attacker", ".example.com"),
        _c("MMAUTHTOKEN", "mine", "mm.example.com"),
        _c("MMCSRF", "mine-csrf", "mm.example.com"),
    ]
    # All three come from one domain, and the exact host wins.
    assert bl.pick_session_cookies(cookies, "mm.example.com") == {"MMAUTHTOKEN": "mine", "MMCSRF": "mine-csrf"}


def test_parent_domain_cookies_are_never_used():
    # Mattermost scopes its cookies to the site host (".mm.example.com" with
    # subdomain cookies on), never to a parent domain, so a parent-domain
    # token can only have been planted by a sibling site.
    cookies = [_c("MMAUTHTOKEN", "tossed", ".example.com"), _c("MMCSRF", "c", ".example.com")]
    assert bl.pick_session_cookies(cookies, "mm.example.com") == {}


def test_subdomain_cookie_setting_is_accepted():
    cookies = [_c("MMAUTHTOKEN", "tok", ".mm.example.com"), _c("MMCSRF", "c", ".mm.example.com")]
    assert bl.pick_session_cookies(cookies, "mm.example.com") == {"MMAUTHTOKEN": "tok", "MMCSRF": "c"}


def test_user_id_must_match_verified_user():
    browser = FakeBrowser([[_c("MMAUTHTOKEN", "tok"), _c("MMUSERID", "someone-else")]])
    clock = Clock()
    with pytest.raises(SessionError, match="Timed out"):
        bl.wait_for_session(browser, "mm.example.com", lambda *a: {"id": "u1", "username": "alice"},
                            timeout=5, now=clock.now, sleep=clock.sleep, alive=lambda: True)


def test_extra_args_cannot_reopen_debugging(monkeypatch):
    monkeypatch.setenv("MATTERMOST_BROWSER_ARGS",
                       "--headless=new --remote-debugging-address=0.0.0.0 --remote-debugging-port=9222")
    assert bl._extra_args() == ["--headless=new"]


def test_pipe_connection_frames_messages():
    import json as _json
    import os
    import threading

    to_browser_r, to_browser_w = os.pipe()
    from_browser_r, from_browser_w = os.pipe()

    def fake_chrome():
        buf = b""
        while not buf.endswith(b"\0"):
            buf += os.read(to_browser_r, 4096)
        req = _json.loads(buf[:-1])
        noise = _json.dumps({"method": "Target.targetCreated", "params": {}}).encode() + b"\0"
        reply = _json.dumps({"id": req["id"], "result": {"cookies": [_c("MMAUTHTOKEN", "t")]}}).encode() + b"\0"
        os.write(from_browser_w, noise + reply)

    threading.Thread(target=fake_chrome, daemon=True).start()
    conn = bl.PipeBrowser(write_fd=to_browser_w, read_fd=from_browser_r)
    assert conn.get_cookies() == [_c("MMAUTHTOKEN", "t")]


def test_host_only_jar_beats_dot_host_jar_and_is_not_mixed():
    cookies = [
        _c("MMAUTHTOKEN", "planted", ".mm.example.com"),
        _c("MMUSERID", "attacker", ".mm.example.com"),
        _c("MMAUTHTOKEN", "mine", "mm.example.com"),
        _c("MMCSRF", "mine-csrf", "mm.example.com"),
    ]
    assert bl.pick_session_cookies(cookies, "mm.example.com") == {"MMAUTHTOKEN": "mine", "MMCSRF": "mine-csrf"}
