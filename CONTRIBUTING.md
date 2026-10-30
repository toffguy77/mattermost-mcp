# Contributing

Thanks for helping! Issues and pull requests are welcome.

## Setup

```sh
uv sync
uv run pytest
uv run ruff check
```

Tests must never touch the network or ssh: mock HTTP with `respx`, and leave
the cookie host off (the shared fixture does this for you).

## How changes are made

- **Test first.** Write a failing test for the behaviour, make it pass with
  the smallest change, then refactor. Every bug fix comes with a test that
  reproduces it.
- **Keep the tool contract.** Existing tool names, parameters, defaults and
  response keys are a public API that agents depend on. Add optional
  parameters and new response keys; do not rename or remove.
  `tests/data/original_tool_params.json` guards the original tools.
- **Read-only stays the default.** Anything that changes server state must
  be a write tool, registered only in write mode, and the HTTP guard in
  `client.py` must keep refusing it otherwise.
- **No secrets in output.** Tokens and cookies must never appear in errors,
  logs or tool results. Diagnostics go to stderr, never stdout (stdout is the
  MCP channel).
- Larger changes are planned with [OpenSpec](https://github.com/Fission-AI/OpenSpec)
  under `openspec/`: a proposal, spec deltas, a design and a task list.

## Releasing

1. Bump `version` in `pyproject.toml` and `server.json` (both places in it)
   and add a `CHANGELOG.md` entry. `tests/test_packaging.py` checks they agree.
2. Tag `vX.Y.Z` and push the tag. The publish workflow builds the package,
   uploads it to PyPI and creates the GitHub release.
