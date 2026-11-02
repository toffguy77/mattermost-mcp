"""FastMCP server exposing Mattermost tools.

Read tools are always registered. Write tools (post, DM, edit own post,
reactions) are registered only when MATTERMOST_ENABLE_WRITE is on; see
client.py for the HTTP-level guard that backs this up.

Auth is a personal access token or browser session cookies; see auth.py.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import __version__
from .client import MattermostClient, write_enabled_from_env

_READ = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True)
_WRITE = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True
)
_WRITE_IDEMPOTENT = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=True
)

_INSTRUCTIONS = """\
Mattermost tools for the authenticated user. IDs (channel, post, user, team,
file) are 26-character strings; find them with list_channels, get_channel,
search_posts or get_user. Timestamps in results are Unix milliseconds; `since`
arguments take ISO 8601. Call get_me to see whether write tools are enabled.
"""


def _as_dict(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, list):
        return [_as_dict(i) for i in obj]
    return obj


def create_server(enable_write: bool = False) -> FastMCP:
    """Build a server; write tools are added only when enable_write is True."""
    server = FastMCP("mattermost", version=__version__, instructions=_INSTRUCTIONS)
    client: MattermostClient | None = None

    def get_client() -> MattermostClient:
        # Created on first use: a missing credential must surface as a tool
        # error the agent can read, not as a crash during the MCP handshake.
        nonlocal client
        if client is None:
            client = MattermostClient(write_enabled=enable_write)
        return client

    _register_read_tools(server, get_client)
    if enable_write:
        register_write_tools(server, get_client)
    return server


# ------------------------------------------------------------------
# Read tools
# ------------------------------------------------------------------


def _register_read_tools(mcp: FastMCP, get_client) -> None:
    @mcp.tool(annotations=_READ)
    def list_channels(
        team_id: str | None = None,
        include_dm: bool = True,
        include_muted: bool = True,
        category: str | None = None,
    ) -> list[dict]:
        """List all Mattermost channels the authenticated user is a member of.

        Args:
            team_id: Optional team ID to filter channels. If omitted, returns channels from all teams.
            include_dm: Whether to include direct message channels. Default: True.
            include_muted: If False, drop channels muted in the sidebar. Default: True.
            category: Filter by sidebar category display name (case-insensitive), e.g. "Favorites".

        Returns list of {id, name, display_name, type, last_post_at, unread_count, muted, category}.
        type: "O" = public, "P" = private, "D" = DM, "G" = group DM.
        """
        return _as_dict(get_client().list_channels(
            team_id=team_id,
            include_dm=include_dm,
            include_muted=include_muted,
            category=category,
        ))

    @mcp.tool(annotations=_READ)
    def get_channel_posts(
        channel_id: str,
        since: str | None = None,
        limit: int = 30,
        before: str | None = None,
    ) -> list[dict]:
        """Get recent posts from a Mattermost channel, newest first.

        Args:
            channel_id: The channel ID (use list_channels or get_channel to find it).
            since: ISO 8601 datetime — only return posts created after this timestamp.
            limit: Maximum number of posts to return. Default: 30.
            before: A post ID — return posts older than it, to page back through history.

        Returns list of {id, channel_id, user_id, username, create_at, message, reactions, file_ids, root_id}.
        """
        return _as_dict(get_client().get_channel_posts(
            channel_id=channel_id, since=since, limit=limit, before=before,
        ))

    @mcp.tool(annotations=_READ)
    def get_thread(post_id: str) -> dict:
        """Get a post and all its replies.

        Args:
            post_id: The root post ID.

        Returns {root: Post, replies: list[Post]}.
        """
        return _as_dict(get_client().get_thread(post_id=post_id))

    @mcp.tool(annotations=_READ)
    def search_posts(
        query: str,
        channel_id: str | None = None,
        category: str | None = None,
        include_muted: bool = False,
        limit: int = 20,
    ) -> list[dict]:
        """Full-text search across Mattermost posts, newest first.

        Supports Mattermost search syntax (from:username, in:channel-name,
        before:/after:/on:YYYY-MM-DD, "exact phrase", -excluded). By default skips
        channels the user has muted in the sidebar — pass include_muted=True to
        widen the search.

        Args:
            query: Search terms.
            channel_id: Optional channel ID to scope the search to a single channel.
            category: Sidebar category display name to restrict results
                (case-insensitive), e.g. "Favorites".
            include_muted: If True, also search muted channels. Default: False.
            limit: Maximum number of results. Default: 20.

        Returns list of Post dicts with matching messages.
        """
        return _as_dict(get_client().search_posts(
            query=query,
            channel_id=channel_id,
            category=category,
            include_muted=include_muted,
            limit=limit,
        ))

    @mcp.tool(annotations=_READ)
    def get_direct_messages(
        username: str,
        limit: int = 30,
        since: str | None = None,
        before: str | None = None,
    ) -> list[dict]:
        """Get direct message history with a specific user, newest first.

        Args:
            username: The Mattermost username (without @).
            limit: Maximum number of messages to return. Default: 30.
            since: ISO 8601 datetime — only return messages after this timestamp.
            before: A post ID — return messages older than it, to page back through history.

        Returns list of Post dicts from the DM channel.
        """
        return _as_dict(get_client().get_direct_messages(
            username=username, limit=limit, since=since, before=before,
        ))

    @mcp.tool(annotations=_READ)
    def get_mentions(
        since: str | None = None,
        limit: int = 20,
        include_muted: bool = True,
    ) -> list[dict]:
        """Get posts that mention the authenticated user, newest first.

        Mentions in muted channels are included by default — mute hides unread
        badges, not @-mentions. Pass include_muted=False to exclude them.

        Args:
            since: ISO 8601 datetime — only return mentions after this timestamp.
            limit: Maximum number of mentions to return. Default: 20.
            include_muted: If False, drop mentions from muted channels. Default: True.

        Returns list of Post dicts where the current user was mentioned.
        """
        return _as_dict(get_client().get_mentions(
            since=since,
            limit=limit,
            include_muted=include_muted,
        ))

    @mcp.tool(annotations=_READ)
    def get_unread(
        include_muted: bool = False,
        category: str | None = None,
    ) -> list[dict]:
        """Get unread counts and mention badges per channel.

        By default skips channels muted in the sidebar (same behavior as the
        client unread badge). Pass include_muted=True to see every unread.

        Args:
            include_muted: If True, include muted channels in the result. Default: False.
            category: Filter by sidebar category (case-insensitive), e.g. "Favorites".

        Returns list of {channel_id, channel_name, msg_count, mention_count, muted, category}.
        msg_count is the number of unread messages. Only channels with unread
        messages or mentions are included.
        """
        return get_client().get_unread(include_muted=include_muted, category=category)

    @mcp.tool(annotations=_READ)
    def get_user(username: str) -> dict:
        """Get a Mattermost user's profile by username.

        Args:
            username: The Mattermost username (without @).

        Returns {id, username, first_name, last_name, email, status}.
        """
        return _as_dict(get_client().get_user(username=username))

    @mcp.tool(annotations=_READ)
    def get_me() -> dict:
        """Get the authenticated user and what this server is allowed to do.

        Returns {id, username, first_name, last_name, email, status, nickname,
        position, auth_mode, write_enabled}. auth_mode is "token" or "cookie";
        write_enabled tells whether posting/editing tools are available.
        """
        return get_client().get_me()

    @mcp.tool(annotations=_READ)
    def list_teams() -> list[dict]:
        """List the teams the authenticated user belongs to.

        Returns list of {id, name, display_name}.
        """
        return get_client().list_teams()

    @mcp.tool(annotations=_READ)
    def get_post(post_id: str) -> dict:
        """Get a single post by ID.

        Args:
            post_id: The post ID.

        Returns a Post dict. Use get_thread for the whole conversation.
        """
        return _as_dict(get_client().get_post(post_id=post_id))

    @mcp.tool(annotations=_READ)
    def get_channel(
        channel_id: str | None = None,
        name: str | None = None,
        team_id: str | None = None,
        team_name: str | None = None,
    ) -> dict:
        """Look up a channel by ID, or by its name (the URL slug, e.g. "town-square").

        Pass channel_id, or name. With name alone, searches the channels you are
        a member of; add team_id or team_name to look up any channel in a team.

        Returns {id, name, display_name, type, team_id, header, purpose}.
        """
        return get_client().get_channel(
            channel_id=channel_id, team_id=team_id, team_name=team_name, name=name,
        )

    @mcp.tool(annotations=_READ)
    def search_users(term: str, limit: int = 20) -> list[dict]:
        """Find users by username, full name, nickname or email prefix.

        Args:
            term: Text to search for.
            limit: Maximum number of users. Default: 20.

        Returns list of {id, username, first_name, last_name, email, status}.
        """
        return _as_dict(get_client().search_users(term=term, limit=limit))

    @mcp.tool(annotations=_READ)
    def get_pinned_posts(channel_id: str) -> list[dict]:
        """Get the posts pinned in a channel.

        Args:
            channel_id: The channel ID.

        Returns list of Post dicts.
        """
        return _as_dict(get_client().get_pinned_posts(channel_id=channel_id))

    @mcp.tool(annotations=_READ)
    def get_file_info(file_id: str) -> dict:
        """Get metadata of a file attached to a post (see a post's file_ids).

        The file content is not downloaded.

        Args:
            file_id: The file ID.

        Returns {id, name, extension, size, mime_type, post_id, channel_id}.
        """
        return get_client().get_file_info(file_id=file_id)


# ------------------------------------------------------------------
# Write tools
# ------------------------------------------------------------------


def register_write_tools(mcp: FastMCP, get_client) -> None:
    @mcp.tool(annotations=_WRITE)
    def create_post(channel_id: str, message: str, root_id: str | None = None) -> dict:
        """Post a message to a channel, or reply in a thread.

        Args:
            channel_id: The channel ID to post in.
            message: Message text (Markdown supported).
            root_id: Optional root post ID to reply in that thread.

        Returns the created Post dict.
        """
        return _as_dict(get_client().create_post(channel_id=channel_id, message=message, root_id=root_id))

    @mcp.tool(annotations=_WRITE)
    def send_direct_message(username: str, message: str) -> dict:
        """Send a direct message to a user, opening the DM channel if needed.

        Args:
            username: The recipient's username (without @).
            message: Message text (Markdown supported).

        Returns the created Post dict.
        """
        return _as_dict(get_client().send_direct_message(username=username, message=message))

    @mcp.tool(annotations=_WRITE_IDEMPOTENT)
    def update_post(post_id: str, message: str) -> dict:
        """Replace the text of one of your own posts. Other users' posts are refused.

        Args:
            post_id: The post ID.
            message: The new message text.

        Returns the updated Post dict.
        """
        return _as_dict(get_client().update_post(post_id=post_id, message=message))

    @mcp.tool(annotations=_WRITE_IDEMPOTENT)
    def add_reaction(post_id: str, emoji: str) -> dict:
        """Add your emoji reaction to a post.

        Args:
            post_id: The post ID.
            emoji: Emoji name, with or without colons, e.g. "thumbsup" or ":white_check_mark:".

        Returns {post_id, emoji, reacted: true}.
        """
        return get_client().add_reaction(post_id=post_id, emoji=emoji)

    @mcp.tool(annotations=_WRITE_IDEMPOTENT)
    def remove_reaction(post_id: str, emoji: str) -> dict:
        """Remove your emoji reaction from a post. Not an error if it is not there.

        Args:
            post_id: The post ID.
            emoji: Emoji name, with or without colons.

        Returns {post_id, emoji, reacted: false}.
        """
        return get_client().remove_reaction(post_id=post_id, emoji=emoji)


# The importable default: read-only, like every previous release.
mcp = create_server(enable_write=False)


def serve() -> None:
    server = create_server(enable_write=write_enabled_from_env())
    server.run(show_banner=False)


def main() -> None:
    from .cli import main as cli_main

    cli_main()
