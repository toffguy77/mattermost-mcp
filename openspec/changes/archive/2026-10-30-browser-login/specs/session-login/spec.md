# Spec Delta

## Purpose

Lets a user obtain Mattermost session cookies without DevTools: by signing in through a browser, with a password, or by importing an existing Firefox session. The session is stored safely for the MCP server to use.

## ADDED Requirements

### Requirement: Browser sign-in
`mattermost-mcp-server login` SHALL open an installed Chromium-family browser on `<url>/login`, using a dedicated profile directory and the DevTools protocol on a loopback port. It SHALL wait until the browser holds an `MMAUTHTOKEN` cookie for the server's host that `/api/v4/users/me` accepts. It SHALL then save the URL, `MMAUTHTOKEN`, `MMCSRF` and `MMUSERID` as the saved session, close the browser, and print the signed-in username. It SHALL fail with a clear message after a timeout (default 300 s, `--timeout`), or if the user closes the browser first.

#### Scenario: Successful sign-in
- **WHEN** the user signs in within the timeout
- **THEN** the session file holds the four values and the command prints `Signed in as @<username>`

#### Scenario: Cookies for other hosts are ignored
- **WHEN** the browser also holds an `MMAUTHTOKEN` cookie for a different host
- **THEN** only the cookie whose domain matches the server's host is used

#### Scenario: No browser installed
- **WHEN** no Chromium-family browser is found and `MATTERMOST_BROWSER` is unset
- **THEN** the command fails, says which browsers it looked for, and mentions `MATTERMOST_BROWSER`, `--password` and `--from-firefox`

### Requirement: Password sign-in
`login --password` SHALL prompt for the login ID, the password and, if the server asks for it, an MFA code, without echoing the password. It SHALL exchange them at `/api/v4/users/login` for a session token and CSRF cookie, and save the session. The password SHALL NOT be stored or logged.

#### Scenario: MFA required
- **WHEN** the server answers that an MFA token is required
- **THEN** the user is prompted for the code and the login is retried with it

#### Scenario: Wrong password
- **WHEN** the server rejects the credentials
- **THEN** nothing is saved and the error says the sign-in was rejected

### Requirement: Firefox import
`login --from-firefox` SHALL read the Mattermost session cookies for the server's host from the default Firefox profile, or from `--profile PATH`. It SHALL work while Firefox is running, by reading a copy of the cookie database. It SHALL verify the cookies against `/users/me` before saving them.

#### Scenario: Not signed in in Firefox
- **WHEN** the profile has no `MMAUTHTOKEN` for the host
- **THEN** the command fails saying no session for that host was found in that profile

### Requirement: Saved session storage
The session SHALL be stored in `MATTERMOST_SESSION_FILE` (default `~/.config/mattermost-mcp/session.env`) as `KEY=VALUE` lines. The file SHALL be created with mode 0600 from the first byte, and its directory and the browser profile directory with mode 0700. Writes SHALL be atomic.

#### Scenario: File permissions
- **WHEN** a session is saved
- **THEN** the file mode is 0600 and the file is never readable by others, even briefly

### Requirement: Status and logout
`status` SHALL print the server URL, the auth mode, the credential source, and the signed-in user (or the authentication error). It SHALL NOT print token, cookie or CSRF values. `logout` SHALL best-effort revoke the saved session at `/api/v4/users/logout`, then delete the session file. With `--forget-browser` it SHALL also delete the browser profile.

#### Scenario: Status without secrets
- **WHEN** `status` runs with a saved session
- **THEN** the output contains the username and `cookie`, and no part of the token
