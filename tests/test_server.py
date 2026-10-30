"""Smoke tests: verify all 8 tools are registered on the FastMCP server."""

from mattermost_mcp.server import mcp

EXPECTED_TOOLS = {
    "list_channels",
    "get_channel_posts",
    "get_thread",
    "search_posts",
    "get_direct_messages",
    "get_mentions",
    "get_unread",
    "get_user",
}


async def test_all_tools_registered():
    tools = await mcp.list_tools()
    registered = {t.name for t in tools}
    assert EXPECTED_TOOLS == registered, f"Missing tools: {EXPECTED_TOOLS - registered}"


async def test_no_write_tools():
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    write_prefixes = ("post_", "create_", "delete_", "update_", "send_", "react_", "mark_")
    for name in names:
        assert not any(name.lower().startswith(p) for p in write_prefixes), (
            f"Unexpected write tool registered: {name}"
        )
