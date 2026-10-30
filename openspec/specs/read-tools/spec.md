# read-tools Specification

## Purpose
Read-only MCP tools that let an agent see what the authenticated user sees in Mattermost: channels, posts, threads, unreads, mentions, users and files. Their results match the official client's view, including mute state and sidebar categories.

## Requirements

### Requirement: Stable contract of the original tools
The tools `list_channels`, `get_channel_posts`, `get_thread`, `search_posts`, `get_direct_messages`, `get_mentions`, `get_unread` and `get_user` SHALL keep their names, parameter names, parameter defaults and response keys. New parameters SHALL be optional, and new response keys SHALL only be added, never renamed or removed.

#### Scenario: Original tool signatures
- **WHEN** a client lists tools
- **THEN** each original tool accepts at least its original parameters with the original defaults

#### Scenario: Original post shape
- **WHEN** any tool returns a post
- **THEN** it contains at least `id, channel_id, user_id, username, create_at, message, reactions, file_ids, root_id`

### Requirement: Read tools are annotated read-only
Every read tool SHALL carry `readOnlyHint=true` and `idempotentHint=true`.

#### Scenario: Annotation present
- **WHEN** a client lists tools
- **THEN** every read tool reports `readOnlyHint=true`

### Requirement: Real unread counts
`get_unread` and `list_channels` SHALL compute unread messages as the channel's total message count minus the member's viewed count. They SHALL use root-post counts when the server provides them, matching the client with collapsed threads. `get_unread` SHALL list only channels that have unread messages or mentions. `list_channels` SHALL fill `unread_count`. Muted channels SHALL be skipped by `get_unread` by default, as now.

#### Scenario: Viewed all messages
- **WHEN** a channel has `total_msg_count_root=40` and the member has `msg_count_root=40, mention_count_root=0`
- **THEN** the channel is not in `get_unread`, and its `unread_count` in `list_channels` is 0

#### Scenario: Some unread
- **WHEN** a channel has `total_msg_count_root=42` and the member has `msg_count_root=40`
- **THEN** `get_unread` reports `msg_count=2` for it, along with its display name

### Requirement: Channel-scoped search filters by channel
`search_posts(query, channel_id=X)` SHALL return only posts from channel X.

#### Scenario: Scoped search
- **WHEN** search is scoped to a channel and the server-side search also matches posts in other channels
- **THEN** only posts whose `channel_id` is X are returned

### Requirement: Search results are unique and newest first
`search_posts` and `get_mentions` SHALL return each post at most once, even when it is found through several teams. Results SHALL be ordered by `create_at`, newest first, before `limit` is applied.

#### Scenario: DM found via two teams
- **WHEN** the same DM post appears in the search results of two teams
- **THEN** it appears once in the output

### Requirement: Mentions respect since before limit
`get_mentions(since=T, limit=N)` SHALL return up to N mentions created at or after T. It SHALL NOT return fewer when older mentions exist beyond the limit.

#### Scenario: Old mentions do not crowd out new ones
- **WHEN** there are 30 mentions, 5 of them after T, and `limit=3`
- **THEN** 3 mentions after T are returned

### Requirement: History paging
`get_channel_posts` and `get_direct_messages` SHALL accept an optional `before` post ID. When it is given, they SHALL return posts older than that post, newest first.

#### Scenario: Page back
- **WHEN** `get_channel_posts(channel_id, before=P)` is called
- **THEN** only posts created before post P are returned

### Requirement: Identity and teams
`get_me` SHALL return the current user's profile, the active auth mode (`token` or `cookie`) and whether write mode is enabled. `list_teams` SHALL return the user's teams with `id, name, display_name`.

#### Scenario: Agent checks capabilities
- **WHEN** `get_me` is called with write mode off
- **THEN** the result includes `write_enabled: false`

### Requirement: Single post and channel lookup
`get_post(post_id)` SHALL return one post. `get_channel` SHALL accept either `channel_id`, or `team_id` (or a team name) together with a channel `name`, and SHALL return the channel's `id, name, display_name, type, team_id, header, purpose`.

#### Scenario: Channel by name
- **WHEN** `get_channel(team_id=T, name="town-square")` is called
- **THEN** the town-square channel of team T is returned

#### Scenario: Missing arguments
- **WHEN** neither `channel_id` nor `name` is given
- **THEN** the call fails with an error explaining the accepted argument combinations

### Requirement: Users, pins and files
`search_users(term, limit=20)` SHALL return matching users in the `get_user` shape. `get_pinned_posts(channel_id)` SHALL return the channel's pinned posts. `get_file_info(file_id)` SHALL return the file's `id, name, extension, size, mime_type, post_id, channel_id` without downloading its content.

#### Scenario: User search
- **WHEN** `search_users("ali")` is called
- **THEN** users whose username or name matches are returned, at most `limit` of them

### Requirement: Safe path arguments
Every ID, name or username taken from tool arguments SHALL be encoded as a single URL path segment. `""`, `.` and `..` SHALL be rejected.

#### Scenario: Traversal attempt
- **WHEN** a tool receives `post_id="../users/me"`
- **THEN** the request targets a single encoded segment, or is rejected, and never reaches another endpoint
