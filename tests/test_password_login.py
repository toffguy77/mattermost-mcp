"""Sign in with username and password (+ MFA)."""

from __future__ import annotations

import json

import pytest
import respx
from httpx import Response

from mattermost_mcp import password_login, session
from mattermost_mcp.session import SessionError

URL = "https://mm.example.com"


def _ok(**headers):
    return Response(
        200,
        json={"id": "u1", "username": "alice"},
        headers=[("Token", "sess-token"), ("Set-Cookie", "MMCSRF=csrf-1; Path=/"),
                 ("Set-Cookie", "MMUSERID=u1; Path=/")],
    )


@respx.mock
def test_password_login_saves_session():
    route = respx.post(f"{URL}/api/v4/users/login").mock(return_value=_ok())
    user = password_login.login(URL, login_id="alice", password="hunter2", prompt_mfa=lambda: pytest.fail("no MFA"))
    assert user["username"] == "alice"
    assert json.loads(route.calls.last.request.content) == {"login_id": "alice", "password": "hunter2"}
    assert session.load() == {
        "MATTERMOST_URL": URL, "MATTERMOST_TOKEN": "sess-token",
        "MATTERMOST_CSRF": "csrf-1", "MATTERMOST_USER_ID": "u1",
    }


@respx.mock
def test_mfa_prompted_and_retried():
    mfa_needed = Response(401, json={"id": "mfa.validate_token.authenticate.app_error", "message": "Invalid MFA token."})
    route = respx.post(f"{URL}/api/v4/users/login").mock(side_effect=[mfa_needed, _ok()])
    password_login.login(URL, login_id="alice", password="pw", prompt_mfa=lambda: "123456")
    assert json.loads(route.calls.last.request.content)["token"] == "123456"


@respx.mock
def test_wrong_password_saves_nothing_and_hides_password():
    respx.post(f"{URL}/api/v4/users/login").mock(
        return_value=Response(401, json={"id": "api.user.login.invalid_credentials_email_username", "message": "bad"})
    )
    with pytest.raises(SessionError) as e:
        password_login.login(URL, login_id="alice", password="hunter2", prompt_mfa=lambda: "")
    assert "rejected" in str(e.value)
    assert "hunter2" not in str(e.value)
    assert session.load() == {}
