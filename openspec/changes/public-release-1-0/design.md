# Design

## Context

See proposal.md (Why) and `docs/superpowers/specs/2026-10-30-public-release-design.md` for the owner's decisions.

Current state:
- `auth.py` resolves cookie credentials per field: env → cookie host (ssh, cached, re-pulled on 401) → keychain.
- `client.py` is a synchronous `httpx.Client`, created lazily on the first tool call.
- `server.py` registers 8 sync tools at import time on a module-level `FastMCP` instance.
- FastMCP (4.1.x in the lock file) runs sync tools in a worker thread by default (`run_in_thread=True`), so a blocking HTTP call does not block the event loop.
- Hermes launches the server over stdio with cookie env vars and never imports the Python modules.

Existing tests call client methods synchronously and build the client by patching `mattermost_mcp.client.get_auth`. `tests/test_server.py` asserts the exact set of 8 tool names and that no tool has a write-like prefix.

## Goals / Non-Goals

**Goals:**
- Add token auth and write mode, and change existing behaviour only where the specs call it a bug.
- Remove the obvious N+1 and repeated-walk costs.
- Keep every existing test's assertions. The single exception is the exact-set assertion in `test_server.py`, which becomes "superset of the original 8".

**Non-Goals:**
- Any change to the cookie-host protocol or the keychain layout beyond the new `access_token` key.
- An async rewrite (see Decisions).

## Decisions

### D1. Stay synchronous; fan out with a thread pool
FastMCP already runs sync tools in threads, so an async rewrite would buy nothing for a single stdio client. It would also force every existing test to change.

Per-team fan-out (channels, members, categories, search) runs through a small `ThreadPoolExecutor` (max 8 workers) that shares one `httpx.Client`, which is thread-safe.

*Alternative considered:* `httpx.AsyncClient` with async tools. It is more idiomatic, but it means rewriting every test with no user-visible gain.

### D2. One metadata snapshot, cached with a TTL
A `ChannelIndex` snapshot is built per call to answer:
- the user's teams;
- each team's channels, which carry `total_msg_count(_root)`, names, type and `team_id`;
- the member rows, which carry `msg_count(_root)`, `mention_count(_root)` and `notify_props`;
- the sidebar categories.

It is cached in memory for 60 s (`MATTERMOST_CACHE_TTL`, set `0` to disable), behind a lock. `me` is cached for the life of the process. The following tools all read the snapshot:
- `list_channels`: filters, mute state, category and `unread_count`;
- `get_unread`: totals minus viewed, display names from the same snapshot (no per-channel GET);
- `search_posts` and `get_mentions`: mute and category filtering.

A 401 retry or an auth change clears the cache.

*Why a TTL and not "always fresh":* `get_unread` followed by `search_posts` in the same agent turn is the common pattern. A minute-old mute state is harmless, while a fresh walk per tool costs about 3 requests per team.

### D3. Unread = total − viewed (bug fix)
`ChannelMember.msg_count` is the number of messages the user has *viewed*. Unread is `channel.total_msg_count_root − member.msg_count_root`, falling back to the non-root fields when the root ones are absent. `mention_count_root` / `mention_count` stay as they are.

This changes `get_unread`'s numbers but not its shape. The `test_get_unread_*` fixtures get channel totals added. Their asserted outputs stay the same where they were correct.

### D4. Auth mode resolution
`get_auth()` returns `MattermostAuth(url, mode, token, access_token, csrf, user_id)`. `mode` stays a field and becomes meaningful again, with values `token` | `cookie`. The constructor keeps its current positional and keyword order, and new fields have defaults, so `MattermostAuth(url=..., token=..., csrf=..., user_id=...)` in the tests still means cookie mode.

Resolution:
1. An explicit `MATTERMOST_AUTH_MODE` wins. An invalid value raises `RuntimeError`.
2. Otherwise, walk the sources in order: env, then cookie host (only if enabled), then keychain. The first source that holds `MATTERMOST_ACCESS_TOKEN` or `MATTERMOST_TOKEN` decides the mode, with the access token preferred within that source.
3. In token mode only `url` and `access_token` are required. In cookie mode the current per-field resolution runs unchanged.

The keychain is consulted only when env and the cookie host give nothing. That keeps today's cost of zero keychain calls for env-only setups. The cookie-host whitelist adds `MATTERMOST_ACCESS_TOKEN`. `MATTERMOST_AUTH_MODE` and `MATTERMOST_ENABLE_WRITE` are deliberately *not* accepted from the cookie host: they are operator policy, not credentials.

### D5. Headers per mode
- Token mode: `Authorization: Bearer <token>` only.
- Cookie mode: unchanged (`Cookie` and `X-CSRF-Token`).

`_apply_auth` clears the other mode's headers so that a mode switch after a cookie-host re-pull cannot leave both sets on the client.

### D6. Write guard in the HTTP layer
`MattermostClient(write_enabled: bool)` passes every request through one `_request` choke point. With writes disabled it allows:
- `GET`;
- `POST` to the paths in `_READ_POSTS`, which are matched as regexes on the path after `/api/v4`.

Anything else raises `RuntimeError("write mode is disabled …")` before httpx is called. The write tools' own methods also check `write_enabled`, as a second layer.

### D7. Conditional tool registration
`server.py` keeps the module-level `mcp`, with the read tools registered at import time, so `from mattermost_mcp.server import mcp` keeps working. A `register_write_tools(mcp)` function adds the five write tools. `main()` calls it when `MATTERMOST_ENABLE_WRITE` is truthy, and tests call it on a fresh `FastMCP` built by a `create_server(enable_write=...)` factory, so test order cannot leak tools into other tests.

Annotations are passed through `@mcp.tool(annotations=...)`.

### D8. Channel-scoped search
Resolve the channel with `GET /channels/{id}`:
- For `O`/`P` channels, search only its team with `in:<channel.name>`.
- For `D`/`G` channels, search across teams.

In both cases, filter the results to `channel_id == X`, so correctness never depends on how the server parses `in:`. Mute and category filtering are skipped for scoped searches, as now.

### D9. Edit-own-post check
`update_post` first does `GET /posts/{id}`. It compares `user_id` with `me.id` and refuses on a mismatch. Then it sends `PUT /posts/{id}/patch {"message": …}`.

Reactions:
- `add_reaction`: `POST /reactions {user_id, post_id, emoji_name}`.
- `remove_reaction`: `DELETE /users/{me}/posts/{pid}/reactions/{emoji}`, where a 404 is treated as success.

### D10. Packaging
- `pyproject`: `name = "mattermost-mcp-server"`, `version = "1.0.0"`, and both scripts pointing at `mattermost_mcp.server:main`. The wheel still ships the `mattermost_mcp` package.
- `server.json` follows the registry schema version current at implementation time; `$schema` is pinned in the file.
- Publish workflow: on `v*` tags, build with `uv build` and publish with `pypa/gh-action-pypi-publish` (OIDC trusted publishing).
- Ruff is added to the dev group and CI.

## Risks / Trade-offs

- [Unread fix changes numbers Hermes sees] → It is the correct number. Note it in CHANGELOG and tell the owner.
- [Cache shows a stale mute or unread state for up to 60 s] → Short TTL, `MATTERMOST_CACHE_TTL=0` disables it, and the cache is cleared after any write tool.
- [Thread pool plus a shared client under concurrent tool calls] → httpx.Client is thread-safe. The cache and `_me` sit behind a lock.
- [`server.json` schema drifts] → Pin `$schema`. A test checks the name and version against pyproject, not the full registry schema, which would need network access.
- [Trusted publishing needs owner setup on PyPI] → The workflow is inert until the owner configures it. Publishing is the owner's action.

## Migration Plan

Hermes needs no change. After the release, the owner may switch Hermes to `uvx mattermost-mcp-server` or keep `uv run --project`. Rollback means pinning the previous git commit.
