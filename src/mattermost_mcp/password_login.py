"""Sign in with a login ID and password (and an MFA code if required).

The password goes to /api/v4/users/login once and is never stored; what is
saved is the session token Mattermost hands back, as a browser would.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from . import session
from .session import SessionError

_MFA_ERRORS = ("mfa.validate_token.authenticate.app_error", "api.user.check_user_mfa.bad_code.app_error")


def _needs_mfa(r: httpx.Response) -> bool:
    try:
        body = r.json()
    except ValueError:
        return False
    return body.get("id") in _MFA_ERRORS or "mfa" in str(body.get("message", "")).lower()


def login(url: str, login_id: str, password: str, prompt_mfa: Callable[[], str]) -> dict:
    url = url.rstrip("/")
    body = {"login_id": login_id, "password": password}
    with session.http_client() as http:
        try:
            r = http.post(f"{url}/api/v4/users/login", json=body)
            if r.status_code == 401 and _needs_mfa(r):
                body["token"] = prompt_mfa().strip()
                r = http.post(f"{url}/api/v4/users/login", json=body)
        except httpx.HTTPError as e:
            raise SessionError(f"Could not reach {url}: {type(e).__name__}") from None
    if r.status_code != 200:
        try:
            reason = r.json().get("message", "")
        except ValueError:
            reason = ""
        raise SessionError(f"{url} rejected the sign-in ({r.status_code}). {reason}".strip())
    token = r.headers.get("Token", "")
    if not token:
        raise SessionError(f"{url} accepted the sign-in but returned no session token.")
    user = r.json()
    csrf = r.cookies.get("MMCSRF", "")
    session.save(url, token, csrf, user.get("id", ""))
    return user
