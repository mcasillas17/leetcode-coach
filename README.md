# LeetCode Coach

Practice in VS Code while Codex acts as your interviewer. The coach checks your
reasoning, gives requested hints, reviews correctness and performance, and records
how your attempts change over time.

The tracker runs locally with **Python 3.10+ and no Python dependencies**. It works
without a LeetCode account connection. The optional repository-owned MCP server
provides public problem lookup, tracker tools, and optional authenticated testing and
submission through LeetCode. Solutions never execute on your machine through this server.

## Start coaching

Open this repository as the project in Codex and VS Code. Initialize local storage:

```bash
python3 -m leetcode_coach init
```

Then tell Codex:

> Use leetcode-coach. Start an interview practice session. I will write the code in VS Code.

The repository's `AGENTS.md` points Codex to the coaching skill. A new conversation
opened in this project can discover `.agents/skills/leetcode-coach/SKILL.md`.

Useful things to say during practice:

- “Here is my approach. Ask me about its correctness before I code.”
- “I’m starting implementation.”
- “Give me a small hint.”
- “Pause; I’m taking a break.”
- “Resume. I’m debugging now.”
- “Review my saved code and suggest improvements without editing it.”
- “Submit this solution.”
- “I’m done. Debrief me and show my progress.”

Interview mode gives hints on request. Guided mode is more interactive. In either
mode, code edits and complete solutions require an explicit request. The coach
records assistance, so a helped solve is distinguishable from an independent one.
Independence remains unconfirmed until the debrief establishes original work without
coach or outside solution assistance. Having no logged hints is not sufficient.

## Personal settings

`coach.json` supplies English, `python3`, `interview`, and `leetcode.com` defaults.
Create ignored `coach.local.json` to override only the settings you want:

```json
{
  "language": "typescript",
  "mode": "guided"
}
```

Supported practice languages: Python 3, JavaScript, TypeScript, Java, C++, C, C#,
Go, Rust, Swift, Kotlin, and Ruby. This controls file extensions and recorded
language; it does not install compilers. Public problem lookup returns the starter
signatures supplied by LeetCode. Pass your configured language when starting an
attempt through MCP.

## Connect the local MCP server

The server lives in this repository and uses the official Python MCP SDK. It runs
locally over stdio, with no listening port, telemetry, shell execution, or runtime
package downloads. Optional account credentials are stored in macOS Keychain. The CLI still works without these optional dependencies.

Set up the optional environment from the repository root (tested with Python 3.14
on macOS; the SDK requires Python 3.10+):

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes --only-binary=:all: -r requirements-mcp.txt
.venv/bin/python scripts/serve_mcp.py --print-config
```

Merge the printed `[mcp_servers.leetcode]` table into this project's
`.codex/config.toml`, replacing the old table if it exists. Preserve unrelated
settings. The output contains absolute paths, so the server works regardless of
Codex's working directory. A placeholder template is in `config/leetcode-mcp.toml`.
If you move the repository, regenerate the configuration. Open a new Codex task
in this trusted project or restart the MCP connection to load the new server.

Public lookup and tracking need no credentials. Remove old `LEETCODE_SESSION`, `env_vars`, and `npx`
settings from this server's configuration. The local server ignores LeetCode
credentials even if present in its environment.

Verify the server and optionally make one public network request:

```bash
make check-mcp
.venv/bin/python scripts/check_mcp.py --problem two-sum
```

The first command runs all tests and a real stdio handshake/tool listing without
network access. The second checks live problem lookup, without credentials or
submissions. Public APIs are undocumented and can change or be blocked; failures
are reported as errors, never as empty successful results or judge verdicts.

The server exposes 23 tools:

| Purpose | Tools |
| --- | --- |
| LeetCode judge | `run_code`, `submit_solution`, `get_submission_status` |
| Public lookup | `get_problem`, `search_problems`, `get_daily_challenge` |
| Practice state | `get_status`, `get_attempt`, `start_attempt`, `change_phase`, `pause_attempt`, `resume_attempt`, `finish_attempt` |
| Timing recovery | `recover_attempt`, `correct_timing`, `confirm_timing` |
| Assistance and evidence | `record_hint`, `snapshot_solution`, `get_snapshot`, `record_judge_result` |
| Debrief and progress | `save_feedback`, `get_progress`, `end_session` |

Problem lookup returns plain text, examples and starter signatures, but excludes
hints, tags, editorials and community solutions. Search and the daily tool return
metadata; call `get_problem` for the statement. Premium-only content is not bypassed.
Image-only parts of a statement should be viewed on the linked LeetCode page.

Tracker tools use the same `.coach/progress.sqlite3` as the CLI. `get_snapshot`
returns frozen solution code to the MCP host/model for review. Progress and notes
also enter the conversation when requested; local storage does not imply that
model conversations stay on your machine. Public lookup sends only the requested
slug/search filters to `leetcode.com`, never your solutions or progress.

## Enable LeetCode testing and submission

On macOS, run this yourself in a local interactive terminal from the repository root:

```bash
python3 -m leetcode_coach.credentials login
```

Sign in to `leetcode.com` in your browser. In its developer tools, find the site's
cookies and copy the values of `LEETCODE_SESSION` and `csrftoken` into the two hidden
terminal prompts. Never paste them into chat, source files, config, or commands.
Login stores them in macOS Keychain; it does not verify the session. macOS may ask
you to allow Python to access the Keychain entry. No browser data is read automatically.

```bash
python3 -m leetcode_coach.credentials status
python3 -m leetcode_coach.credentials logout
```

`status` checks only whether credentials are stored. `logout` deletes that local
entry; it does not revoke the browser session on LeetCode. Public tools continue to
work without credentials and on other operating systems. Authenticated tools
currently support `leetcode.com` and macOS Keychain only.

After reloading the MCP connection, say **“Test my saved solution with the example
input”** or **“Submit my saved solution.”** The coach freezes the saved file, sends
that exact snapshot through `run_code` or `submit_solution`, and polls the returned
local `operation_id` with `get_submission_status`. Each poll makes one request;
wait at least two seconds between polls, with at most ten polls per user request.

The server verifies the problem's internal ID and language before sending code,
pauses solve timing before the judge request, and records a recognized result
against the frozen snapshot. Timing stays paused until you resume active work.
A test pass does not establish full submission acceptance. Only an accepted full
submission observed through authenticated polling creates verified MCP evidence.

Repeated calls for the same snapshot and test input reuse the existing operation.
If a POST response is lost, the outcome stays **unknown** and the server does not
resend. Inspect your LeetCode history before explicitly requesting another attempt;
the coach must not create new snapshots to bypass this protection. If an operation
has a remote ID, it can be polled again. Account/session errors or website blocks
require local login or the browser workflow; the server does not bypass them.

If version 1.1.0 returned **invalid judge ID** for a test, update/reload the MCP
server to 1.1.1 or later. That version incorrectly rejected the decimal timestamp
in LeetCode test IDs. The old unknown operation cannot be recovered because its ID
was not retained. Keep it in history; after checking any available website result,
explicitly request a fresh test with a new snapshot if needed. Do not delete or
rewrite the unknown operation to force a retry.

For the browser workflow, snapshot your source, pause timing, submit that exact code
on the website, then record the matching result with `record_judge_result`. This
always records **user-reported** evidence. Passing `source: mcp` cannot promote it.

See [MCP security and maintenance](docs/local-mcp.md) for trust boundaries, upstream
limitations and dependency updates. MCP itself is documented in the
[official server guide](https://modelcontextprotocol.io/docs/develop/build-server).

## VS Code

Open this repository and edit the returned `working_file` as a normal source file.
The recommended extension is [Codex](https://learn.chatgpt.com/docs/codex/ide).
The LeetCode VS Code extension is no longer recommended; it is not required for any
local MCP workflow. Disable it in VS Code if previously installed. This project
sets `leetcode.allowReportData` to false for this workspace, but that does not fix
the extension's other audited risks or uninstall it globally.

Tracker-created files use a new numbered directory per attempt so a recall
exercise does not expose the old answer. Existing files can still be adopted
through the CLI's `start --file workspace/leetcode/...` option. MCP creates a new
blank attempt file. The coach reads saved files, not unsaved editor activity.

## Timing and records

An attempt moves between reasoning, implementation, and debugging. `pause` excludes
breaks and judge waits. `finish` stops solve timing before the debrief. No timer
process needs to stay alive; the next command calculates elapsed intervals from
persisted timestamps. Wall time is shown separately. Dates and timestamps use UTC.

These are explicit work-phase timers, not measured typing time. Closing the editor
does not pause them. On conversational recovery the coach pauses a running attempt
and marks its timing unconfirmed. Confirm it or correct each affected interval
using your own recollection; original intervals and correction reasons remain
in history. Unconfirmed or invalid timing is excluded from report aggregates.

Each attempt keeps its language, hints, phases, code snapshots, judge results,
feedback, teach-back, and review date. A passed local test is not LeetCode acceptance.
Acceptance recorded from an actual MCP submission is associated with its submission
ID and snapshot. `mcp` is recorded provenance, not a cryptographic attestation: the
coach is responsible for checking the real result before labeling it verified.
Unknown results remain unknown and conflicting terminal verdicts are rejected.

Review intervals are intentionally simple: 1 day for incomplete or helped attempts,
7 days for an independent accepted solve with teach-back, and 30 days for an
independent accepted review with teach-back. A custom review date is supported.

## Manual commands

Every command accepts `--json` and `--root PATH`. Run from this repository so Python
can import the package. The default data root is this repository, regardless of shell
working directory. IDs in this example assume an empty workspace; use returned IDs.

```bash
python3 -m leetcode_coach start two-sum --id 1 --title "Two Sum" --difficulty Easy
python3 -m leetcode_coach phase 1 implementation
python3 -m leetcode_coach hint 1 --level 1 --note "Asked about duplicate values"
python3 -m leetcode_coach pause 1 --reason break
python3 -m leetcode_coach resume 1
python3 -m leetcode_coach phase 1 debugging
```

After you save your code, freeze it before submitting through an external judge:

```bash
python3 -m leetcode_coach snapshot 1
python3 -m leetcode_coach show-snapshot 1 --json
python3 -m leetcode_coach pause 1 --reason judge
```

Only after observing the result for that same source:

```bash
python3 -m leetcode_coach judge 1 --snapshot 1 --source user-reported --verdict accepted
python3 -m leetcode_coach finish 1 --outcome accepted
```

`judge` records evidence; it does **not** submit code. Use `--kind test` for a test
run, `--source local-test` for local tests, or `--verdict unknown` for a timeout.
MCP terminal submission results require `--submission-id`. A test pass cannot
unlock `finish --outcome accepted`. Unfinished practice can finish as `unsolved`
or `abandoned` without any judge result.

For an interrupted timer, inspect and resolve it explicitly:

```bash
python3 -m leetcode_coach recover 1
python3 -m leetcode_coach correct 1 --interval 2 --seconds 600 --reason "User confirmed ten active minutes"
python3 -m leetcode_coach confirm-timing 1
python3 -m leetcode_coach resume 1
```

Use the actual interval ID and duration from your attempt. Clock rollback blocks
invalid transitions; correct the system clock, recover the attempt, and record a
duration correction if needed. Repeated `finish` with the same outcome is a no-op.

After finishing, put observed feedback in `.coach/debrief.json`, for example:

```json
{
  "approach": "Describe the approach the user actually attempted",
  "correctness": "Record the correctness reasoning demonstrated",
  "complexity": "Record their time and space analysis",
  "optimizations": "Explain a specific improvement and its tradeoff",
  "testing": "Record covered and missed cases",
  "communication": "Record clarity of the explanation",
  "mistakes": ["duplicate-handling"],
  "next_exercise": "Repeat the problem independently"
}
```

Omit fields not assessed. Empty or unexpected field names are rejected.

```bash
python3 -m leetcode_coach feedback 1 --file .coach/debrief.json --teach-back
python3 -m leetcode_coach end-session --summary "Practiced arrays and explained the invariant"
python3 -m leetcode_coach report --session 1
python3 -m leetcode_coach report --group-by encounter
python3 -m leetcode_coach report --group-by topic --output reports/progress.md
```

Only include `--teach-back` when the user demonstrated understanding. A solve counts
as independent only when `feedback` also receives `--independent`,
confirming original work without outside or coach help. Do not add that flag to the
hinted example above. For a confirmed independent solve, use both flags. Reports refuse
to overwrite an existing file. Additional groupings: `problem`, `difficulty`,
`language`, and `assistance`. Use `show ATTEMPT --json` for interval and event history.

## Storage and backups

The source of truth is `.coach/progress.sqlite3`. SQLite transactions serialize
writes. Snapshots store exact UTF-8 source bytes inside the database; editing the
working file later cannot alter them. Each session can include several sequential
attempts; `end-session` closes it. Only one unfinished attempt can exist at a time.

All local data, working files, backups, personal config, and generated reports are
ignored by Git. Reports are exports, not editable progress records. SQLite schema
versions are checked; incompatible databases are rejected without migration.

```bash
python3 -m leetcode_coach backup backups/practice-2026-09-20.sqlite3
python3 -m leetcode_coach --root /path/to/new-practice-root restore backups/practice-2026-09-20.sqlite3
python3 -m leetcode_coach --root /path/to/new-practice-root status
```

Backups use SQLite's consistent backup API and an integrity check. Backup and restore
refuse to overwrite existing files. Restoration targets a new data root; preserve
your current database instead of deleting it. Backups include snapshots and history,
but **not working files or configuration**. Copy those separately if needed. An open
attempt restored without its working file can still be recovered/finished; restore
the saved file before creating new snapshots. There is no automatic cloud backup.

## Development and verification

```bash
make check
```

Tests use temporary roots and controlled clocks; they never populate your personal
progress or submit solutions. The dependency-free CI job checks Python 3.10 and
3.14. The MCP job installs the hash-locked environment on Python 3.14 and runs
`make check-mcp`, including protocol tests without contacting LeetCode.

Live problem, search and daily-challenge lookup were checked without credentials.
Live checks remain explicit because LeetCode's public website API is undocumented
and may change or be unavailable. Authenticated judge transport is tested with
synthetic responses; a real account submission has not been validated. Native
Keychain create/read/update/delete was checked with a disposable dummy entry.

See [coaching behavior evaluation](docs/coaching-evaluation.md) for scenario results.

## Inspiration

The coaching workflow was informed by
[guanyipengai/leetcode-coach](https://github.com/guanyipengai/leetcode-coach) at revision
`5fb42e2ff18e30b80d87350b02376cf810de1a66`: progressive assistance, teach-back, and
review-driven practice. This tracker and its instructions are independently written;
no upstream source code, study history, problem statements, or personal records were
imported. The source project is MIT licensed.
