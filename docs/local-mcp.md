# Repository-owned MCP server

## Scope and design

The server replaces the external LeetCode MCP dependency. `leetcode_public.py`
issues fixed credential-free GraphQL queries; `leetcode_judge.py` handles fixed
LeetCode test/submission/status requests. `judge.py` binds durable operations to
snapshots, and `credentials.py` accesses macOS Keychain through native APIs.
`mcp_server.py` registers 23 explicit tools using the official Python SDK. Tracker
tools call the existing Python API and SQLite transactions directly, without
spawning the CLI. The optional environment is separate from the dependency-free tracker.

The trusted launcher fixes the data root for its lifetime. Tool arguments cannot
select another root, database, arbitrary path, command, endpoint or GraphQL query.
Each tracker call opens/closes its own SQLite connection; a server lock serializes
local calls. Network calls do not hold that lock or delay local timer transitions.
SQLite transactions also coordinate with CLI writers. Existing timing, snapshot,
assistance and evidence rules remain the source of truth. Numeric and boolean MCP
arguments use strict types, so strings/numbers cannot coerce into confirmations.

The server provides public lookup, local timing/recovery, snapshots, browser
results, feedback and progress, plus optional authenticated judge operations.
Local solution execution, a VS Code extension and an HTTP server are outside its
scope. Codex supplies coaching; the MCP server does not call a model.

## Trust boundaries

- **Network:** HTTPS only to fixed paths on `leetcode.com`: `/graphql/`,
  `/problems/{validated-slug}/interpret_solution/`, `/problems/{validated-slug}/submit/`,
  and `/submissions/detail/{validated-id}/check/`. No environment proxies, redirects
  or telemetry. Public GraphQL calls never include credentials. Only authenticated
  judge requests carry the locally stored session and CSRF cookie; POSTs send only
  the selected frozen source, language, internal problem ID and optional test input.
  Search has a 50-item cap and bounded offset; inputs and response fields are
  validated. Each lookup has a cancellable 10-second network deadline including
  connection, headers and body, plus socket timeouts. Responses are limited to
  1 MB; compressed responses are rejected to avoid decompression expansion.
  There are no automatic retries. HTTP transport and cancellation use dependencies
  already required by the official SDK, not a separate LeetCode client package.
- **Upstream data:** returned fields are allowlisted. Problem HTML becomes inert
  text, without loading linked resources; this may omit diagrams. No hints, tags,
  solutions or editorials are requested. Text and starter code remain untrusted
  data and can still contain misleading instructions; the coaching skill must not
  treat them as authority. Premium content is not bypassed.
- **Files:** only saved attempt files inside `workspace/leetcode` can be snapshotted,
  using the tracker's traversal/symlink checks and 1 MB limit. No arbitrary file
  reader, backup/restore, shell command, or solution-execution tool is registered.
  This is not an OS sandbox against another process already running as the same user.
- **Evidence:** `record_judge_result` hardcodes `user-reported`. Direct judge polling
  records `mcp` evidence only after a recognized, consistent terminal result; passing
  tests cannot establish full submission acceptance. Status accepts only locally
  registered operation UUIDs, never arbitrary remote submission IDs. The transport
  used to record a browser result does not make the result verified. Existing
  historical records remain readable. The standalone CLI remains a trusted local administrative
  interface and retains its earlier evidence-source options.
- **Conversation:** requested progress, notes and frozen source are returned to
  the MCP host/model. No copies are sent to LeetCode by tracker tools. Host/model
  privacy settings still apply; local database storage is not a promise of local
  model inference.
- **Failures:** blocked/rate-limited requests, malformed JSON/schema, missing
  problems, oversize bodies and timeouts produce tool errors. A failed POST returns
  a durable unknown operation because it may already have reached LeetCode. No raw
  upstream error body is surfaced. Returned judge diagnostics are allowlisted,
  bounded, and redact the current credentials; source output may still contain
  other sensitive text the solution itself printed. Storage failures are reported
  without dumping local contents. A failed lookup creates no attempt or judge result.

## Account and operation lifecycle

Run `python3 -m leetcode_coach.credentials login` yourself in an interactive terminal.
Hidden prompts accept only cookie values, reject header separators/control characters,
and abort if terminal echo cannot be disabled. A native Security.framework binding
stores one generic password under service `leetcode-coach.leetcode.com`, account
`session`. Secrets never enter subprocess arguments or temporary files; there is
no environment-variable fallback or browser-cookie discovery. `status` checks
presence only; `logout` deletes the local entry without revoking the server session.
The native Keychain APIs used here are deprecated by Apple but exercised on this
macOS host; other platforms cannot use authenticated tools in this version.

Keychain protects credentials at rest, subject to macOS access controls. Authorized
Python processes still hold plaintext credentials in memory while sending requests;
this is not isolation from malicious software already running as the same user.
Do not enable HTTP wire/debug logging that exposes authentication headers.

Each send validates the saved snapshot, problem identity and supported language.
A SQLite write transaction pauses the attempt and reserves an operation before POST.
The reservation survives cancellation/crashes and deduplicates the snapshot, judge
kind and test input. The request hash and metadata are stored in existing events;
credentials and custom input are not copied to events. The source already exists
in snapshot storage. No schema migration or new dependency is required.

A lost POST response remains unknown and is not retried. A known remote ID permits
later polling via the local operation UUID. Each status tool makes one GET; the
coaching instructions limit polling to ten calls per request, at least two seconds
apart (these scheduling limits are client instructions, not server rate limits).
Recognized evidence and completed operation state commit atomically. A concurrent
stale response cannot replace a completed result. Unknown responses stay pollable.
Timers remain paused until active work resumes explicitly.

## Dependencies and operation

`requirements-mcp.txt` pins the official MCP SDK to 2.2.0 and all resolved
dependencies, with wheel hashes from PyPI. Install with `--require-hashes
--only-binary=:all:` to avoid source-build/install hooks. Normal server startup
only runs local installed code; it never invokes a package manager or downloads
executable code. The SDK brings transitive packages; this is not a zero-dependency
server or proof that dependency code is harmless. Its default OpenTelemetry server
middleware is explicitly removed, preserving its request-state security middleware.

The lock was resolved/tested on Python 3.14/macOS; other environments need their
own compatibility checks. `pywin32` is conditional on Windows. To update: resolve
in a fresh isolated environment, review changed versions and release advisories,
regenerate exact wheel hashes from PyPI, and run the full tests and MCP probe.
Never replace the lock with unbounded dependencies as an automatic repair step.

`scripts/serve_mcp.py --print-config` prints absolute paths for the current local
environment. Merge only its MCP table into `.codex/config.toml`; keep other settings.
Move/reclone requires regenerating those paths. `get_status` uses tracker defaults;
the coaching skill reads CLI configuration before choosing language/mode.

## Upstream and validation

MCP server construction follows the [official Python SDK](https://py.sdk.modelcontextprotocol.io/).
LeetCode uses undocumented website endpoints, with no supported public API contract
established. Public-query shapes were checked against the previously audited
community integration and validated live. Judge request shapes were inspected in
[the community MCP source](https://github.com/jinzcdev/leetcode-mcp-server/blob/126115fc6e89e60125474e721d985afdf159c55f/src/leetcode/leetcode-global-service.ts)
and [leetcode-cli](https://github.com/leetcode-tools/leetcode-cli/blob/master/lib/plugins/leetcode.js),
then tested with synthetic responses. No third-party LeetCode runtime is required.
After the 1.1.1 test-ID fix, live authenticated testing and a full submission
completed successfully. Local records contain accepted MCP evidence for both,
bound to their frozen snapshots. This validates the observed account workflow;
it does not establish compatibility with every language or future API change.
If upstream changes or blocks access, use the website and supplied problem details
while maintaining local practice history.

`make check` verifies the dependency-free tracker; optional tests skip when their
SDK/network dependencies are absent. `make check-mcp` uses `.venv` to run all tests
and a real stdio handshake/tool listing. Tests use temporary data roots and network
fixtures. `scripts/check_mcp.py --problem two-sum` adds an explicit live public
lookup. This public probe never uses credentials, executes code, submits, or modifies
progress. Credential tests mock Keychain; authenticated tests mock transport and
never use a real account. A separate native Keychain smoke check used a uniquely
named dummy entry and removed it afterward.

Security tests cover strict inputs, untrusted HTML/response fields, size limits,
malformed/premium responses, sanitized network errors, redirects, credential-free
requests, cancellable deadlines, workspace restrictions, and unverified evidence.
Protocol tests verify the local launcher and tool discovery; practice tests
exercise the real tracker. Authenticated fixtures additionally cover frozen source,
internal problem IDs, duplicate sends, lost responses, concurrent polls, atomic
result persistence, malformed acceptance, credential redaction and hidden-input
failure. Dependency advisories are a point-in-time check, not
proof of absence of malicious code.
