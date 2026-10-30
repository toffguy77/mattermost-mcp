"""Mattermost REST API v4 client — synchronous httpx, read-only unless write mode is on."""

from __future__ import annotations

import dataclasses
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from urllib.parse import quote

import httpx

from .auth import get_auth, refresh_remote, remote_enabled
from .models import Channel, Post, Thread, User


def _seg(value: str) -> str:
    """Quote a tool argument as a single URL path segment.

    IDs and usernames come from the model; unquoted, "../" or "?" in them
    would reach other API endpoints with the user's session. "." and ".."
    survive quoting and are still dot-segments, so they are refused outright.
    """
    value = str(value)
    if value in {"", ".", ".."}:
        raise ValueError(f"invalid path argument: {value!r}")
    return quote(value, safe="")


def _iso_to_ms(iso: str) -> int:
    """Convert ISO 8601 string to Unix milliseconds."""
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp() * 1000)


_AUTH_401_HELP = (
    "Mattermost rejected the session cookies (401): they are invalid or "
    "expired and must be refreshed by whoever rotates them for this "
    "deployment. If a cookie host is configured, it was already re-pulled "
    "once and still returned 401."
)

_TOKEN_401_HELP = (
    "Mattermost rejected the access token (401): it is invalid, expired or "
    "revoked. Create a new one under Profile > Security > Personal Access "
    "Tokens (or a bot token under Integrations > Bot Accounts) and update "
    "MATTERMOST_ACCESS_TOKEN."
)


def _auth_401_help(mode: str = "cookie") -> str:
    base = _TOKEN_401_HELP if mode == "token" else _AUTH_401_HELP
    # Deployments wire credential rotation differently; let them say how theirs works.
    extra = os.environ.get("MATTERMOST_AUTH_HELP", "").strip()
    return f"{base}\n{extra}" if extra else base


# POSTs that only read. Everything else that is not a GET mutates and needs
# write mode. Matched against the whole path, so "../" tricks cannot pass.
# /channels/direct creates the DM channel if it does not exist yet; that was
# already the case for get_direct_messages and is the one documented exception.
_READ_POSTS = tuple(
    re.compile(p)
    for p in (
        r"/users/ids",
        r"/users/search",
        r"/teams/[A-Za-z0-9]+/posts/search",
        r"/channels/direct",
    )
)

_TRUTHY = {"1", "true", "yes", "on"}


def write_enabled_from_env() -> bool:
    return os.environ.get("MATTERMOST_ENABLE_WRITE", "").strip().lower() in _TRUTHY


def _is_read_only(method: str, path: str) -> bool:
    if method == "GET":
        return True
    return method == "POST" and any(p.fullmatch(path) for p in _READ_POSTS)


class AuthError(RuntimeError):
    """A 401 that survived the cookie host re-pull. Never swallowed."""


def _cache_ttl() -> float:
    try:
        return float(os.environ.get("MATTERMOST_CACHE_TTL", "").strip() or 60)
    except ValueError:
        return 60.0


# Fan-out across teams. Small: a user is in a handful of teams, and a stdio
# server has a single client.
_MAX_WORKERS = 8


@dataclasses.dataclass
class ChannelIndex:
    """One walk over the user's teams: channels, membership, categories.

    Shared by list_channels, get_unread and the muted/category filters of
    search, so an agent turn that calls several of them pays for one walk.
    """

    teams: list[dict]
    channels: dict[str, dict]  # channel_id -> channel, in team order, deduplicated
    members: dict[str, dict]  # channel_id -> channel member of the current user
    category: dict[str, str]  # channel_id -> sidebar category display name

    def muted(self, cid: str) -> bool:
        notify = (self.members.get(cid) or {}).get("notify_props") or {}
        return notify.get("mark_unread") == "mention"

    def unread(self, cid: str) -> int:
        # ChannelMember.msg_count is how many messages the user has *viewed*;
        # unread is the channel total minus that. Root counts match the
        # client with collapsed threads, so prefer them when both sides have them.
        m = self.members.get(cid)
        c = self.channels.get(cid)
        if not m or not c:
            return 0
        if "msg_count_root" in m and "total_msg_count_root" in c:
            total, viewed = c["total_msg_count_root"], m["msg_count_root"]
        else:
            total, viewed = c.get("total_msg_count", 0), m.get("msg_count", 0)
        return max(0, (total or 0) - (viewed or 0))

    def mentions(self, cid: str) -> int:
        m = self.members.get(cid) or {}
        return m.get("mention_count_root", m.get("mention_count", 0)) or 0


def _trust_env() -> bool:
    # Off when Mattermost must be reached directly while the process env
    # carries a proxy meant for everything else.
    return os.environ.get("MATTERMOST_TRUST_ENV", "1").strip().lower() not in {"0", "false", "no", "off"}


class MattermostClient:
    def __init__(self, write_enabled: bool | None = None) -> None:
        self.write_enabled = write_enabled_from_env() if write_enabled is None else write_enabled
        auth = get_auth()
        self._auth = auth
        self._base = auth.url + "/api/v4"

        self._http = httpx.Client(
            timeout=30.0,
            trust_env=_trust_env(),
        )
        self._apply_auth(auth)
        self._me: dict | None = None
        # One re-auth per client: if a freshly pulled cookie also 401s, the
        # cookie host is stale too and only a human paste fixes it. Retrying
        # further would just add ssh round-trips to every call.
        self._reauth_tried = False
        self._lock = threading.Lock()
        self._index: ChannelIndex | None = None
        self._index_at = 0.0
        self._pool = ThreadPoolExecutor(max_workers=_MAX_WORKERS, thread_name_prefix="mm")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _apply_auth(self, auth) -> None:
        # Clear both modes' headers first: a cookie host re-pull may switch
        # modes, and a request must never carry two identities.
        for h in ("Authorization", "Cookie", "X-CSRF-Token"):
            self._http.headers.pop(h, None)
        if auth.mode == "token":
            self._http.headers["Authorization"] = f"Bearer {auth.access_token}"
            return
        cookie = f"MMAUTHTOKEN={auth.token}"
        if auth.user_id:
            cookie += f"; MMUSERID={auth.user_id}"
        self._http.headers["Cookie"] = cookie
        if auth.csrf:
            self._http.headers["X-CSRF-Token"] = auth.csrf

    def _reauth(self) -> bool:
        """Re-pull cookies from the cookie host after a 401.

        Returns True only when the token actually changed — otherwise the
        caller must surface the 401 instead of replaying the same request.
        """
        if self._reauth_tried or not remote_enabled():
            return False
        self._reauth_tried = True
        if not refresh_remote():
            return False
        auth = get_auth()
        if not auth.secret or auth.secret == self._auth.secret:
            return False
        self._auth = auth
        self._base = auth.url + "/api/v4"
        self._apply_auth(auth)
        self.invalidate_cache()
        return True

    def _check_write(self, method: str, path: str) -> None:
        if _is_read_only(method, path):
            return
        if not self.write_enabled:
            raise RuntimeError(
                f"Refusing {method} {path}: write mode is disabled. "
                "Set MATTERMOST_ENABLE_WRITE=1 to allow posting and editing."
            )
        if self._auth.mode == "cookie" and not self._auth.csrf:
            raise RuntimeError(
                "Write tools in cookie mode need the MMCSRF cookie: set MATTERMOST_CSRF, "
                "or use a personal access token (MATTERMOST_ACCESS_TOKEN)."
            )

    def _request(self, method: str, path: str, *, params=None, json=None, _retry: bool = True):
        self._check_write(method, path)
        url = f"{self._base}{path}"
        try:
            r = self._http.request(method, url, params=params, json=json)
        except httpx.TimeoutException:
            raise RuntimeError(f"Request timed out: {url}") from None
        if r.status_code == 401:
            if _retry and self._reauth():
                return self._request(method, path, params=params, json=json, _retry=False)
            raise AuthError(_auth_401_help(self._auth.mode))
        if r.status_code == 403:
            raise RuntimeError(f"Access denied: {url}")
        if r.status_code == 404:
            raise RuntimeError(f"Not found: {url}")
        r.raise_for_status()
        return r.json()

    def _get(self, path: str, **params) -> dict | list:
        return self._request(
            "GET", path,
            params={k: v for k, v in params.items() if v is not None},
        )

    def _post(self, path: str, body: dict) -> dict | list:
        return self._request("POST", path, json=body)

    def _me_user(self) -> dict:
        if self._me is None:
            self._me = self._get("/users/me")
        return self._me

    def _optional(self, fn, default):
        """Run a best-effort lookup: degrade quietly, except on auth failure."""
        try:
            return fn()
        except AuthError:
            raise
        except Exception:
            return default

    def invalidate_cache(self) -> None:
        with self._lock:
            self._index = None

    def _channel_index(self) -> ChannelIndex:
        with self._lock:
            ttl = _cache_ttl()
            if self._index is not None and ttl > 0 and time.monotonic() - self._index_at < ttl:
                return self._index
        index = self._build_index()
        with self._lock:
            self._index, self._index_at = index, time.monotonic()
        return index

    def _build_index(self) -> ChannelIndex:
        uid = self._me_user()["id"]
        teams = self._get(f"/users/{uid}/teams")

        def per_team(team: dict):
            tid = team["id"]
            channels = self._get(f"/users/{uid}/teams/{tid}/channels")
            members = self._optional(lambda: self._get(f"/users/{uid}/teams/{tid}/channels/members"), [])
            cats = self._optional(lambda: self._get(f"/users/{uid}/teams/{tid}/channels/categories"), {})
            return channels, members, cats

        results = list(self._pool.map(per_team, teams))
        dms = self._optional(lambda: self._get(f"/users/{uid}/channels", team_id="direct"), [])

        channels: dict[str, dict] = {}
        members: dict[str, dict] = {}
        category: dict[str, str] = {}
        for team_channels, team_members, cats in results:
            for c in team_channels:
                channels.setdefault(c["id"], c)
            for m in team_members:
                members.setdefault(m["channel_id"], m)
            for cat in (cats or {}).get("categories", []):
                name = cat.get("display_name") or cat.get("type", "")
                for cid in cat.get("channel_ids", []):
                    category.setdefault(cid, name)
        for c in dms:
            channels.setdefault(c["id"], c)
        return ChannelIndex(teams=teams, channels=channels, members=members, category=category)

    def _parse_post(self, p: dict) -> Post:
        reactions = []
        if p.get("metadata", {}).get("reactions"):
            for r in p["metadata"]["reactions"]:
                reactions.append({"user_id": r.get("user_id", ""), "emoji": r.get("emoji_name", "")})
        return Post(
            id=p["id"],
            channel_id=p.get("channel_id", ""),
            user_id=p.get("user_id", ""),
            username=p.get("metadata", {}).get("sender_name") or p.get("user_id", ""),
            create_at=p.get("create_at", 0),
            message=p.get("message", ""),
            reactions=reactions,
            file_ids=list(p.get("file_ids") or []),
            root_id=p.get("root_id", ""),
        )

    def _enrich_posts_with_usernames(self, posts: list[Post]) -> list[Post]:
        """Batch-fetch usernames for posts that only have user_id."""
        user_ids = {p.user_id for p in posts if p.user_id and not p.username.startswith("@")}
        if not user_ids:
            return posts
        try:
            users_data = self._post("/users/ids", list(user_ids))
            id_to_username = {u["id"]: u["username"] for u in users_data}
            for p in posts:
                if p.user_id in id_to_username and not p.username.startswith("@"):
                    p.username = id_to_username[p.user_id]
        except Exception:
            pass
        return posts

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_channels(
        self,
        team_id: str | None = None,
        include_dm: bool = True,
        include_muted: bool = True,
        category: str | None = None,
    ) -> list[Channel]:
        index = self._channel_index()
        result: list[Channel] = []
        for cid, c in index.channels.items():
            is_dm = c.get("type") in ("D", "G")
            if is_dm and not include_dm:
                continue
            if team_id and not is_dm and c.get("team_id") != team_id:
                continue
            is_muted = index.muted(cid)
            if not include_muted and is_muted:
                continue
            cat = index.category.get(cid)
            if category is not None and (cat or "").lower() != category.lower():
                continue
            result.append(Channel(
                id=cid,
                name=c.get("name", ""),
                display_name=c.get("display_name") or c.get("name", ""),
                type=c.get("type", ""),
                last_post_at=c.get("last_post_at", 0),
                unread_count=index.unread(cid),
                muted=is_muted,
                category=cat,
            ))
        return result

    def get_channel_posts(
        self,
        channel_id: str,
        since: str | None = None,
        limit: int = 30,
    ) -> list[Post]:
        params: dict = {"per_page": limit}
        if since:
            params["since"] = _iso_to_ms(since)
        data = self._get(f"/channels/{_seg(channel_id)}/posts", **params)
        order = data.get("order", [])
        posts_map = data.get("posts", {})
        posts = [self._parse_post(posts_map[pid]) for pid in order if pid in posts_map]
        return self._enrich_posts_with_usernames(posts)

    def get_thread(self, post_id: str) -> Thread:
        data = self._get(f"/posts/{_seg(post_id)}/thread")
        order = data.get("order", [])
        posts_map = data.get("posts", {})
        all_posts = [self._parse_post(posts_map[pid]) for pid in order if pid in posts_map]
        all_posts = self._enrich_posts_with_usernames(all_posts)
        root = next((p for p in all_posts if p.id == post_id), None)
        if root is None and all_posts:
            root = all_posts[0]
        replies = [p for p in all_posts if p.id != (root.id if root else None)]
        return Thread(root=root or all_posts[0], replies=replies)

    def search_posts(
        self,
        query: str,
        channel_id: str | None = None,
        category: str | None = None,
        include_muted: bool = False,
        limit: int = 20,
    ) -> list[Post]:
        search_query = query
        if channel_id:
            search_query = f"in:{channel_id} {query}"

        # Server-side search across all teams the user has access to.
        # Mattermost's `in:` filter can't carry hundreds of channel names,
        # so we filter by category/muted client-side after the fact.
        teams = self._get(f"/users/{self._me_user()['id']}/teams")
        order: list[str] = []
        posts_map: dict = {}
        for team in teams:
            data = self._post(
                f"/teams/{team['id']}/posts/search",
                {"terms": search_query, "is_or_search": False},
            )
            order.extend(data.get("order", []))
            posts_map.update(data.get("posts", {}))

        posts = [self._parse_post(posts_map[pid]) for pid in order if pid in posts_map]

        if channel_id is None and (category is not None or not include_muted):
            channels = self.list_channels(include_muted=True)
            allowed = {
                c.id for c in channels
                if (include_muted or not c.muted)
                and (category is None or (c.category or "").lower() == category.lower())
            }
            posts = [p for p in posts if p.channel_id in allowed]

        posts = posts[:limit]
        return self._enrich_posts_with_usernames(posts)

    def get_user(self, username: str) -> User:
        try:
            u = self._get(f"/users/username/{_seg(username)}")
        except RuntimeError as e:
            if "Not found" in str(e):
                raise RuntimeError(f"User not found: @{username}") from e
            raise
        return User(
            id=u["id"],
            username=u.get("username", ""),
            first_name=u.get("first_name", ""),
            last_name=u.get("last_name", ""),
            email=u.get("email", ""),
            status=u.get("status", ""),
        )

    def get_direct_messages(
        self,
        username: str,
        limit: int = 30,
        since: str | None = None,
    ) -> list[Post]:
        target = self.get_user(username)
        me = self._me_user()
        dm_channel = self._post("/channels/direct", [me["id"], target.id])
        return self.get_channel_posts(dm_channel["id"], since=since, limit=limit)

    def get_mentions(
        self,
        since: str | None = None,
        limit: int = 20,
        include_muted: bool = True,
    ) -> list[Post]:
        # Mentions are intentionally surfaced from muted channels by default —
        # mute hides the unread badge in the client, not @-mentions.
        me = self._me_user()
        query = f"@{me['username']}"
        posts = self.search_posts(query, include_muted=include_muted, limit=limit)
        if since:
            since_ms = _iso_to_ms(since)
            posts = [p for p in posts if p.create_at >= since_ms]
        return posts

    def get_unread(
        self,
        include_muted: bool = False,
        category: str | None = None,
    ) -> list[dict]:
        index = self._channel_index()
        result: list[dict] = []
        for cid, c in index.channels.items():
            msg_count = index.unread(cid)
            mention_count = index.mentions(cid)
            if msg_count == 0 and mention_count == 0:
                continue
            is_muted = index.muted(cid)
            if not include_muted and is_muted:
                continue
            cat = index.category.get(cid)
            if category is not None and (cat or "").lower() != category.lower():
                continue
            result.append({
                "channel_id": cid,
                "channel_name": c.get("display_name") or c.get("name", cid),
                "msg_count": msg_count,
                "mention_count": mention_count,
                "muted": is_muted,
                "category": cat,
            })
        return result
