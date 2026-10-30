# Spec Delta

## ADDED Requirements

### Requirement: Command-line subcommands
The `mattermost-mcp-server` and `mattermost-mcp` commands SHALL accept the subcommands `serve`, `login`, `status` and `logout`. With no arguments they SHALL start the stdio MCP server exactly as before. `--help` SHALL list the subcommands.

#### Scenario: No arguments
- **WHEN** the command runs without arguments
- **THEN** the stdio MCP server starts

#### Scenario: Help
- **WHEN** `mattermost-mcp-server --help` runs
- **THEN** the output lists `login`, `status`, `logout` and `serve`
