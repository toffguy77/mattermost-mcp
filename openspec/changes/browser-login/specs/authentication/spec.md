# Spec Delta

## ADDED Requirements

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
