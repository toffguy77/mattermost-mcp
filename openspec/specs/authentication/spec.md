# authentication Specification

## Purpose
Defines how the server finds Mattermost credentials, picks between access-token and browser-cookie authentication, and reports authentication failures without leaking secrets.

## Requirements

### Requirement: Access token authentication
The server SHALL accept a personal access token or bot token in `MATTERMOST_ACCESS_TOKEN` and, in token mode, SHALL send it on every request as `Authorization: Bearer <token>`. In token mode it SHALL NOT send a `Cookie` or `X-CSRF-Token` header.

#### Scenario: Token from environment
- **WHEN** `MATTERMOST_URL` and `MATTERMOST_ACCESS_TOKEN` are set and no other auth variables are set
- **THEN** each API request carries `Authorization: Bearer <MATTERMOST_ACCESS_TOKEN>` and no `Cookie` header

#### Scenario: Token from keychain
- **WHEN** no env access token is set and the keychain holds account `access_token` under the configured service, with `MATTERMOST_AUTH_MODE=token`
- **THEN** the keychain value is used as the bearer token

#### Scenario: Token from cookie host
- **WHEN** the cookie host export contains `MATTERMOST_ACCESS_TOKEN=<value>` and no env auth variables are set
- **THEN** that value is used as the bearer token

### Requirement: Cookie authentication remains unchanged
The server SHALL keep cookie authentication exactly as before. `MATTERMOST_TOKEN` is the `MMAUTHTOKEN` cookie value, `MATTERMOST_CSRF` goes in `X-CSRF-Token`, and `MATTERMOST_USER_ID` goes in the `MMUSERID` cookie. Each field is resolved env → cookie host → keychain, and the cookie host is re-pulled once on a 401.

#### Scenario: Existing cookie configuration
- **WHEN** only `MATTERMOST_URL`, `MATTERMOST_TOKEN` and `MATTERMOST_CSRF` are set, as in the private deployment
- **THEN** requests carry `Cookie: MMAUTHTOKEN=<token>` and `X-CSRF-Token: <csrf>`, and no `Authorization` header

#### Scenario: Cookie host re-pull on 401
- **WHEN** a cookie-host-backed session gets a 401 and the host now serves a different token
- **THEN** the request is retried once with the new token and succeeds

### Requirement: Auth mode selection
The server SHALL pick the auth mode as follows:
- `MATTERMOST_AUTH_MODE` (`token` or `cookie`, case-insensitive), when set, decides the mode.
- Otherwise, the first source in the order env → cookie host → keychain that holds any auth credential decides it. That source picks token mode if it holds `MATTERMOST_ACCESS_TOKEN` and cookie mode if it holds only `MATTERMOST_TOKEN`.

A lower-priority source SHALL NOT switch the mode away from credentials found in a higher-priority source. An unknown `MATTERMOST_AUTH_MODE` value SHALL fail with an error that names the allowed values.

#### Scenario: Env cookie beats keychain token
- **WHEN** env has `MATTERMOST_TOKEN` and the keychain also has `access_token`, with `MATTERMOST_AUTH_MODE` unset
- **THEN** cookie mode is used with the env cookie, and the keychain is not consulted for an access token

#### Scenario: Both in env without explicit mode
- **WHEN** env has both `MATTERMOST_ACCESS_TOKEN` and `MATTERMOST_TOKEN`, with `MATTERMOST_AUTH_MODE` unset
- **THEN** token mode is used

#### Scenario: Explicit cookie mode
- **WHEN** `MATTERMOST_AUTH_MODE=cookie` and env has both an access token and a cookie
- **THEN** cookie mode is used

#### Scenario: Invalid mode
- **WHEN** `MATTERMOST_AUTH_MODE=oauth`
- **THEN** the first tool call fails with an error listing `token` and `cookie`

### Requirement: Actionable auth errors without secrets
A 401 that survives any retry SHALL produce an error whose text matches the auth mode. In token mode it SHALL say that the token is invalid or revoked and how to create a new one. In cookie mode it SHALL keep the existing cookie text and append `MATTERMOST_AUTH_HELP`. Missing credentials SHALL produce an error that names the variables to set. No error, log line or tool output SHALL contain a token, cookie or CSRF value.

#### Scenario: Revoked token
- **WHEN** token mode is active and Mattermost answers 401
- **THEN** the tool error mentions an invalid or revoked access token and Personal Access Tokens, and does not contain the token value

#### Scenario: Nothing configured
- **WHEN** no URL or credential is available from any source
- **THEN** the error names `MATTERMOST_URL` and `MATTERMOST_ACCESS_TOKEN` (and points to the cookie alternative)

### Requirement: Saved session source
The saved session SHALL be a credential source between the cookie host and the keychain: env → cookie host → saved session → keychain. It SHALL supply cookie-mode credentials. It SHALL be used only when its URL equals `MATTERMOST_URL`, after trailing slashes are normalised, or when no URL is configured anywhere else, so that a session is never sent to a different server.

#### Scenario: Zero-config start after login
- **WHEN** no `MATTERMOST_*` variables are set and a saved session exists
- **THEN** the server authenticates with the saved session's URL and cookies

#### Scenario: Session for another server
- **WHEN** `MATTERMOST_URL` points to server A and the saved session is for server B
- **THEN** the saved session is ignored

#### Scenario: Env credentials win
- **WHEN** env has `MATTERMOST_ACCESS_TOKEN` and a saved session exists
- **THEN** token mode with the env token is used

### Requirement: Session refresh on 401
After a 401 in cookie mode, the server SHALL first try the existing cookie host re-pull. If that does not apply, it SHALL re-read the saved session file and retry once if the file holds a different token. If `MATTERMOST_AUTO_LOGIN` is on, it SHALL then run the browser sign-in, save the new session and retry once. Several server processes SHALL share one sign-in window through a lock file, and a process that waited on the lock SHALL use the session the other one saved.

#### Scenario: Another process signed in again
- **WHEN** a request gets 401 and the session file now holds a newer token
- **THEN** the request is retried with the newer token and no browser opens

#### Scenario: Auto login
- **WHEN** a request gets 401, the file has no newer token, and `MATTERMOST_AUTO_LOGIN=1`
- **THEN** the browser sign-in runs, and the request is retried with the new session

#### Scenario: Auto login off
- **WHEN** the same happens without `MATTERMOST_AUTO_LOGIN`
- **THEN** the 401 error tells the user to run `mattermost-mcp-server login`
