# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed

- `get_unread` reported the number of messages the user had already *viewed*
  (`ChannelMember.msg_count`) as the unread count, so nearly every channel was
  listed. Unread is now `channel.total_msg_count − member.msg_count` (root
  counts when available, matching the client with collapsed threads). The
  response shape is unchanged.
- `list_channels` now fills `unread_count` (it was always 0).
- Direct and group messages no longer appear once per team in `get_unread`
  and `list_channels`.

### Changed

- Channel metadata (teams, channels, membership, sidebar categories) is
  fetched once, concurrently across teams, and cached for 60 seconds
  (`MATTERMOST_CACHE_TTL`). `get_unread` no longer makes one request per
  channel.
