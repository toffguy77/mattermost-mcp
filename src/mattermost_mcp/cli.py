"""Command line: `serve` (the default) plus `login`, `status` and `logout`.

Only `serve` speaks MCP on stdio; the other subcommands are for people and
print to stdout.
"""

from __future__ import annotations

import argparse
import getpass
import os
import shutil
import sys
from pathlib import Path

from . import __version__, browser_login, firefox, password_login, session
from .session import SessionError

_input = input
_getpass = getpass.getpass


def _serve() -> None:
    from .server import serve

    serve()


def _default_url() -> str:
    return os.environ.get("MATTERMOST_URL", "").strip() or session.load().get("MATTERMOST_URL", "")


def _fail(message: str) -> None:
    print(f"mattermost-mcp-server: {message}", file=sys.stderr)
    raise SystemExit(1)


def _login(args) -> None:
    url = (args.url or _default_url()).rstrip("/")
    if not url:
        _fail("which server? Pass --url https://mattermost.example.com (or set MATTERMOST_URL).")
    try:
        if args.password:
            login_id = args.login_id or _input("Username or email: ")
            user = password_login.login(
                url, login_id=login_id, password=_getpass("Password: "),
                prompt_mfa=lambda: _input("MFA code: "),
            )
        elif args.from_firefox:
            user = firefox.import_session(url, profile=args.profile)
        else:
            print(f"Opening a browser at {url}/login — sign in there; this window closes by itself.")
            user = browser_login.login(url, timeout=args.timeout)
    except SessionError as e:
        _fail(str(e))
    except (OSError, RuntimeError) as e:
        _fail(f"sign-in failed: {e}")
    print(f"Signed in as @{user.get('username', '?')} on {url}. Session saved to {session.session_path()}.")


def _status(args) -> None:
    from .auth import get_auth

    try:
        auth = get_auth()
    except RuntimeError as e:
        _fail(f"not signed in.\n{e}\nRun `mattermost-mcp-server login` to sign in with your browser.")
    print(f"Server:  {auth.url}")
    print(f"Auth:    {auth.mode} (from {auth.source or 'unknown'})")
    try:
        if auth.mode == "token":
            from .client import MattermostClient

            me = MattermostClient(write_enabled=False).get_me()
        else:
            me = session.verify(auth.url, auth.token, auth.csrf, auth.user_id)
    except (RuntimeError, SessionError) as e:
        _fail(f"the credential does not work: {str(e).splitlines()[0]}")
    print(f"User:    @{me.get('username')} ({me.get('id')})")


def _logout(args) -> None:
    saved = session.load()
    if saved:
        url = saved.get("MATTERMOST_URL", "")
        headers = session.cookie_headers(
            saved.get("MATTERMOST_TOKEN", ""),
            saved.get("MATTERMOST_CSRF", ""),
            saved.get("MATTERMOST_USER_ID", ""),
        )
        try:
            with session.http_client() as http:
                http.post(f"{url}/api/v4/users/logout", headers=headers)
        except Exception:
            pass  # revoking is best effort; the local copy goes regardless
        session.delete()
        print(f"Signed out of {url} and deleted {session.session_path()}.")
    else:
        print("No saved session.")
    if args.forget_browser:
        profile = session.profile_dir()
        shutil.rmtree(profile, ignore_errors=True)
        print(f"Deleted the sign-in browser profile {profile}.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="mattermost-mcp-server",
        description="MCP server for Mattermost. Without a subcommand it serves MCP on stdio.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="{serve,login,status,logout}")

    sub.add_parser("serve", help="run the MCP server on stdio (the default)")

    p = sub.add_parser("login", help="sign in and save the session cookies for the server")
    p.add_argument("--url", help="Mattermost URL (default: MATTERMOST_URL or the saved session)")
    how = p.add_mutually_exclusive_group()
    how.add_argument("--browser", action="store_true", help="sign in through a browser window (default)")
    how.add_argument("--password", action="store_true", help="sign in with username and password (+MFA)")
    how.add_argument("--from-firefox", action="store_true", help="import the session from Firefox")
    p.add_argument("--timeout", type=int, default=300, help="seconds to wait for browser sign-in (300)")
    p.add_argument("--login-id", help="username or email for --password")
    p.add_argument("--profile", type=Path, help="Firefox profile directory for --from-firefox")

    sub.add_parser("status", help="show which server and user the credentials resolve to")

    p = sub.add_parser("logout", help="revoke and delete the saved session")
    p.add_argument("--forget-browser", action="store_true", help="also delete the sign-in browser profile")

    args = parser.parse_args(argv)
    if args.command in (None, "serve"):
        _serve()
    elif args.command == "login":
        _login(args)
    elif args.command == "status":
        _status(args)
    elif args.command == "logout":
        _logout(args)
