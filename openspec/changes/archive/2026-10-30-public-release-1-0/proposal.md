# Proposal

## Why

This server was built for one private agent. It is read-only, it accepts only browser session cookies, and you install it from a git clone. We now want to publish it as a complete Mattermost MCP server that anyone can install with a single command, set up with a normal access token, and use to read or (if they opt in) write. It still has to stay a drop-in replacement for the existing private deployment.

Full background and the owner's decisions: `docs/superpowers/specs/2026-10-30-public-release-design.md`.

## What Changes

- **Token auth**: a personal access token or bot token (`MATTERMOST_ACCESS_TOKEN`) is sent as `Authorization: Bearer`. An explicit `MATTERMOST_AUTH_MODE` (`token` | `cookie`) can force the mode. Cookie auth and all its sources (env, cookie host over ssh, keychain) keep working unchanged.
- **Opt-in write mode** (`MATTERMOST_ENABLE_WRITE`, off by default). New tools: `create_post`, `send_direct_message`, `update_post` (own posts only), `add_reaction`, `remove_reaction`. With write mode off, these tools are not registered and the HTTP layer refuses any mutating request.
- **New read tools**: `get_me`, `list_teams`, `get_post`, `get_channel` (by ID or team + name), `search_users`, `get_pinned_posts`, `get_file_info`. A new optional `before` parameter on `get_channel_posts` and `get_direct_messages` lets the agent page backwards.
- **MCP tool annotations** on every tool (`readOnlyHint`, `destructiveHint`, `idempotentHint`).
- **Bug fixes**:
  - `search_posts` scoped to a channel now actually filters by that channel.
  - `get_mentions` applies `since` before `limit`.
  - Search across several teams no longer returns duplicate posts.
  - Search results come back newest first.
  - `get_unread` and `list_channels.unread_count` now report real unread counts, `total_msg_count − msg_count`. Today `get_unread` returns the member's *viewed* count.
  - A 401 during username enrichment is no longer swallowed.
- **Performance**:
  - No per-channel request in `get_unread`.
  - A short in-memory cache for the current user, teams and channel metadata.
  - Requests that fan out across teams run concurrently.
- **Distribution**:
  - The PyPI package is named `mattermost-mcp-server`, version 1.0.0. Both `mattermost-mcp-server` and `mattermost-mcp` are console commands.
  - A `server.json` for the official MCP registry.
  - The README is rewritten for the community. New `CHANGELOG.md`, `CONTRIBUTING.md` and `SECURITY.md`.
  - CI gets ruff and a tag-triggered PyPI publish workflow (trusted publishing).

No **BREAKING** changes. The original eight tools keep their names, parameters and response keys, and every existing environment variable keeps its meaning. The `get_unread` count fix changes the numbers, not the shape: the old numbers were wrong.

## Capabilities

### New Capabilities

- `authentication`: how credentials are resolved, how the auth mode is chosen, which headers are sent, and how auth failures are reported.
- `read-tools`: the read-only MCP tools, both existing and new, with their inputs, outputs and filtering semantics.
- `write-tools`: the opt-in write mode, the mutating tools, and the guarantees that hold when write mode is off.
- `distribution`: how the server is installed and launched, and what is published (package name, entry points, registry metadata).

### Modified Capabilities

(none: the project has no specs yet)

## Impact

- Code: `src/mattermost_mcp/auth.py` (token mode, mode resolution), `client.py` (async, cache, write guard, new endpoints, fixes), `server.py` (new tools, annotations, conditional registration), `models.py` (new fields only).
- Tests: new tests for every behaviour above. Existing tests keep their assertions; calls become `await` where the client turns async.
- Packaging: `pyproject.toml` (name, version, scripts, ruff), new `server.json`, `.github/workflows/`.
- Docs: `README.md`, plus the new `CHANGELOG.md`, `CONTRIBUTING.md` and `SECURITY.md`.
- Hermes (the private deployment) runs the server over stdio with cookie env vars and needs no change. It does not import the Python API.
- Mattermost endpoints used for the first time: `PUT /posts/{id}/patch`, `POST /posts`, `POST /reactions`, `DELETE /users/{uid}/posts/{pid}/reactions/{emoji}`, `GET /channels/{id}/pinned`, `GET /files/{id}/info`, `POST /users/search`, `GET /teams/{tid}/channels/name/{name}`, `GET /posts/{id}`.
