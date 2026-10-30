# mattermost-mcp

A read-only [Model Context Protocol](https://modelcontextprotocol.io) server for
Mattermost. It lets an LLM agent read channels, threads, DMs, mentions and
unread counts, and search posts. It cannot post, react or mark anything as read.

It authenticates with **browser session cookies** (`MMAUTHTOKEN`, `MMCSRF`) rather
than a personal access token. That way it works on servers where PATs are
disabled, or where a reverse proxy strips the `Authorization` header.

## Tools

| Tool | What it returns |
|---|---|
| `list_channels` | Channels you are a member of, with unread count, mute state and sidebar category |
| `get_channel_posts` | Recent posts in a channel, optionally `since` an ISO 8601 timestamp |
| `get_thread` | A root post and all its replies |
| `search_posts` | Full-text search, optionally scoped to a channel or sidebar category; skips muted channels by default |
| `get_direct_messages` | DM history with a user |
| `get_mentions` | Posts that mention you |
| `get_unread` | Per-channel unread and mention counts (muted channels skipped by default, like the client badge) |
| `get_user` | A user's profile by username |

## Install

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```sh
git clone https://github.com/toffguy77/mattermost-mcp.git
cd mattermost-mcp
uv sync --frozen
```

## Credentials

Log in to Mattermost in a browser and open DevTools → Application → Cookies.
Copy `MMAUTHTOKEN`, `MMCSRF` and (optionally) `MMUSERID`.

The server resolves each field separately. The first source that has a value wins:

1. **Environment variables**

   ```sh
   MATTERMOST_URL=https://mattermost.example.com
   MATTERMOST_TOKEN=<MMAUTHTOKEN>
   MATTERMOST_CSRF=<MMCSRF>
   MATTERMOST_USER_ID=<MMUSERID>   # optional
   ```

2. **Cookie host** (off by default): a plain `KEY=VALUE` file with the same
   variable names, kept on another machine and read over ssh. Use this when
   one machine rotates the cookie and others just consume it. The result is
   cached locally. On a 401 the client pulls the file again and retries once.

   | Variable | Default | Meaning |
   |---|---|---|
   | `MATTERMOST_COOKIE_HOST` | unset (off) | ssh host alias, or `local` to read the file on this machine |
   | `MATTERMOST_COOKIE_PATH` | `.config/mattermost-mcp/cookie.env` | path relative to `$HOME` on the host |
   | `MATTERMOST_COOKIE_CACHE` | `~/.cache/mattermost-mcp/cookie.cache` | local cache file (mode 0600) |
   | `MATTERMOST_COOKIE_TTL` | `900` | cache lifetime, seconds |
   | `MATTERMOST_COOKIE_SSH_TIMEOUT` | `10` | ssh connect timeout, seconds |

   ssh runs with `BatchMode=yes`, so a locked key fails fast instead of
   hanging the MCP handshake. If ssh fails, the reason goes to stderr.

3. **OS keychain**: accounts `url`, `token`, `csrf` and `user_id` under the
   service `MATTERMOST_KEYCHAIN_SERVICE` (default `mattermost-mcp`).

   ```sh
   # macOS
   security add-generic-password -s mattermost-mcp -a url   -w https://mattermost.example.com
   security add-generic-password -s mattermost-mcp -a token -w <MMAUTHTOKEN>
   security add-generic-password -s mattermost-mcp -a csrf  -w <MMCSRF>
   # Linux (pass)
   pass insert mattermost-mcp/url
   pass insert mattermost-mcp/token
   pass insert mattermost-mcp/csrf
   ```

### Other settings

| Variable | Default | Meaning |
|---|---|---|
| `MATTERMOST_TRUST_ENV` | `1` | set `0` to ignore `HTTP(S)_PROXY`/`ALL_PROXY` and connect to Mattermost directly |
| `MATTERMOST_AUTH_HELP` | unset | extra text added to the 401 error, e.g. how cookies are rotated in your setup |

Session cookies expire. When they do, every tool call fails with a 401 error.
Put fresh cookies wherever the server reads them from, then restart it: env is
read only once, at startup. If an agent rotates cookies through its own
pipeline, tell it how in `MATTERMOST_AUTH_HELP`. The base error text
deliberately says nothing about where to write cookies.

## Client configuration

Claude Code / Claude Desktop (`mcpServers`):

```json
{
  "mcpServers": {
    "mattermost": {
      "command": "uv",
      "args": ["run", "--project", "/path/to/mattermost-mcp", "mattermost-mcp"],
      "env": {
        "MATTERMOST_URL": "https://mattermost.example.com",
        "MATTERMOST_TOKEN": "…",
        "MATTERMOST_CSRF": "…"
      }
    }
  }
}
```

`python -m mattermost_mcp` works as the entry point too.

## Development

```sh
uv sync
uv run pytest
```

The tests never touch the network or ssh. HTTP is mocked with `respx`, and the
cookie host is switched off unless a test turns it on explicitly.

## License

MIT
