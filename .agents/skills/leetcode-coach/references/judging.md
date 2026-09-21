# LeetCode judge workflow

The tracker records evidence; it does not call LeetCode. The coach uses the
available MCP tools or the user's website/extension result. Do not assume that
tools described in a README are connected to the current conversation.

## Before a judge operation

Use the user's request to test/submit or an already established session preference
for that explicit checkpoint. Reviewing code does not authorize submission.

1. Run `snapshot ATTEMPT --json`, retain its ID, then `show-snapshot SNAPSHOT --json`.
2. Pause solve timing with `pause ATTEMPT --reason judge` if it is running.
3. Call the available `run_code` or `submit_solution` using the frozen `code`, the
   snapshot's `language`, and the attempt's problem slug. Never send code from a
   file reread after the snapshot. Do not send tokens, config, or repository files.

Pinned server 1.4.0 registers these tools only when a session cookie is configured.
Its inspected inputs are `titleSlug`, `lang`, and `typedCode`, with optional
`timeoutMs` and `pollIntervalMs`; `run_code` also accepts `dataInput`. Use a bounded
wait (for example 30,000 ms) rather than repeatedly issuing a submission. Inspect
the connected tool schema before use in case configuration/version differs.

## Interpret the result

The pinned implementation returns JSON text with `start`, `checkUrl`, and `check`.
It can also return JSON text containing `error` and `message` without `isError`.
Inspect both the MCP error flag and the decoded payload. A successful tool call
or HTTP response alone is not acceptance.

For an official submission, require a final judge status and its actual submission
ID. A completed accepted result maps to `accepted`; wrong answer, time limit,
memory limit, runtime error, and compile error map to the CLI's corresponding
hyphenated verdicts. A code test uses `--kind test` even if it passes every supplied
test. Missing, pending, timed-out, and network-error results map to `unknown`.
Do not infer a final verdict from a submission-start response or invent IDs.

Record only fields present in the result. Convert units explicitly if necessary;
omit runtime/memory when their units are ambiguous. Example, after actually
observing the matching result (IDs shown are illustrative):

```bash
python3 -m leetcode_coach judge 1 --snapshot 1 --source mcp --kind submission \
  --verdict accepted --submission-id 12345 --runtime-ms 3 --memory-mb 16
```

For website/extension reports, first establish that the snapshot matches the code
the user submitted. Use `--source user-reported`; do not label it MCP verified.
For local tests use `--source local-test --kind test`.

## Unknown results and recovery

Retain the snapshot and unknown result. Do not retry a submission automatically;
another call may create a second real submission. Reconcile with submission
history/detail using the known ID when available. Match the returned code and
language to the snapshot before recording verified acceptance. If identity or
code cannot be established, report the uncertainty and keep the evidence unknown.

The CLI deduplicates identical results and accepts an unknown-to-terminal update
as another event. It rejects conflicting terminal verdicts for the same submission.
If MCP is unavailable, the user can submit normally and report the outcome. A
failure to connect never counts as a wrong answer.

Keep credentials in the local host's environment. Never ask the user to paste a
session cookie into chat, put it in a committed file, or include it in a report.
