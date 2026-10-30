# Proposal

## Why

Cookie auth is the fallback for servers where personal access tokens are disabled, which is common on SSO-only deployments. Today it means copying `MMAUTHTOKEN`/`MMCSRF` out of DevTools and doing it again every time the session expires. Users should be able to sign in once, the way they normally do (password, SSO, MFA), and have the server pick up the session cookies itself, and pick them up again when they expire.

## What Changes

- **`mattermost-mcp-server login`**: opens a Chromium-family browser that is already installed on the machine (Chrome, Chromium, Edge or Brave), with a dedicated profile, at the server's login page.
  - It waits until you have signed in, reads `MMAUTHTOKEN`, `MMCSRF` and `MMUSERID` over the Chrome DevTools Protocol, and checks them against `/users/me`.
  - It saves the session to a 0600 file and closes the browser.
  - No Playwright, no browser download.
- **Other ways to get a session:**
  - `login --password`: username or email, password and an optional MFA code, sent to `/users/login`. The password is never stored.
  - `login --from-firefox`: imports the session cookies from a Firefox profile that is already signed in.
- **`status` and `logout` commands.**
  - `status` shows who you are signed in as and which credential source is used, without printing any secret.
  - `logout` revokes the saved session on the server and deletes the local session file. It can also wipe the browser profile.
- **Saved session as a credential source.** It sits between the cookie host and the keychain, and is only used for the server it was saved for. After `login`, the server starts with no environment variables at all.
- **Automatic re-login (opt-in, `MATTERMOST_AUTO_LOGIN=1`).**
  - When the session expires (a 401), the server re-reads the session file in case another process signed in again.
  - If that does not help, it opens the login browser and waits for you.
  - The browser profile keeps the IdP session, so an SSO sign-in often completes without any input.
  - Concurrent server processes share one login window.
- The plain command still starts the MCP server, so existing configurations do not change.

## Capabilities

### New Capabilities

- `session-login`: how a browser session is obtained (browser, password, Firefox import), how it is stored, and the `login` / `status` / `logout` commands.

### Modified Capabilities

- `authentication`: the saved session joins the credential sources, and an opt-in automatic re-login is added on 401.
- `distribution`: the console command gains subcommands; running it with no arguments still serves MCP over stdio.

## Impact

- New modules:
  - `session.py`: the session file, the lock and verification;
  - `browser_login.py`: browser discovery, a minimal CDP client and the login loop;
  - `firefox.py`: the cookie import;
  - `cli.py`: the subcommands.
- Changed modules: `auth.py` (the new source), `client.py` (the 401 path).
- `websockets` becomes an explicit dependency. It is already installed through FastMCP.
- Docs: a README section, CHANGELOG, SECURITY (the profile directory is as sensitive as the cookie). The version becomes 1.1.0.
