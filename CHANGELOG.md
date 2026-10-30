# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-10-30

First public release.

### Added

- Personal access token / bot token auth (`MATTERMOST_ACCESS_TOKEN`, sent as
  `Authorization: Bearer`). `MATTERMOST_AUTH_MODE=token|cookie` forces a mode.
  Cookie auth and its sources (env, cookie host, keychain) are unchanged.
- Opt-in write mode (`MATTERMOST_ENABLE_WRITE=1`) with `create_post`,
  `send_direct_message`, `update_post` (own posts only), `add_reaction` and
  `remove_reaction`. With write mode off these tools are not registered and
  the HTTP client refuses any mutating request.
- Read tools `get_me`, `list_teams`, `get_post`, `get_channel` (by ID or
  name), `search_users`, `get_pinned_posts`, `get_file_info`.
- `before` parameter on `get_channel_posts` and `get_direct_messages` to page
  back through history.
- MCP tool annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`)
  on every tool, and server instructions for the model.

### Fixed

- `get_unread` reported the number of messages the user had already *viewed*
  (`ChannelMember.msg_count`) as the unread count, so nearly every channel was
  listed. Unread is now `channel.total_msg_count − member.msg_count` (root
  counts when available, matching the client with collapsed threads). The
  response shape is unchanged.
- `list_channels` now fills `unread_count` (it was always 0).
- Direct and group messages no longer appear once per team in `get_unread`
  and `list_channels`.
- `search_posts(channel_id=…)` now really searches that channel: `in:` needs a
  channel name, not an ID.
- Search results are deduplicated across teams and sorted newest first.
- `get_mentions` applies `since` before `limit`, so old mentions no longer
  crowd out recent ones.
- A 401 while resolving usernames is reported instead of silently ignored.

### Changed

- Published on PyPI as `mattermost-mcp-server`; run it with
  `uvx mattermost-mcp-server`. The `mattermost-mcp` command and
  `python -m mattermost_mcp` still work.
- Requires FastMCP 4.1+.
- Channel metadata (teams, channels, membership, sidebar categories) is
  fetched once, concurrently across teams, and cached for 60 seconds
  (`MATTERMOST_CACHE_TTL`). `get_unread` no longer makes one request per
  channel.

## [0.2.0]

Private read-only release with browser-cookie auth.

[1.0.0]: https://github.com/toffguy77/mattermost-mcp/releases/tag/v1.0.0
