# LeetCode Coach

Practice in VS Code while Codex acts as your interviewer. The coach checks your
reasoning, gives requested hints, reviews correctness and performance, and records
how your attempts change over time.

The tracker runs locally with **Python 3.10+ and no Python dependencies**. It works
without a LeetCode account connection. Optional MCP tools provide problem lookup
and authenticated judge operations.

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
language; it does not install compilers. MCP language support is determined by
the connected server. Update the VS Code extension's default language separately
if you use it.

## Connect LeetCode MCP

The integration is pinned to
[`@jinzcdev/leetcode-mcp-server@1.4.0`](https://github.com/jinzcdev/leetcode-mcp-server).
Use Node.js 20+ with `npx` available to the Codex host.

Copy the supplied project configuration, preserving any existing settings:

```bash
mkdir -p .codex
cp -n config/leetcode-mcp.toml .codex/config.toml
```

If that file already exists, merge the `[mcp_servers.leetcode]` table instead.
Open a fresh Codex session in this trusted project or restart its MCP connection.
The setup disables community-solution tools to reduce accidental answer exposure.
Public problem responses can still contain tags and hints; the coaching skill
keeps those out of the interview conversation.

Verify the external server independently:

```bash
python3 scripts/check_mcp.py
python3 scripts/check_mcp.py --problem two-sum
```

The probe initializes the server, lists its actual tool schemas, and optionally
retrieves public metadata. It explicitly clears `LEETCODE_SESSION` in its child
process and never runs or submits a solution.

For authenticated operations, supply `LEETCODE_SESSION` through the local Codex
host's environment and restart the connection. Obtain the cookie from your signed-in
LeetCode browser session using the [server's authentication instructions](https://github.com/jinzcdev/leetcode-mcp-server#authentication).
Keep it out of chat, source files, Git, reports, and shell history. A terminal's
environment is not automatically inherited by an already-running desktop app.
The provided configuration forwards the variable; it never contains the cookie.

With credentials present, the server registers `run_code`, `submit_solution`,
and private submission-detail tools. The coach submits only at your request,
using an immutable snapshot. Without credentials, submit through the website or
VS Code and report the result; the tracker labels it **user-reported**.

Project MCP configuration is described in [OpenAI's MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).
The coach checks the current session's tools instead of assuming a connection is active.

## VS Code

Open this repository folder. The recommended extensions are
[LeetCode](https://marketplace.visualstudio.com/items?itemName=LeetCode.vscode-leetcode)
and [Codex](https://learn.chatgpt.com/docs/codex/ide). The LeetCode extension is optional;
editing normal files in VS Code is enough when you use MCP or the website to judge.

Workspace settings put extension files in `workspace/leetcode/` and select
`leetcode.com`. Follow the extension's documented sign-in workaround if ordinary
login fails. Extension login and MCP authentication are separate.

Tracker-created files use a new numbered directory per attempt, preventing an old
answer from appearing in a recall exercise. To use an existing extension-generated
file, start with `--file workspace/leetcode/1.two-sum.py`; the tracker preserves it.
For a blind redo, use a new blank attempt file. The coach sees saved file contents,
not unsaved keystrokes. There is no automatic editor-activity tracking.

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
progress or submit solutions. CI checks Python 3.10 and 3.14. Live MCP checks are
separate because they require Node, network access, and an available external service.

During implementation, the pinned server initialized, listed nine public tools,
and retrieved Two Sum metadata without authentication. Authenticated test/submission
tool definitions were inspected in the installed package; real authenticated judge
execution and VS Code sign-in have not been exercised. The tracker/manual fallback
are tested independently of those account-dependent operations.

See [coaching behavior evaluation](docs/coaching-evaluation.md) for scenario results.

## Inspiration

The coaching workflow was informed by
[guanyipengai/leetcode-coach](https://github.com/guanyipengai/leetcode-coach) at revision
`5fb42e2ff18e30b80d87350b02376cf810de1a66`: progressive assistance, teach-back, and
review-driven practice. This tracker and its instructions are independently written;
no upstream source code, study history, problem statements, or personal records were
imported. The source project is MIT licensed.
