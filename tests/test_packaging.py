"""Release metadata stays consistent: pyproject, server.json, README."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from mattermost_mcp.server import create_server

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())
SERVER_JSON = json.loads((ROOT / "server.json").read_text())
README = (ROOT / "README.md").read_text()


def test_package_name_and_scripts():
    project = PYPROJECT["project"]
    assert project["name"] == "mattermost-mcp-server"
    assert project["scripts"] == {
        "mattermost-mcp-server": "mattermost_mcp.server:main",
        "mattermost-mcp": "mattermost_mcp.server:main",
    }


def test_server_json_matches_pyproject():
    version = PYPROJECT["project"]["version"]
    assert SERVER_JSON["version"] == version
    (pkg,) = SERVER_JSON["packages"]
    assert pkg["registryType"] == "pypi"
    assert pkg["identifier"] == PYPROJECT["project"]["name"]
    assert pkg["version"] == version
    assert pkg["transport"] == {"type": "stdio"}


def test_readme_has_registry_marker():
    assert f"mcp-name: {SERVER_JSON['name']}" in README


def test_server_json_env_vars_are_documented():
    (pkg,) = SERVER_JSON["packages"]
    for var in pkg["environmentVariables"]:
        assert f"`{var['name']}`" in README, var["name"]


def test_changelog_has_release_entry():
    version = PYPROJECT["project"]["version"]
    assert re.search(rf"^## \[{re.escape(version)}\]", (ROOT / "CHANGELOG.md").read_text(), re.M)


async def test_every_tool_is_in_the_readme_table():
    tools = await create_server(enable_write=True).list_tools()
    for tool in tools:
        assert re.search(rf"^\| `{tool.name}` \|", README, re.M), tool.name


def test_server_json_description_fits_registry_limit():
    assert 0 < len(SERVER_JSON["description"]) <= 100
