from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Channel:
    id: str
    name: str
    display_name: str
    type: str  # "O" public, "P" private, "D" DM, "G" group DM
    last_post_at: int  # Unix ms
    unread_count: int = 0
    muted: bool = False
    category: str | None = None  # sidebar category display name (per-team)


@dataclass
class Post:
    id: str
    channel_id: str
    user_id: str
    username: str
    create_at: int  # Unix ms
    message: str
    reactions: list[dict] = field(default_factory=list)
    file_ids: list[str] = field(default_factory=list)
    root_id: str = ""  # non-empty if this is a reply


@dataclass
class Thread:
    root: Post
    replies: list[Post] = field(default_factory=list)


@dataclass
class User:
    id: str
    username: str
    first_name: str
    last_name: str
    email: str
    status: str = ""
