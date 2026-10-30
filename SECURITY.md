# Security policy

This server holds credentials that act as your Mattermost account, so
security reports are very welcome.

## Reporting a vulnerability

Please report privately through
[GitHub security advisories](https://github.com/toffguy77/mattermost-mcp/security/advisories/new)
rather than a public issue. You can expect an answer within a week.

## What the server guarantees

- Read-only unless `MATTERMOST_ENABLE_WRITE` is set: write tools are not
  registered and mutating HTTP requests are refused before they are sent.
- `update_post` only edits posts written by the authenticated user.
- Tool arguments are encoded as single URL path segments; `.` and `..` are
  refused.
- Tokens and cookies are never written to logs, errors or tool output. The
  cookie host cache is created with mode 0600.
- The cookie host file can only supply credentials, never settings.
- `login` saves the session to a 0600 file and keeps the sign-in browser
  profile in a 0700 directory. Both are as sensitive as your password for as
  long as the session lives: keep them out of backups and dotfile sync.
  `logout --forget-browser` removes both.
- The sign-in browser is driven over `--remote-debugging-pipe` on macOS and
  Linux, so nothing listens on a port. On Windows it uses a random loopback
  port that exists only while the sign-in window is open.
- Only cookies scoped to the server's own host are taken from the browser,
  all from one cookie jar, and the user ID cookie must match the user the
  server reports, so a sibling site cannot plant a session.
- A saved session is only ever sent to the server it was created for.

Prompt injection is out of scope for the server itself: messages in
Mattermost are untrusted input to your agent. Keep write mode off for
agents that read channels they do not control, or require approval for
write tools in your client.
