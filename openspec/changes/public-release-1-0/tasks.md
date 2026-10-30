# Tasks

Every behaviour task is red → green → refactor: first write the failing test and watch it fail, then write the minimal code that makes it pass. Run `uv run pytest` before ticking the box.

## 1. Tooling

- [x] 1.1 Add ruff to the dev group and `[tool.ruff]` in `pyproject.toml`, fix the existing lint findings, and add a `ruff check` step to `.github/workflows/test.yml`. Verify: `uv run ruff check` is clean and `uv run pytest` is green.

## 2. Authentication (spec: authentication)

- [x] 2.1 `tests/test_auth_modes.py`: env `MATTERMOST_ACCESS_TOKEN` → `get_auth().mode == "token"` with the token set. Then implement the access-token field and the mode in `auth.py`. Verify: the new test passes and `tests/test_auth_remote.py` is unchanged and green.
- [x] 2.2 `tests/test_auth_modes.py`: the mode-selection matrix. Cases: env cookie beats keychain token (the keychain is never called), both in env → token, explicit `cookie`, explicit `token`, invalid mode → error lists both values, cookie host supplies the access token, keychain `access_token` with explicit token mode. Implement the resolution order from design D4. Verify: the matrix passes.
- [x] 2.3 `tests/test_auth_modes.py`: the cookie host ignores `MATTERMOST_AUTH_MODE` / `MATTERMOST_ENABLE_WRITE` lines. Verify the test passes.
- [x] 2.4 `tests/test_client_auth_headers.py`:
  - token mode sends Bearer, with no Cookie or CSRF;
  - cookie mode headers are identical to before;
  - a re-pull that switches the mode leaves no stale headers.

  Implement D5 in `client.py`. Verify: the tests pass, and so do the existing `test_client_reauth.py` tests.
- [x] 2.5 `tests/test_client_auth_headers.py`:
  - a 401 in token mode → the message mentions "access token" and "Personal Access Tokens" and does not contain the token;
  - a 401 in cookie mode → the old text plus `MATTERMOST_AUTH_HELP`;
  - nothing configured → the error names `MATTERMOST_URL` and `MATTERMOST_ACCESS_TOKEN`.

  Verify the tests pass.
- [x] 2.6 Update the `auth.py` module docstring for both modes. Verify: it reads correctly and `ruff` is clean.

## 3. Write guard (spec: write-tools, "Write mode is opt-in")

- [x] 3.1 `tests/test_write_guard.py`: with writes disabled, PUT, DELETE and `POST /posts` raise before any HTTP call (assert respx saw no call). The allowlisted POSTs (`/users/ids`, `/users/search`, `/teams/x/posts/search`, `/channels/direct`) still go through. Implement the `write_enabled` flag and the D6 guard. Verify the tests pass.
- [x] 3.2 `tests/test_write_guard.py`: in cookie mode with writes enabled and no CSRF, a write raises an error mentioning `MATTERMOST_CSRF` and nothing is sent. Verify the test passes.

## 4. Metadata snapshot, unread fix, performance (spec: read-tools)

- [ ] 4.1 `tests/test_channel_index.py`: the snapshot builds from mocked teams, channels, members and categories. A second call within the TTL issues no HTTP requests. `MATTERMOST_CACHE_TTL=0` refetches. Implement D2, including the lock and the thread-pool fan-out. Verify the tests pass.
- [ ] 4.2 `tests/test_client.py`: add channel totals to the `get_unread` fixtures and add new tests for "all viewed → absent" and "42 total / 40 viewed → msg_count 2". `get_unread` makes no `/channels/{id}` requests (assert the route was not called). The old `get_unread` count semantics are a bug per design D3: fixtures get `total_msg_count_root` added, and any assertion that encoded the old (viewed-as-unread) count is updated to the true unread count. Implement D3 on top of the snapshot. Verify: the new and updated tests pass.
- [ ] 4.3 `tests/test_client.py`: `list_channels` returns `unread_count` from the snapshot, and the existing `list_channels` tests stay green. Implement it and verify.
- [ ] 4.4 Note the unread fix in `CHANGELOG.md` under Fixed. Verify the entry exists.

## 5. Read-tool fixes (spec: read-tools)

- [ ] 5.1 `tests/test_client.py`: channel-scoped search returns only that channel's posts, for both an `O` channel (one team searched with `in:<name>`) and a `D` channel. Implement D8 and verify.
- [ ] 5.2 `tests/test_client.py`: a DM post returned by two teams appears once, and results are sorted newest first. Implement and verify.
- [ ] 5.3 `tests/test_client.py`: `get_mentions(since, limit)` with 30 results, 5 of them after `since`, and `limit=3` → 3 recent posts. Implement filter-then-limit and verify.
- [ ] 5.4 `tests/test_client.py`: a 401 during username enrichment propagates, and other errors still degrade quietly. Implement and verify.

## 6. New read tools (spec: read-tools)

- [ ] 6.1 `tests/test_client.py` and `tests/test_server.py`: `get_me` (profile + `auth_mode` + `write_enabled`) and `list_teams`. Implement the client methods and tools with read annotations. Verify the tests pass.
- [ ] 6.2 `get_post` and `get_channel` (by ID; by team ID + name; by team name + name; error when the arguments are missing), with tests in `tests/test_client.py`. Implement and verify.
- [ ] 6.3 `search_users`, `get_pinned_posts` and `get_file_info`, with tests in `tests/test_client.py`. Implement and verify.
- [ ] 6.4 Add the `before` parameter to `get_channel_posts` and `get_direct_messages`, with tests in `tests/test_client.py` that assert the `before` query param is sent. Implement and verify.
- [ ] 6.5 `tests/test_server.py`:
  - relax the exact-set test to "superset of the original 8, plus the new read tools";
  - keep `test_no_write_tools` as is;
  - add a test that every read tool has `readOnlyHint=true` and that the original tools' parameter names and defaults are unchanged (snapshot of the input schemas).

  Add the annotations to the existing tools. Verify the tests pass.

## 7. Write tools (spec: write-tools)

- [ ] 7.1 `tests/test_server.py`: `create_server(enable_write=False)` has no write tools; `create_server(enable_write=True)` has all five, with the specified annotations. Implement `create_server`, `register_write_tools` and the env switch in `main()`. Verify the tests pass.
- [ ] 7.2 `tests/test_write_tools.py`: `create_post` (in a channel, as a reply, empty message rejected) returns the post shape. Implement and verify.
- [ ] 7.3 `tests/test_write_tools.py`: `send_direct_message` (opens the DM and posts; unknown user → "User not found", nothing posted). Implement and verify.
- [ ] 7.4 `tests/test_write_tools.py`: `update_post` on an own post → PATCH sent and the post returned; on another user's post → refused and no PUT made (respx asserts that). Implement D9 and verify.
- [ ] 7.5 `tests/test_write_tools.py`: `add_reaction` strips colons; `remove_reaction` treats a 404 as success. Successful writes clear the snapshot cache. Implement and verify.

## 8. Distribution and docs (spec: distribution)

- [ ] 8.1 `pyproject.toml`: name `mattermost-mcp-server`, version `1.0.0`, both scripts, an updated description and classifiers. Run `uv lock`. `tests/test_packaging.py` checks the scripts and the version. Verify: `uv build` succeeds, and `uvx --from dist/*.whl mattermost-mcp-server` answers an MCP `initialize` (a manual check, recorded in the PR).
- [ ] 8.2 Add `server.json` (registry schema, PyPI package, stdio, env vars). `tests/test_packaging.py` checks that its name and version match pyproject and that every env var it lists appears in the README. Verify the tests pass.
- [ ] 8.3 Rewrite the README to cover:
  - pitch;
  - quick start with a PAT and `uvx`;
  - configs for Claude Code, Claude Desktop, Cursor and VS Code;
  - the tool table with a read/write column;
  - write mode and its safety model;
  - the cookie alternative (env, cookie host, keychain);
  - the full env var table;
  - troubleshooting;
  - the `mcp-name:` marker.

  `tests/test_packaging.py` checks that every tool registered with writes enabled appears in the README table. Verify the test passes.
- [ ] 8.4 Add `CHANGELOG.md` (1.0.0: Added / Fixed / Changed), `CONTRIBUTING.md` (uv, TDD, ruff, OpenSpec) and `SECURITY.md`. Verify: the files exist and are linked from the README.
- [ ] 8.5 Add `.github/workflows/publish.yml` (tag `v*` → `uv build` → trusted publishing). Verify: `actionlint`, if available, or a YAML parse passes. Do not tag or publish; that is the owner's action.

## 9. Integration check

- [ ] 9.1 Run the full suite and ruff clean. Smoke the built wheel over stdio: `tools/list` without `MATTERMOST_ENABLE_WRITE` shows no write tools, and with it shows all of them. Run `openspec validate public-release-1-0 --strict`. Verify: everything is green.
