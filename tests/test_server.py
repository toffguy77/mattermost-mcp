"""Tool registration: the original contract, annotations and write mode."""

import json
from pathlib import Path

from mattermost_mcp.server import create_server, mcp

ORIGINAL_TOOLS = {
    "list_channels",
    "get_channel_posts",
    "get_thread",
    "search_posts",
    "get_direct_messages",
    "get_mentions",
    "get_unread",
    "get_user",
}

NEW_READ_TOOLS = {
    "get_me",
    "list_teams",
    "get_post",
    "get_channel",
    "search_users",
    "get_pinned_posts",
    "get_file_info",
}

WRITE_TOOLS = {
    "create_post",
    "send_direct_message",
    "update_post",
    "add_reaction",
    "remove_reaction",
}

_ORIGINAL_PARAMS = json.loads((Path(__file__).parent / "data" / "original_tool_params.json").read_text())


async def test_all_tools_registered():
    tools = await mcp.list_tools()
    registered = {t.name for t in tools}
    assert ORIGINAL_TOOLS <= registered, f"Missing tools: {ORIGINAL_TOOLS - registered}"
    assert registered == ORIGINAL_TOOLS | NEW_READ_TOOLS


async def test_no_write_tools():
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    write_prefixes = ("post_", "create_", "delete_", "update_", "send_", "react_", "mark_")
    for name in names:
        assert not any(name.lower().startswith(p) for p in write_prefixes), (
            f"Unexpected write tool registered: {name}"
        )


async def test_original_parameters_unchanged():
    tools = {t.name: t for t in await mcp.list_tools()}
    for name, expected in _ORIGINAL_PARAMS.items():
        schema = tools[name].parameters
        assert sorted(schema.get("required", [])) == expected["required"], name
        for param, default in expected["defaults"].items():
            assert param in schema["properties"], f"{name}.{param} removed"
            assert schema["properties"][param].get("default") == default, f"{name}.{param} default changed"


async def test_read_tools_are_annotated_read_only():
    for tool in await mcp.list_tools():
        assert tool.annotations is not None, tool.name
        assert tool.annotations.read_only_hint is True, tool.name
        assert tool.annotations.idempotent_hint is True, tool.name


async def test_create_server_without_write():
    names = {t.name for t in await create_server(enable_write=False).list_tools()}
    assert names == ORIGINAL_TOOLS | NEW_READ_TOOLS


async def test_create_server_with_write():
    tools = {t.name: t for t in await create_server(enable_write=True).list_tools()}
    assert set(tools) == ORIGINAL_TOOLS | NEW_READ_TOOLS | WRITE_TOOLS
    for name in WRITE_TOOLS:
        ann = tools[name].annotations
        assert ann.read_only_hint is False, name
        assert ann.destructive_hint is False, name
    assert tools["create_post"].annotations.idempotent_hint is False
    assert tools["send_direct_message"].annotations.idempotent_hint is False
    for name in ("update_post", "add_reaction", "remove_reaction"):
        assert tools[name].annotations.idempotent_hint is True, name
