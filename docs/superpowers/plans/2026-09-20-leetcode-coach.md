# LeetCode Coach Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. The user requested implementation in this session.

**Goal:** Run interview practice through Codex with durable local timing, evidence, and progress.

**Architecture:** Python CLI over a SQLite store, a repository coaching skill, and an optional existing LeetCode MCP server. Saved working files stay separate from immutable code snapshots. Every mutation uses a database transaction.

**Tech Stack:** Python 3.10+ standard library, SQLite, unittest, Node.js for optional MCP.

**Spec:** `docs/superpowers/specs/2026-09-20-leetcode-coach-design.md`

## Global constraints

- English, Python 3, leetcode.com, interview mode are configurable defaults.
- No model API service, custom MCP server, custom editor extension, or background polling.
- One unfinished attempt at a time; no unsolicited solution edits or submissions.
- Local progress, backups, reports, and solutions remain ignored by Git.
- Keep measured timing, user-reported acceptance, and verified judge evidence distinct.

## Review focus

1. Clock rollback and interrupted sessions must not yield fabricated valid durations.
2. Two simultaneous CLI writers must not open two active attempts or lose evidence.
3. Repeating finish or recording the same judge result must not inflate progress.
4. A malformed result or a local test pass must not become verified acceptance.
5. A backup failure, unsafe path, or future schema version must not overwrite data.

## Task 1: Durable attempts, timing, and evidence

**Files:** `leetcode_coach/store.py`, `leetcode_coach/tracker.py`, `tests/test_tracker.py`.

**Interfaces:** `Tracker(root, clock=utc_now)` exposes `start`, `phase`, `pause`, `resume`, `recover`, `confirm_timing`, `correct_interval`, `hint`, `snapshot`, `judge`, `finish`, `feedback`, `attempt`, `status`, `backup`, and `restore`. Public methods return JSON-compatible dictionaries. Explicit attempt IDs prevent accidental changes to a different attempt.

- [ ] Write controlled-clock tests before implementation, including:

  ```python
  attempt = tracker.start('two-sum', 1, 'Two Sum', 'Easy')
  clock.advance(60)
  tracker.phase(attempt['id'], 'implementation')
  clock.advance(120)
  tracker.pause(attempt['id'])
  clock.advance(900)
  tracker.resume(attempt['id'])
  clock.advance(30)
  tracker.finish(attempt['id'], 'abandoned')
  assert tracker.attempt(attempt['id'])['timing']['active_seconds'] == 210
  ```

- [ ] Run `python3 -m unittest discover -s tests -v`; expect missing module failure.
- [ ] Create transactional schema and tracker. Use `BEGIN IMMEDIATE`, parameterized SQL, a unique partial index for unfinished attempts, append-only events, stored snapshot bytes, explicit evidence provenance, and separate interval adjustments.
- [ ] Verify pause/restart, repeated phases, recovery confirmation, clock rollback correction, repeated finish, duplicate judge results, snapshot immutability, invalid paths/results, and consistent backup/restore using the same test command; expect all tracker cases to pass.
- [ ] Commit the independently tested tracker.

## Task 2: CLI and progress reports

**Files:** `leetcode_coach/__main__.py`, `leetcode_coach/cli.py`, `leetcode_coach/reports.py`, `tests/test_cli.py`, `tests/test_reports.py`, `coach.json`, `.gitignore`, `Makefile`.

**Interfaces:** CLI uses `Tracker`; every command supports machine-readable JSON through `--json`. `build_report(tracker, group_by, session_id)` returns attempts, totals, groups, and reviews; `render_markdown(report)` emits the human-readable view.

- [ ] Add subprocess tests for a fresh workspace, an offline practice cycle, invalid CLI arguments, and non-destructive backup/restore. Add report tests separating first/repeat and assisted/independent attempts and excluding unconfirmed timing.
- [ ] Run `python3 -m unittest discover -s tests -v`; expect missing CLI/report behavior.
- [ ] Implement explicit argparse commands and JSON feedback import, validate object shapes and file sizes, and render Markdown with escaped user content. Reports include per-phase totals, hint counts, mistakes, acceptance evidence, review dates, and sample counts.
- [ ] Run the complete suite and the documented offline commands in a temporary root; expect accurate results and no changes to real progress.
- [ ] Commit CLI and reports.

## Task 3: Coaching and integrations

**Files:** `.agents/skills/leetcode-coach/SKILL.md`, `AGENTS.md`, `.vscode/settings.json`, `.vscode/extensions.json`, `config/leetcode-mcp.toml`, `README.md`, `docs/coaching-evaluation.md`, `scripts/check_mcp.py`, `.github/workflows/check.yml`.

**Interfaces:** Skill invokes the documented CLI; MCP setup enables only problem/user/judge tools whose schemas were inspected. The MCP probe initializes the pinned external server, lists tools, and optionally retrieves one public problem. It never uses credentials or submits code.

- [ ] Record independent baseline responses for hints, full-answer requests, unverified acceptance, recovery after a break, and ambiguous requests to improve code.
- [ ] Write concise coaching instructions with a worked CLI example, recovery protocol, judge provenance, immutable snapshot submission flow, debrief, and review policy.
- [ ] Run independent scenarios with the skill and real CLI in a temporary root; inspect resulting responses and records. Fix demonstrated gaps.
- [ ] Pin the npm server release and smoke-test initialize/tools/list. Inspect run/submit input schemas; probe public problem retrieval separately and report any service failure honestly.
- [ ] Validate skill frontmatter with the skill-creator validator, run all tests, and document setup, backup/restore, timer semantics, failure recovery, optional authentication, and startup prompts.
- [ ] Request one independent whole-change code review; resolve material findings with regression tests.
- [ ] Commit the verified result and hand off with exact run commands and integration limits.

## Execution record

- Ruling: Work on `codex/leetcode-coach` in the user's clean dedicated clone, preserving the requested path; no competing code or uncommitted work requires another checkout.
- Ruling: Proceed with inline implementation on the user's explicit request, without another approval cycle.
- Pre-flight: Task 2 consumes Tracker's dictionary interface; Task 3 uses Task 2's CLI. Commands and skill examples will be tested together.
