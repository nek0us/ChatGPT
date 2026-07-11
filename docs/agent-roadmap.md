# ChatGPTWeb Optimization Roadmap

This document tracks the practical path from the current browser-driven ChatGPT wrapper to a cleaner bot and agent backend.

## Current Direction

The main transport should stay browser-resident. Protected ChatGPT requests should be made from the logged-in Playwright page with browser `fetch`, not from Python `httpx`.

Reasons:

- Browser fetch keeps the real browser cookie jar, Cloudflare state, user agent, TLS/browser behavior, local storage, service worker state, and cached frontend modules together.
- Python `httpx` was historically tested and sometimes worked, but it is unreliable because Cloudflare can distinguish it from the real browser environment.
- The old route/goto transport is kept only as a compatibility fallback. It is slower and cannot provide realtime streaming cleanly.
- Frontend JS exports can move. Code should prefer capability detection and multiple provider names over hard-coded single module names.

## Implementation Notes So Far

- Login failures are now classified and permanent failures stop retrying instead of looping forever.
- Send retries are iterative and write structured errors into `MsgData.error_list`.
- `ChatStreamParser` parses ChatGPT SSE/WebSocket patch events into `ChatStreamEvent` objects.
- `ChatStreamDecoder` incrementally decodes raw SSE chunks and feeds `ChatStreamParser`.
- Buffered browser fetch send works through endpoint candidates: `/backend-api/f/conversation`, `/backend-api/conversation`, `/api` variants, and singular conversation paths discovered from browser performance resources.
- Buffered browser fetch now uses `ChatStreamDecoder`/`ChatStreamParser` directly instead of the legacy `recive_handle()` hard parser.
- `continue_chat_stream()` streams events from browser `fetch` by exposing a temporary Playwright binding and pushing `ReadableStream` chunks back to Python.
- Stream event noise is filtered:
  - empty early `final` events are hidden;
  - duplicate final events are hidden;
  - overlapping text chunks are deduplicated by the parser.
- `chat.close()` now cancels keep-alive work and closes browser resources without forcibly stopping the event loop.
- Runtime watchers record unexpected browser/context/page closure and can recreate missing session context/page before keep-alive or send.
- Startup watchdog wraps Playwright start, Firefox launch, and startup context/page creation with timeouts and one browser launch retry.
- `probe_browser_runtime()` inspects bridge capabilities after frontend updates without sending a message.
- `continue_chat()` and `continue_chat_stream()` now share `_prepare_chat_session()` for startup wait, account selection, old conversation routing, parent message restore, runtime recovery, and session reservation.
- Buffered and streaming browser fetch now share `_browser_fetch_bridge_script()` so endpoint discovery and proof/turnstile/arkose provider handling are maintained in one browser-side script.
- `MsgData` and `ChatStreamEvent` reserve `model_requested`, `model_used`, `usage`, and response metadata fields for bot/API/agent callers. Bot adapters can hide them by default; agent/API layers can expose them.
- Runtime probe records model/quota/usage/entitlement/rate-limit related browser resources and storage keys. Optional probe fetch only reads already-observed capability resources.
- Runtime probe has verified `/backend-api/models?iim=false&is_gizmo=false&supports_model_picker_upgrade_presets=true` returns the authenticated model catalog, while localStorage also caches model categories under `.../models`.
- Runtime probe has verified `/backend-api/pageConfigs/billing` returns billing/usage-limit eligibility configuration with authorization, but not necessarily live remaining quota.
- `get_model_catalog()` exposes authenticated remote model catalog, cached browser model categories, and static local aliases in one API for bot/API/agent callers.
- `ChatService` now provides a transport-neutral facade: `send()`, `stream()`, `get_history()`, `get_account_status()`, `get_model_catalog()`, and an explicitly unknown-safe `get_usage_status()`. It converts between caller-owned `ChatRequest`/`ChatResult` objects and legacy `MsgData` internally.
- `ChatService.stream_to_callback()` adapts ordered stream events to synchronous or asynchronous bot callbacks and returns the final `ChatResult` after the stream closes.
- `create_http_app()` is an opt-in aiohttp application factory over `ChatService`. It provides OpenAI-shaped `/v1/chat/completions`, SSE, local health/model/status routes, optional bearer-key protection, and bounded base64 JSON attachments without starting a network listener itself.
- Streaming browser fetches now register a per-request `AbortController`; closing the Python generator or losing an HTTP SSE client aborts the matching page-side fetch and removes the controller entry.
- `McpServiceAdapter` and `create_mcp_server()` provide an optional FastMCP server over `ChatService`, never browser internals. The initial tools are `chat_send`, `chat_stream`, `list_accounts`, `list_models`, and `get_conversation`; both chat tools require explicit `confirm=true`, while output is recursively redacted for credential-shaped keys.
- `chat_stream` forwards each upstream `delta` through MCP progress notifications and returns the final normalized response. If a host delivers tool cancellation to the coroutine, `ChatService.stream_to_callback()` closes the browser-fetch generator and reaches the existing AbortController path; host-specific cancellation signaling still needs a live-client check.
- The MCP test suite now runs a real stdio server subprocess with the official SDK client, verifies initialization/tool discovery, and calls `chat_stream` through the JSON-RPC transport with real progress callbacks, without touching a browser or account.

## Known Traps

- Do not make `httpx` the default path for protected ChatGPT endpoints. It can trigger Cloudflare verification and account risk behavior.
- Do not assume `/backend-api/sentinel/chat-requirements` is the only requirements URL forever. The browser bridge gathers resource entries containing `/backend-api/sentinel/chat-requirements` and also keeps the known path as a candidate.
- Do not assume conversation endpoints stay exactly under `/backend-api`. The bridge keeps known paths, `/api` variants, and resource-discovered singular conversation candidates.
- Do not assume stream `data:` payloads are always one clean dict. Some chunks can contain non-dict payloads or status-only patches.
- Do not emit every parser `final` event directly to bot/agent callers. Some early final-like patches contain only a conversation id and no useful assistant content.
- Do not listen to every new page in a context as if it were the long-lived session page. Upload, login, markdown rendering, and keep-alive temporary pages close normally.
- Do not close browser/context on each bot request. Bot and agent usage need warm sessions for latency and account stability.
- Do not immediately fallback to the legacy route when browser fetch returns `Unusual activity`/403. Treat it as a risk block and cool the session down.
- Do not use rapid-fire live smoke tests as evidence that `old_payload` is broken. A no-delay two-turn test triggered `Unusual activity`; the same prompts passed with a 15 second delay in both buffered and streaming modes.
- The Firefox/Playwright blank startup hang appears to happen around initial browser/context/page startup, not normal per-request page creation. Keep it documented as a runtime/library risk and prefer bounded startup retry over restarting the whole bot process immediately.
- A failed frontend bridge initialization no longer leaves a `Ready` but `login_state=False` session. Startup retries bridge loading once, then records a transient `Update` state with a cooldown instead of advertising an unusable account.
- `token_status()` now includes an `accounts` list with schedulability, conversation count, login failure diagnostics, and runtime closure/recovery timestamps; legacy parallel arrays remain for compatibility.
- After a ChatGPT frontend update, do not assume a full reverse is required. First run the browser runtime probe. If backend endpoints and proof/turnstile/arkose providers are still present, the browser fetch bridge should keep working. If providers disappear or signatures change, then redo frontend capability discovery.
- Keep legacy `recive_handle()` only for the old route/goto fallback until that transport is retired. New browser fetch paths should parse stream text through `ChatStreamDecoder`.
- Do not hard-code dynamic model/quota behavior beyond the local fallback catalog. Prefer browser runtime discovery or authenticated API probes, then merge remote capabilities with local aliases.
- Usage/quota may not be available as a realtime standalone endpoint. It can appear only after certain UI states, model picker interactions, or rate-limit responses, so treat missing quota data as unknown rather than zero.
- For model catalog, prefer authenticated `/backend-api/models?...` when available, then localStorage model cache, then the static local alias catalog.

## Verified Smoke Commands

Buffered send:

```powershell
uv run python example\local_smoke.py
```

Streaming send:

```powershell
$env:CHATGPTWEB_SMOKE_STREAM='true'
uv run python example\local_smoke.py
```

Google-only login diagnosis with optional local screenshots:

```powershell
$env:CHATGPTWEB_SESSION_MODE='google'
$env:CHATGPTWEB_SMOKE_SAVE_SCREEN='true'
$env:CHATGPTWEB_SMOKE_TIMEOUT='180'
uv run python example\local_smoke.py
```

This isolates one login mode without printing session credentials. Screenshots are local diagnostics only and are ignored by Git.

Two-turn buffered send:

```powershell
$env:CHATGPTWEB_SMOKE_PROMPTS='["Say hello in one short sentence.", "Reply with exactly four words."]'
$env:CHATGPTWEB_SMOKE_DELAY='15'
uv run python example\local_smoke.py
```

Two-turn streaming send:

```powershell
$env:CHATGPTWEB_SMOKE_STREAM='true'
$env:CHATGPTWEB_SMOKE_PROMPTS='["Say hello in one short sentence.", "Reply with exactly four words."]'
$env:CHATGPTWEB_SMOKE_DELAY='15'
uv run python example\local_smoke.py
```

Runtime capability probe after frontend updates:

```powershell
$env:CHATGPTWEB_SMOKE_PROBE='true'
uv run python example\local_smoke.py
```

Runtime capability probe with read-only capability fetch:

```powershell
$env:CHATGPTWEB_SMOKE_PROBE='true'
$env:CHATGPTWEB_SMOKE_PROBE_FETCH='true'
uv run python example\local_smoke.py
```

Authenticated model catalog:

```powershell
$env:CHATGPTWEB_SMOKE_MODELS='true'
$env:CHATGPTWEB_SMOKE_PROBE_FETCH='true'
uv run python example\local_smoke.py
```

Expected streaming shape:

```json
[
  {"type": "delta", "text": "..."},
  {"type": "final", "text": "...", "conversation_id": "...", "message_id": "..."}
]
```

## Phase 1: Login Stability

- Add login failure classification for account lock, bad credentials, verification required, risk blocks, rate limits, transient failures, and unknown failures.
- Stop permanent failures instead of retrying forever.
- Add cooldown for temporary failures.
- Expose login diagnostics in `token_status()`.
- Persist enough login failure metadata to understand account health after restart.
- Add targeted screenshots and page text capture for failed login attempts.
- Offline coverage now verifies failure classification, cooldowns, permanent stops, unknown-failure thresholds, and `Auth()` state transitions with a mocked provider.
- Persisted session state now keeps only safety-critical `Stop`/`Update` status; legacy saved failures without a status are restored as `Stop` or `Update` from their failure metadata so locked accounts stay disabled after restart. Ready/login state is re-established by the new browser context.
- Google OAuth diagnosis confirmed the old flow opened a second unrelated `accounts.google.com` page after the OpenAI redirect, then attempted locators on that page while screenshots captured the original page. The flow now stays on the current OAuth redirect page, waits for the Google URL after clicking the provider button, avoids `networkidle` waits and automatic Google-cookie import files, and fails once into the existing risk-block cooldown. A July 2026 Google test reached the normal OpenAI OAuth identifier page but hit the old redirect/locator race before submitting credentials; do not repeat live attempts until this fix has been committed and the account cooldown has elapsed. Direct Google sign-in remains a best-effort compatibility path because Google can block software-controlled browsers; the supported fallback is a manually obtained ChatGPT session token.
- Optional `persist_auth_state` now stores a per-account Playwright storage state under the ignored local data directory after a successful ready state, and restores it before stale session cookies on future context creation. This is the long-lived recovery path for accounts whose ChatGPT session token changes; it is local sensitive state, not an exportable Google-cookie workflow.
- Google failures are classified from explicit page/error evidence rather than the provider name alone: only actual risk-block text gets the long risk cooldown, while locator/navigation timeouts remain transient and require a shorter retry delay. Login diagnostics strip OAuth query parameters before persistence.

## Phase 2: Error And Retry Model

- Replace recursive retry in `send_msg()` with an iterative retry loop.
- Store structured errors as items with `kind`, `message`, `attempt`, `retryable`, and `session_email`.
- Keep `MsgData.error_info` as a compatibility field generated from structured errors.
- Retry only known retryable errors: timeout, websocket disconnect, token expiration, and transient network failures.
- Avoid marking a session Ready after token-expired paths that set it to Update.
- Offline coverage now verifies transient retry, retry exhaustion, and token-expired/Update paths that must stop without being mislabeled as retry exhaustion.

## Phase 3: Streaming Output

- Split the current receive path into parser and transport layers. Done for SSE via `ChatStreamDecoder` and `ChatStreamParser`.
- Convert browser fetch streaming into an async generator that yields `delta`, `final`, `image`, and `error` events. Implemented as `continue_chat_stream()`.
- Keep `continue_chat()` as the existing buffered API.
- Add adapter examples so NoneBot can choose buffered or streaming mode.

## Phase 4: Stable Core Service API

- Introduce a small internal service layer. Initial `ChatService` facade is implemented:
  - `send()`
  - `stream()`
  - file attachments carried by `send()`
  - `get_history()`
  - `get_account_status()`
  - `get_model_catalog()`
  - `get_usage_status()`
- Keep Playwright, websocket, history files, and bot formatting outside this service boundary.
- Treat `MsgData` as a compatibility DTO until a cleaner request/response model replaces it.
- Return structured metadata alongside text so API/agent callers can show requested model, actual upstream model, quota hints, citations, images, and raw unsupported rich UI fragments.

## Phase 5: Bot-Facing Formatting

- `ChatContent` now preserves raw Markdown while exposing plain-text fallback, links, code blocks, citations, image URLs, and opaque `rich_items` as platform-neutral rendering hints. Known upstream aggregate/tool/attachment payloads are retained structurally but core code does not assume a renderer.
- Live web-search SSE verified private `genui`/`url`/`cite` tokens. `ChatContent.markdown` removes them for display while `raw_markdown` and `source_references` retain source labels and opaque source IDs.
- A July 2026 browser-fetch smoke test verified two consecutive `auto`/`gpt-5-5` streaming turns on `/backend-api/f/conversation`, plus a web-search response using the same private `cite`/`url` token shape. A sanitized search fragment is now a content regression test. Upstream did not report usage values in these successful responses, so usage remains honestly empty/unknown.
- Image-generation smoke received a 200 SSE response but no displayable events for 300 seconds. Streams now emit platform-neutral `status` events while no parsed content is available and support an opt-in `stream_idle_timeout_seconds`; timeout aborts local browser fetch consumption but cannot guarantee cancellation of a remote generation already started upstream.
- Runtime probe now records sanitized image/media/task/file/download resource paths and storage keys without issuing speculative requests. Use this trace after a future image test before implementing any task polling endpoint.
- A verified startup probe observed `/backend-api/tasks`; capability fetch may now read that exact observed GET resource, but does not guess task IDs or invoke image/task mutations.
- Rich-media startup resources are timing-dependent: later probe runs observed `/backend-api/files/library` instead of `/backend-api/tasks`. Treat either as a discovery lead only; do not hard-code image polling until a single image task yields a stable resource trace or task payload.
- Keep platform-specific Markdown normalization and message composition in the NoneBot plugin, after it can inspect the active OneBot v11, Satori, or Telegram driver.
- `web_search=True` now reaches both new and existing conversation payloads; live web-search SSE samples remain the preferred source for extending citation/tool-event parsing.
- Move markdown-to-image behind an interface so different renderers can be plugged in.
- Return generated image URLs and downloaded bytes separately.
- Add platform-specific adapters for NoneBot instead of baking display logic into core chat code.

## Phase 6: MCP And Agent Integration

- A minimal optional FastMCP server is implemented as `create_mcp_server(service)`. It uses the official `mcp` Python package only when the factory is called, so base package users do not need the extra dependency.
- Implemented tools:
  - `chat_send` with explicit `confirm=true`
  - `list_accounts` with credential-free diagnostics
  - `list_models` with opt-in remote refresh
  - `get_conversation`
- Deferred tools:
  - `upload_file`, until explicit user approval and file-size/content policy are designed
- Keep tool schemas compact and explicit.
- Never expose raw cookies, access tokens, or account passwords through MCP.
- Add approval-sensitive tools for actions that spend account quota or upload files.
- For Codex/agent usage, prefer streaming events over buffered responses once the client transport can preserve partial progress and cancellation.

## Phase 7: Storage And State

- Replace ad-hoc JSON files with a repository class.
- Keep the first implementation file-backed for easy migration.
- Add file locks or async locks around conversation map writes. Initial implementation uses per-conversation async locks, a map lock, and atomic JSON replacement; it preserves the existing file format.
- Consider SQLite only after the storage interface is stable.

## Phase 8: Test Harness

- Add unit tests for login failure classification. Initial offline coverage is implemented for classification and session state transitions.
- Add parser tests using saved websocket/SSE fixtures. Initial offline coverage added for text, overlapping patches, empty early final events, image patches, model metadata, usage, and citations.
- Add state-machine tests for session transitions.
- Add a fake transport for `send()` and `stream()` so most tests do not need a browser.
- Keep live Playwright tests manual or opt-in because login flows are unstable and account-specific.

## Suggested Commit Order

1. Login state metadata and failure classification.
2. Login retry/cooldown/stop behavior.
3. Structured retry errors for sending messages.
4. Browser fetch transport for conversation send.
5. Graceful shutdown and runtime context/page recovery.
6. Streaming parser and `continue_chat_stream()`.
7. Service API boundary.
8. NoneBot adapter cleanup.
9. MCP server prototype.

## Next Engineering Steps

- Add authenticated runtime probes for account usage/quota. Start by discovering endpoints from browser resources instead of guessing private paths.
- Capture sanitized real SSE samples after future frontend changes and add them as regression fixtures. Current tests intentionally use synthetic, secret-free protocol fixtures.
- Add fixture coverage for unsupported rich UI payloads and tool-result blocks.
- Add platform-specific NoneBot message-edit/send adapters on top of `stream_to_callback()`.
- Add HTTP API fixture coverage for malformed attachment payloads and real client-disconnect cancellation. Do not let HTTP handlers call browser internals directly.
- Add structured account/runtime diagnostics to `token_status()`, including last runtime closure reason.
- Test `chat_stream` with a target client such as Codex and verify its cancellation request reaches the browser AbortController. The base stdio handshake, progress callback, and final tool response are now covered by an offline integration test.
