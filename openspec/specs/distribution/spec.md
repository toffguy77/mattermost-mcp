# distribution Specification

## Purpose
Defines how users install and launch the server and what is published, so the server installs the same way as other community MCP servers.

## Requirements

### Requirement: Installable package and entry points
The project SHALL build a Python package named `mattermost-mcp-server` with version 1.0.0. The package SHALL provide two console commands, `mattermost-mcp-server` and `mattermost-mcp`, both of which start the stdio server. `python -m mattermost_mcp` SHALL keep working.

#### Scenario: uvx launch
- **WHEN** the built wheel is run with `uvx --from <wheel> mattermost-mcp-server`
- **THEN** the MCP stdio server starts and answers `initialize`

#### Scenario: Legacy command
- **WHEN** `mattermost-mcp` is run from the installed package
- **THEN** the same server starts

### Requirement: Registry metadata
The repository SHALL contain a `server.json` that is valid against the official MCP registry schema. It SHALL describe the PyPI package and stdio transport, and SHALL list the environment variables users set. The README SHALL contain the `mcp-name:` ownership marker the registry requires for PyPI packages.

#### Scenario: Metadata consistency
- **WHEN** tests read `server.json` and `pyproject.toml`
- **THEN** the package name and version match, and every env var in `server.json` is documented in the README

### Requirement: Community documentation
The README SHALL include:
- a token-based quick start using `uvx`;
- client configuration for Claude Code, Claude Desktop, Cursor and VS Code;
- a table of every tool marked read or write;
- the write mode and its safety model;
- the cookie alternative (env, cookie host, keychain);
- a reference table of all environment variables;
- troubleshooting for 401, CSRF and proxies.

The repository SHALL include `CHANGELOG.md`, `CONTRIBUTING.md` and `SECURITY.md`.

#### Scenario: Tools documented
- **WHEN** a test compares registered tool names (write mode on) with the README tool table
- **THEN** every registered tool appears in the table

### Requirement: Command-line subcommands
The `mattermost-mcp-server` and `mattermost-mcp` commands SHALL accept the subcommands `serve`, `login`, `status` and `logout`. With no arguments they SHALL start the stdio MCP server exactly as before. `--help` SHALL list the subcommands.

#### Scenario: No arguments
- **WHEN** the command runs without arguments
- **THEN** the stdio MCP server starts

#### Scenario: Help
- **WHEN** `mattermost-mcp-server --help` runs
- **THEN** the output lists `login`, `status`, `logout` and `serve`
