# Browser judge workflow

The repository-owned MCP server provides public lookup and local tracking only.
It has no account connection, run-code tool, or submission tool. The user submits
through the LeetCode website. Do not install or reconnect another server to bypass
this boundary.

1. Use `snapshot_solution(attempt_id)` (CLI: `snapshot ATTEMPT --json`) to freeze
   saved code. Retain the snapshot ID. `get_snapshot(snapshot_id)` returns that
   exact source for review; it enters the MCP host/model conversation.
2. Pause the running timer with `pause_attempt(attempt_id, reason="judge")`.
3. The user tests or submits on the website. Establish that the submitted source
   matches the frozen snapshot before recording a result.
4. Use `record_judge_result(attempt_id, snapshot_id, verdict, ...)`. All results
   recorded by this tool are **user-reported**, even though the tracker operation
   itself uses MCP. It cannot claim independently verified acceptance.

Use `kind="submission"` for a full submission and `kind="test"` for example/custom
tests. Verdicts: accepted, wrong-answer, time-limit, memory-limit, runtime-error,
compile-error, unknown. A test pass does not establish LeetCode acceptance.
Missing, pending or ambiguous results stay unknown; do not invent a submission ID,
infer acceptance from successful transport, or associate unrelated source.
Record runtime/memory only when supplied with known units (milliseconds/MB).

CLI equivalent (illustrative IDs):

```bash
python3 -m leetcode_coach judge 1 --snapshot 1 --source user-reported \
  --kind submission --verdict accepted --submission-id 12345
```

For local tests performed separately, the CLI supports `--source local-test
--kind test`. Neither the MCP server nor the tracker executes solution code.
Keep local test results distinct from LeetCode submissions.

The tracker preserves unknown-to-terminal history, deduplicates identical judge
results, and rejects conflicting terminal verdicts. If code/result identity is
unclear, leave the evidence unresolved. Resume only when the user returns to
active work; finish before debrief if solving is complete.

Historical `mcp` evidence remains readable for compatibility, but this server
cannot create it. Never ask for a session cookie or put credentials in chat,
source, configuration, Git, or reports.
