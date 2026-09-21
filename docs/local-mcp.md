# Repository-owned MCP server

## Scope and design

The server replaces the external LeetCode MCP dependency with two small adapters:
`leetcode_public.py` issues three fixed public GraphQL queries, and `mcp_server.py`
registers 20 explicit tools using the official Python SDK. Tracker tools call the
existing Python API and SQLite transactions directly, without spawning the CLI.
The optional environment is separate from the dependency-free tracker.

The trusted launcher fixes the data root for its lifetime. Tool arguments cannot
select another root, database, arbitrary path, command, endpoint or GraphQL query.
Each tracker call opens/closes its own SQLite connection; a server lock serializes
local calls. Network calls do not hold that lock or delay local timer transitions.
SQLite transactions also coordinate with CLI writers. Existing timing, snapshot,
assistance and evidence rules remain the source of truth. Numeric and boolean MCP
arguments use strict types, so strings/numbers cannot coerce into confirmations.

The first version provides public lookup, local timing/recovery, snapshots,
user-reported browser results, feedback and progress. Authenticated LeetCode
operations, local solution execution, a VS Code extension and an HTTP server are
outside this version. Codex supplies coaching; the MCP server does not call a model.

## Trust boundaries

- **Network:** HTTPS only to the fixed `https://leetcode.com/graphql/` endpoint.
  No environment proxies, cookies, credential discovery, redirects or telemetry.
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
- **Evidence:** `record_judge_result` hardcodes `user-reported`. The transport used
  to record a browser result does not make the result verified. Existing historical
  records remain readable. The standalone CLI remains a trusted local administrative
  interface and retains its earlier evidence-source options.
- **Conversation:** requested progress, notes and frozen source are returned to
  the MCP host/model. No copies are sent to LeetCode by tracker tools. Host/model
  privacy settings still apply; local database storage is not a promise of local
  model inference.
- **Failures:** blocked/rate-limited requests, malformed JSON/schema, missing
  problems, oversize bodies and timeouts produce tool errors. No raw upstream error
  body is surfaced. Storage failures are reported without dumping local contents.
  A failed lookup never creates a practice attempt or judge result.

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
LeetCode lookup uses undocumented website endpoints, with no supported public API
contract established. Public-query shapes were checked against the previously
audited community integration and validated live; no third-party LeetCode runtime
is required. If upstream changes or blocks access, use the website and supplied
problem details while maintaining local practice history.

`make check` verifies the dependency-free tracker; optional tests skip when their
SDK/network dependencies are absent. `make check-mcp` uses `.venv` to run all tests
and a real stdio handshake/tool listing. Tests use temporary data roots and network
fixtures. `scripts/check_mcp.py --problem two-sum` adds an explicit live public
lookup. Live calls never use credentials, execute code, submit, or modify progress.

Security tests cover strict inputs, untrusted HTML/response fields, size limits,
malformed/premium responses, sanitized network errors, redirects, credential-free
requests, cancellable deadlines, workspace restrictions, and unverified evidence.
Protocol tests verify the local launcher and tool discovery; practice tests
exercise the real tracker. Dependency advisories are a point-in-time check, not
proof of absence of malicious code.
