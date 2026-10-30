# Tasks

Every behaviour task is red → green → refactor: first write the failing test, then the minimal code. Run `uv run pytest` and `uv run ruff check` before ticking a box.

## 1. Session store

- [ ] 1.1 `tests/test_session.py`: save/load round trip, 0600 file in a 0700 directory, atomic replace, `MATTERMOST_SESSION_FILE` override, delete. Implement `session.py` storage. Verify the tests pass.
- [ ] 1.2 `tests/test_session.py`: `verify(url, cookies)` returns the user on 200 and raises a clear error on 401; it sends `Cookie` and `X-CSRF-Token`. Implement it. Verify the tests pass.

## 2. Credential source (spec: authentication)

- [ ] 2.1 `tests/test_auth_session.py`:
  - zero-config start from the session file;
  - a session for a different `MATTERMOST_URL` is ignored;
  - env token wins;
  - cookie-host values win over the session;
  - the keychain is not consulted when the session supplies the cookie.

  Implement D3 in `auth.py`. Verify: the new tests pass and the existing auth tests are unchanged.

## 3. Browser sign-in (spec: session-login)

- [ ] 3.1 `tests/test_browser_login.py`: browser discovery (`MATTERMOST_BROWSER`, PATH candidates, none found → error text). Implement and verify.
- [ ] 3.2 `tests/test_browser_login.py`: the DevToolsActivePort read waits for the file, and websocket URL discovery uses mocked `/json/version`. Implement and verify.
- [ ] 3.3 `tests/test_browser_login.py`: the login loop with a fake cookie source.
  - Cookies appear after N polls → verified → session saved, browser closed.
  - Cookies for another host are ignored.
  - Timeout → error; browser closed early → error.

  Implement and verify.
- [ ] 3.4 Live check: `tests/live/test_browser_live.py` runs a real headless Chromium against a local HTTP server that sets the cookies. It is skipped without `MATTERMOST_TEST_BROWSER`. Run it once locally with a downloaded Chromium and record the result.

## 4. Password and Firefox (spec: session-login)

- [ ] 4.1 `tests/test_password_login.py`: success (Token header, MMCSRF cookie, user ID saved); MFA retry; wrong password saves nothing; the password never appears in errors. Implement and verify.
- [ ] 4.2 `tests/test_firefox_import.py`: a temp profile with `profiles.ini` and `cookies.sqlite` → cookies for the host imported; another host ignored; no session → error. Implement and verify.

## 5. CLI (spec: distribution, session-login)

- [ ] 5.1 `tests/test_cli.py`:
  - no args → serve;
  - `--help` lists the subcommands;
  - `login` dispatches to browser, password or Firefox;
  - `status` prints user, mode and source without secrets;
  - `logout` revokes, deletes the file, and with `--forget-browser` removes the profile.

  Implement `cli.py`, then wire `server.main` and `__main__` to it. Verify the tests pass.

## 6. Refresh on 401 (spec: authentication)

- [ ] 6.1 `tests/test_client_relogin.py`:
  - 401 plus a newer token in the session file → retried without a browser;
  - 401 plus auto login on → login called once and the request retried;
  - auto login off → error mentions `mattermost-mcp-server login`;
  - the inter-process lock: a second waiter reuses the saved session.

  Implement D6 and verify.

## 7. Docs and release

- [ ] 7.1 README: a "Sign in with your browser" section (`login`, `status`, `logout`, auto login, password, Firefox); add `MATTERMOST_SESSION_FILE`, `MATTERMOST_BROWSER`, `MATTERMOST_BROWSER_PROFILE` and `MATTERMOST_AUTO_LOGIN` to the configuration table; update the 401 troubleshooting. Add notes on the profile and CDP port to SECURITY.md. Add a 1.1.0 entry to CHANGELOG. Bump the version in pyproject and server.json. Verify: `tests/test_packaging.py` passes.
- [ ] 7.2 Integration check: full suite, ruff, `openspec validate browser-login --strict`, and a wheel smoke test (`--help`, and stdio `tools/list` unchanged). Verify that everything is green.
