# ChatGPTWeb Optimization Roadmap

This document tracks the practical path from the current browser-driven ChatGPT wrapper to a cleaner bot and agent backend.

## Phase 1: Login Stability

- Add login failure classification for account lock, bad credentials, verification required, risk blocks, rate limits, transient failures, and unknown failures.
- Stop permanent failures instead of retrying forever.
- Add cooldown for temporary failures.
- Expose login diagnostics in `token_status()`.
- Persist enough login failure metadata to understand account health after restart.
- Add targeted screenshots and page text capture for failed login attempts.

## Phase 2: Error And Retry Model

- Replace recursive retry in `send_msg()` with an iterative retry loop.
- Store structured errors as items with `kind`, `message`, `attempt`, `retryable`, and `session_email`.
- Keep `MsgData.error_info` as a compatibility field generated from structured errors.
- Retry only known retryable errors: timeout, websocket disconnect, token expiration, and transient network failures.
- Avoid marking a session Ready after token-expired paths that set it to Update.

## Phase 3: Streaming Output

- Split the current receive path into parser and transport layers.
- Convert websocket receive logic into an async generator that yields `delta`, `final`, `image`, and `error` events.
- Keep `continue_chat()` as the existing buffered API.
- Add `stream_chat()` as the new realtime API for bots and agents.
- Add compatibility adapters so NoneBot can choose buffered or streaming mode.

## Phase 4: Stable Core Service API

- Introduce a small internal service layer:
  - `send()`
  - `stream()`
  - `upload_file()`
  - `get_history()`
  - `get_account_status()`
- Keep Playwright, websocket, history files, and bot formatting outside this service boundary.
- Treat `MsgData` as a compatibility DTO until a cleaner request/response model replaces it.

## Phase 5: Bot-Facing Formatting

- Normalize markdown output before sending to chat platforms.
- Preserve links, code blocks, citations, and image placeholders in structured output.
- Move markdown-to-image behind an interface so different renderers can be plugged in.
- Return generated image URLs and downloaded bytes separately.
- Add platform-specific adapters for NoneBot instead of baking display logic into core chat code.

## Phase 6: MCP And Agent Integration

- Expose a minimal MCP server after the service API stabilizes.
- Start with tools:
  - `chat_send`
  - `chat_stream` if the MCP client supports the chosen transport pattern
  - `list_accounts`
  - `get_conversation`
  - `upload_file`
- Keep tool schemas compact and explicit.
- Never expose raw cookies, access tokens, or account passwords through MCP.
- Add approval-sensitive tools for actions that spend account quota or upload files.

## Phase 7: Storage And State

- Replace ad-hoc JSON files with a repository class.
- Keep the first implementation file-backed for easy migration.
- Add file locks or async locks around conversation map writes.
- Consider SQLite only after the storage interface is stable.

## Phase 8: Test Harness

- Add unit tests for login failure classification.
- Add parser tests using saved websocket/SSE fixtures.
- Add state-machine tests for session transitions.
- Add a fake transport for `send()` and `stream()` so most tests do not need a browser.
- Keep live Playwright tests manual or opt-in because login flows are unstable and account-specific.

## Suggested Commit Order

1. Login state metadata and failure classification.
2. Login retry/cooldown/stop behavior.
3. Structured retry errors for sending messages.
4. Streaming parser and `stream_chat()`.
5. Service API boundary.
6. NoneBot adapter cleanup.
7. MCP server prototype.
