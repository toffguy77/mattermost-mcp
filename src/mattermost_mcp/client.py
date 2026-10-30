"""Mattermost REST API v4 client — read-only, synchronous httpx."""

from __future__ import annotations

import os
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


def _auth_401_help() -> str:
    # Deployments wire cookie rotation differently; let them say how theirs works.
    extra = os.environ.get("MATTERMOST_AUTH_HELP", "").strip()
    return f"{_AUTH_401_HELP}\n{extra}" if extra else _AUTH_401_HELP


def _trust_env() -> bool:
    # Off when Mattermost must be reached directly while the process env
    # carries a proxy meant for everything else.
    return os.environ.get("MATTERMOST_TRUST_ENV", "1").strip().lower() not in {"0", "false", "no", "off"}


class MattermostClient:
    def __init__(self) -> None:
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

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _apply_auth(self, auth) -> None:
        cookie = f"MMAUTHTOKEN={auth.token}"
        if auth.user_id:
            cookie += f"; MMUSERID={auth.user_id}"
        self._http.headers["Cookie"] = cookie
        if auth.csrf:
            self._http.headers["X-CSRF-Token"] = auth.csrf
        else:
            self._http.headers.pop("X-CSRF-Token", None)

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
        if not auth.token or auth.token == self._auth.token:
            return False
        self._auth = auth
        self._base = auth.url + "/api/v4"
        self._apply_auth(auth)
        return True

    def _request(self, method: str, path: str, *, params=None, json=None, _retry: bool = True):
        url = f"{self._base}{path}"
        try:
            r = self._http.request(method, url, params=params, json=json)
        except httpx.TimeoutException:
            raise RuntimeError(f"Request timed out: {url}") from None
        if r.status_code == 401:
            if _retry and self._reauth():
                return self._request(method, path, params=params, json=json, _retry=False)
            raise RuntimeError(_auth_401_help())
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

    def _channel_metadata(self, uid: str) -> tuple[dict[str, bool], dict[str, str]]:
        """Walk all teams once, return (muted_by_channel, category_by_channel)."""
        muted: dict[str, bool] = {}
        category: dict[str, str] = {}
        teams = self._get(f"/users/{uid}/teams")
        for team in teams:
            tid = team["id"]
            try:
                members = self._get(f"/users/{uid}/teams/{tid}/channels/members")
                for m in members:
                    notify = m.get("notify_props") or {}
                    muted[m["channel_id"]] = notify.get("mark_unread") == "mention"
            except Exception:
                pass
            try:
                cats = self._get(f"/users/{uid}/teams/{tid}/channels/categories")
                for cat in cats.get("categories", []):
                    name = cat.get("display_name") or cat.get("type", "")
                    for cid in cat.get("channel_ids", []):
                        category[cid] = name
            except Exception:
                pass
        return muted, category

    def list_channels(
        self,
        team_id: str | None = None,
        include_dm: bool = True,
        include_muted: bool = True,
        category: str | None = None,
    ) -> list[Channel]:
        me = self._me_user()
        uid = me["id"]

        channels: list[dict] = []
        if team_id:
            channels = self._get(f"/users/{uid}/teams/{_seg(team_id)}/channels")
        else:
            teams = self._get(f"/users/{uid}/teams")
            for team in teams:
                team_channels = self._get(f"/users/{uid}/teams/{team['id']}/channels")
                channels.extend(team_channels)

        if include_dm:
            dm_channels = self._get(f"/users/{uid}/channels", team_id="direct")
            channels.extend(dm_channels)

        muted_map, category_map = self._channel_metadata(uid)

        seen: set[str] = set()
        result: list[Channel] = []
        for c in channels:
            cid = c["id"]
            if cid in seen:
                continue
            seen.add(cid)
            if not include_dm and c.get("type") in ("D", "G"):
                continue
            is_muted = muted_map.get(cid, False)
            if not include_muted and is_muted:
                continue
            cat = category_map.get(cid)
            if category is not None and (cat or "").lower() != category.lower():
                continue
            result.append(Channel(
                id=cid,
                name=c.get("name", ""),
                display_name=c.get("display_name") or c.get("name", ""),
                type=c.get("type", ""),
                last_post_at=c.get("last_post_at", 0),
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
        me = self._me_user()
        uid = me["id"]
        teams = self._get(f"/users/{uid}/teams")

        _, category_map = self._channel_metadata(uid)

        result: list[dict] = []
        for team in teams:
            members = self._get(f"/users/{uid}/teams/{team['id']}/channels/members")
            for m in members:
                msg_count = m.get("msg_count_root", m.get("msg_count", 0))
                mention_count = m.get("mention_count_root", m.get("mention_count", 0))
                if msg_count == 0 and mention_count == 0:
                    continue
                notify = m.get("notify_props") or {}
                is_muted = notify.get("mark_unread") == "mention"
                if not include_muted and is_muted:
                    continue
                cat = category_map.get(m["channel_id"])
                if category is not None and (cat or "").lower() != category.lower():
                    continue
                try:
                    ch = self._get(f"/channels/{m['channel_id']}")
                    display = ch.get("display_name") or ch.get("name", m["channel_id"])
                except Exception:
                    display = m["channel_id"]
                result.append({
                    "channel_id": m["channel_id"],
                    "channel_name": display,
                    "msg_count": msg_count,
                    "mention_count": mention_count,
                    "muted": is_muted,
                    "category": cat,
                })
        return result
