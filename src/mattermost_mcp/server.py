"""FastMCP server exposing read-only Mattermost tools.

Auth is cookie-based (MMAUTHTOKEN / MMCSRF / MMUSERID from a browser session);
see auth.py for where credentials are read from.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from fastmcp import FastMCP

from .client import MattermostClient

mcp = FastMCP("mattermost")

_client: MattermostClient | None = None


def _get_client() -> MattermostClient:
    global _client
    if _client is None:
        _client = MattermostClient()
    return _client


def _as_dict(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, list):
        return [_as_dict(i) for i in obj]
    return obj


# ------------------------------------------------------------------
# Tools
# ------------------------------------------------------------------


@mcp.tool()
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
    return _as_dict(_get_client().list_channels(
        team_id=team_id,
        include_dm=include_dm,
        include_muted=include_muted,
        category=category,
    ))


@mcp.tool()
def get_channel_posts(
    channel_id: str,
    since: str | None = None,
    limit: int = 30,
) -> list[dict]:
    """Get recent posts from a Mattermost channel.

    Args:
        channel_id: The channel ID (use list_channels to find it).
        since: ISO 8601 datetime — only return posts created after this timestamp.
        limit: Maximum number of posts to return. Default: 30.

    Returns list of {id, channel_id, user_id, username, create_at, message, reactions, file_ids, root_id}.
    """
    return _as_dict(_get_client().get_channel_posts(channel_id=channel_id, since=since, limit=limit))


@mcp.tool()
def get_thread(post_id: str) -> dict:
    """Get a post and all its replies.

    Args:
        post_id: The root post ID.

    Returns {root: Post, replies: list[Post]}.
    """
    return _as_dict(_get_client().get_thread(post_id=post_id))


@mcp.tool()
def search_posts(
    query: str,
    channel_id: str | None = None,
    category: str | None = None,
    include_muted: bool = False,
    limit: int = 20,
) -> list[dict]:
    """Full-text search across Mattermost posts.

    By default skips channels the user has muted in the sidebar — pass
    include_muted=True to widen the search.

    Args:
        query: Search terms.
        channel_id: Optional channel ID to scope the search to a single channel.
        category: Sidebar category display name to restrict results
            (case-insensitive), e.g. "Favorites".
        include_muted: If True, also search muted channels. Default: False.
        limit: Maximum number of results. Default: 20.

    Returns list of Post dicts with matching messages.
    """
    return _as_dict(_get_client().search_posts(
        query=query,
        channel_id=channel_id,
        category=category,
        include_muted=include_muted,
        limit=limit,
    ))


@mcp.tool()
def get_direct_messages(
    username: str,
    limit: int = 30,
    since: str | None = None,
) -> list[dict]:
    """Get direct message history with a specific user.

    Args:
        username: The Mattermost username (without @).
        limit: Maximum number of messages to return. Default: 30.
        since: ISO 8601 datetime — only return messages after this timestamp.

    Returns list of Post dicts from the DM channel.
    """
    return _as_dict(_get_client().get_direct_messages(username=username, limit=limit, since=since))


@mcp.tool()
def get_mentions(
    since: str | None = None,
    limit: int = 20,
    include_muted: bool = True,
) -> list[dict]:
    """Get posts that mention the authenticated user.

    Mentions in muted channels are included by default — mute hides unread
    badges, not @-mentions. Pass include_muted=False to exclude them.

    Args:
        since: ISO 8601 datetime — only return mentions after this timestamp.
        limit: Maximum number of mentions to return. Default: 20.
        include_muted: If False, drop mentions from muted channels. Default: True.

    Returns list of Post dicts where the current user was mentioned.
    """
    return _as_dict(_get_client().get_mentions(
        since=since,
        limit=limit,
        include_muted=include_muted,
    ))


@mcp.tool()
def get_unread(
    include_muted: bool = False,
    category: str | None = None,
) -> list[dict]:
    """Get unread message counts and mention badges per channel.

    By default skips channels muted in the sidebar (same behavior as the
    client unread badge). Pass include_muted=True to see every unread.

    Args:
        include_muted: If True, include muted channels in the result. Default: False.
        category: Filter by sidebar category (case-insensitive), e.g. "Favorites".

    Returns list of {channel_id, channel_name, msg_count, mention_count, muted, category}.
    Only channels with unread messages are included.
    """
    return _get_client().get_unread(include_muted=include_muted, category=category)


@mcp.tool()
def get_user(username: str) -> dict:
    """Get a Mattermost user's profile by username.

    Args:
        username: The Mattermost username (without @).

    Returns {id, username, first_name, last_name, email, status}.
    """
    return _as_dict(_get_client().get_user(username=username))


def main() -> None:
    mcp.run()
