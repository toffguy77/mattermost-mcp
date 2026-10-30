# Design

## Context

See proposal.md. Credentials today are resolved per field in this order: env → cookie host → keychain (`auth.py`). On a 401 the client re-pulls the cookie host once (`MattermostClient._reauth`). There is no browser on CI or on the developer machine, so the browser path has to be testable without one.

## Decisions

### D1. Drive an installed browser over CDP, not Playwright
Run the user's Chromium-family browser with:
- `--user-data-dir=<profile>`;
- `--remote-debugging-port=0`, which picks a free loopback port;
- `--no-first-run --no-default-browser-check --new-window <url>/login`.

Chrome writes the chosen port to `<profile>/DevToolsActivePort`. Read it, take the browser websocket URL from `http://127.0.0.1:<port>/json/version`, and poll `Storage.getCookies` once per second with `websockets.sync.client`.

*Alternatives considered:*
- Playwright: it downloads about 150 MB and adds a heavy dependency.
- Decrypting Chrome's cookie database: the encryption differs per OS and is blocked by app-bound encryption on Windows.

Firefox has no usable CDP, so it gets the import path (D4) instead.

Browser discovery:
1. `MATTERMOST_BROWSER` (a path), then
2. per-OS candidates: `google-chrome`, `google-chrome-stable`, `chromium`, `chromium-browser`, `microsoft-edge`, `brave-browser` on `PATH`, and the standard `.app` / `Program Files` locations.

### D2. One session store, reusing the cookie-env format
`session.py` reads and writes `MATTERMOST_SESSION_FILE` with `parse_cookie_env` and the same 0600/O_EXCL/rename write as the cookie-host cache. The profile lives at `~/.config/mattermost-mcp/browser-profile` (`MATTERMOST_BROWSER_PROFILE`).

`verify(url, cookies)` calls `GET /users/me` with the cookie headers and returns the user. Login and `status` both use it. It honours `MATTERMOST_TRUST_ENV`.

### D3. Source order and URL binding in `auth.get_auth`
The saved session is consulted after the cookie host and before the keychain. It is read lazily and only once per resolution.

Its values are used only if:
- no URL comes from env or the cookie host, or
- that URL equals the session URL (compared with trailing slashes stripped).

It never supplies an access token. Mode detection treats a session `MATTERMOST_TOKEN` like the cookie host does.

### D4. Firefox import
- Find the profile through `profiles.ini`: the install section's `Default=` first, then the profile with `Default=1`. The base directory depends on the OS.
- Copy `cookies.sqlite` (plus `-wal` if present) to a temp directory, then `SELECT name, value, host FROM moz_cookies` for the three names.
- Filter by host match and verify.

### D5. Password login
- `POST /users/login {login_id, password[, token]}`.
- If the server answers 401 with id `mfa.validate_token.authenticate.app_error`, or the message mentions MFA, prompt for the code and retry once.
- The session token comes from the `Token` header, the CSRF value from `Set-Cookie: MMCSRF`, the user ID from the body.
- Prompts use `input` and `getpass`, and are injectable for tests.

### D6. 401 path
`_reauth(secret_used)` keeps its lock and the "already refreshed by another thread" check, then tries in order:
1. a cookie-host re-pull, as today;
2. re-reading the session file;
3. `MATTERMOST_AUTO_LOGIN` → `browser_login.login(url)` under an inter-process lock (`<session file>.lock`, fcntl on POSIX, msvcrt on Windows). After taking the lock, it re-reads the file first: if another process already saved a newer token, it uses that one.

Steps 1–2 are tried once per client. Step 3 is tried once per 401 burst. The existing `_reauth_tried` flag is reset after a successful refresh, so a long-running server can sign in again days later.

### D7. CLI
`cli.py` uses argparse with subparsers. `main()` in `server.py` delegates to it, so both console scripts and `python -m` get the subcommands. No arguments, or `serve`, runs the server.

The CLI prints to stdout. That is fine because those subcommands never run as an MCP stdio server.

### D8. Testability
- The CDP client sits behind a small interface (`get_cookies()`, `close()`). The login loop takes a cookie source and a clock, so the tests drive it with fakes.
- DevToolsActivePort parsing, discovery, Firefox import (a temp sqlite file) and password login (respx) are unit-tested.
- A live test (`tests/live/`, skipped unless `MATTERMOST_TEST_BROWSER` points to a Chromium binary) runs the real CDP path against a local HTTP server that sets the cookies.

## Risks / Trade-offs

- [The CDP port is reachable by local processes while the login window is open] → Loopback only, a random port, and the browser closes right after the sign-in. This is documented in SECURITY.md.
- [The profile directory holds the IdP and Mattermost sessions unencrypted] → It has mode 0700 and is documented; `logout --forget-browser` removes it.
- [Auto login opens a window in the middle of an agent call] → Opt-in, with a bounded timeout, and the tool returns a clear error on timeout.
- [Chrome 136+ refuses remote debugging on the *default* profile] → We always use our own `--user-data-dir`, which is allowed.
