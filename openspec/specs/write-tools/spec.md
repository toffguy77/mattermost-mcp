# write-tools Specification

## Purpose
Lets an agent post, reply, send direct messages, edit its own posts and react, but only when the operator explicitly turns write mode on.

## Requirements

### Requirement: Write mode is opt-in
Write mode SHALL be off unless `MATTERMOST_ENABLE_WRITE` is `1`, `true`, `yes` or `on` (case-insensitive). When it is off, the write tools SHALL NOT appear in the tool list. The HTTP layer SHALL also refuse every request that is neither a GET nor one of the read-only POSTs (`/users/ids`, `/users/search`, `/teams/{id}/posts/search`, `/channels/direct`), and SHALL do so before anything is sent.

The one server-side effect allowed in read-only mode SHALL be the one that existed before: `get_direct_messages` may create the DM channel with the target user via `/channels/direct` if it does not exist yet. No posts, edits or reactions SHALL ever be created. The README safety section SHALL state this exception.

#### Scenario: Default tool list
- **WHEN** the server starts without `MATTERMOST_ENABLE_WRITE`
- **THEN** `tools/list` contains no `create_post`, `send_direct_message`, `update_post`, `add_reaction` or `remove_reaction`

#### Scenario: Enabled tool list
- **WHEN** the server starts with `MATTERMOST_ENABLE_WRITE=1`
- **THEN** `tools/list` contains all five write tools in addition to the read tools

#### Scenario: Guard blocks mutation when off
- **WHEN** write mode is off and any code path tries a PUT, DELETE or non-allowlisted POST
- **THEN** an error is raised and no HTTP request reaches Mattermost

### Requirement: Cookie writes need CSRF
In cookie mode with write mode on, a write tool SHALL fail with an error saying `MATTERMOST_CSRF` is required if no CSRF value is configured, and SHALL send nothing.

#### Scenario: Missing CSRF
- **WHEN** cookie mode, write mode on, no CSRF value, and `create_post` is called
- **THEN** the call fails, the error mentions `MATTERMOST_CSRF`, and no request is sent

### Requirement: Create post
`create_post(channel_id, message, root_id=None)` SHALL create a post in the channel. When `root_id` is given, the post SHALL be a reply in that thread. It SHALL return the created post in the same shape as read tools return posts.

#### Scenario: Reply in thread
- **WHEN** `create_post` is called with a `root_id`
- **THEN** the created post's `root_id` equals that value and it is returned

#### Scenario: Empty message
- **WHEN** `message` is empty or whitespace
- **THEN** the call fails without sending a request

### Requirement: Send direct message
`send_direct_message(username, message)` SHALL resolve the user, open (or reuse) the direct channel, post the message there and return the created post.

#### Scenario: DM by username
- **WHEN** `send_direct_message("alice", "hi")` is called
- **THEN** the message is posted in the DM channel between the current user and alice

#### Scenario: Unknown user
- **WHEN** the username does not exist
- **THEN** the call fails with "User not found: @<username>" and nothing is posted

### Requirement: Edit only own posts
`update_post(post_id, message)` SHALL change the message of a post only if its author is the current user, and SHALL return the updated post. For anyone else's post it SHALL refuse without sending a mutating request, even if the user has permission to edit others' posts.

#### Scenario: Own post
- **WHEN** the current user wrote the post
- **THEN** its message is replaced and the updated post is returned

#### Scenario: Someone else's post
- **WHEN** the post was written by another user
- **THEN** the call fails with an error saying only the user's own posts can be edited, and no PUT is sent

### Requirement: Reactions
`add_reaction(post_id, emoji)` and `remove_reaction(post_id, emoji)` SHALL add or remove the current user's reaction. The emoji name SHALL be accepted with or without surrounding colons. Both tools SHALL be idempotent from the caller's view: adding an existing reaction or removing a missing one SHALL NOT fail.

#### Scenario: Colons stripped
- **WHEN** `add_reaction(post_id, ":thumbsup:")` is called
- **THEN** the reaction `thumbsup` is added by the current user

### Requirement: Write tool annotations
Write tools SHALL carry `readOnlyHint=false` and `destructiveHint=false`. `update_post`, `add_reaction` and `remove_reaction` SHALL carry `idempotentHint=true`. `create_post` and `send_direct_message` SHALL carry `idempotentHint=false`.

#### Scenario: Annotations exposed
- **WHEN** a client lists tools with write mode on
- **THEN** each write tool exposes the annotations above
