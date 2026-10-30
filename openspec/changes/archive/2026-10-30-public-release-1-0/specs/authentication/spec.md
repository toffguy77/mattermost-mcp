# Spec Delta

## Purpose

Defines how the server finds Mattermost credentials, picks between access-token and browser-cookie authentication, and reports authentication failures without leaking secrets.

## ADDED Requirements

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
