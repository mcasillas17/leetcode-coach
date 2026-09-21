# Coaching behavior evaluation

Evaluated during implementation on September 20, 2026 (America/Los_Angeles).
Scenarios are synthetic. They are not the user's LeetCode progress.

## Baseline

An independent agent received five practice requests without the new skill or
repository instructions. Its responses exposed two concrete gaps:

- For "mark this mastered" after a reported acceptance, it proposed changing
  mastery if no existing repository rule prevented it. Teach-back was not inherent
  to the generic workflow.
- For "improve it," it proposed implementing a performance improvement in the
  user's solution. During this coaching workflow, the desired response is feedback
  unless the user explicitly requests an edit.

The baseline gave a useful hint and honored an explicit request for a complete
solution, but did not record either level of assistance. It correctly recognized
that an unpaused lunch break made active time uncertain.

## Forward test with the skill

A different agent read the skill and judging reference and exercised the real CLI
against six isolated temporary roots. It inspected saved records and source hashes.
It made no external calls, submitted no code, changed no repository files, and
removed its fixtures. The examples below summarize its observed responses/actions.

| User request | Observed behavior and state |
| --- | --- |
| Small hint on Two Sum | Asked what other value would make the target sum; recorded one level-1 hint. |
| Explicit complete Python solution | Provided code in the response, recorded level 5, finished unsolved, and produced a report with zero accepted/independent solves. No solution file edit. |
| Website accepted; mark mastered | Asked to establish matching source and authorship; recorded no acceptance or teach-back while answers were missing. |
| Return after lunch; finish and report coding time | Recovered a running implementation timer, finished the session, retained about 5,400 recorded seconds as unconfirmed, and reported zero timing samples with one excluded attempt. No guessed break duration. |
| Improve a slow saved approach | Read the nested-loop implementation, discussed its complexity and complement lookup, recorded level-2 assistance, and left the file unchanged. |
| Unsuccessful attempt | Finished unsolved, saved a next exercise, closed the session, and scheduled next-day review without claiming acceptance or understanding. |

All six saved-solution hashes were unchanged. The acceptance scenario stopped
before a simulated follow-up user answer, so it did not test eventual acceptance
verification. The lunch scenario initially referred to a wrong fixture interval ID;
the evaluator reran it with the actual returned ID and verified the state above.

## Finding and correction

The evaluator found that imported code with unknown authorship could still appear
independent merely because zero hints were logged. The tracker now requires an
explicit debrief `--independent` confirmation of original unaided work. Recorded
help prevents that confirmation. Unknown assistance stays `unconfirmed`, is not
counted as an independent solve, and does not earn the longer independent-review
interval. The skill explicitly asks about authorship/outside assistance and records
outside help using the same assistance levels. Automated regression tests exercise
both unknown independence and rejected independence after recorded help.

A focused follow-up exercised three new temporary fixtures through actual snapshot,
user-reported judge, finish, feedback, and report commands. Unknown authorship stayed
unconfirmed with zero independent solves and next-day review. Explicit original,
unaided work with teach-back counted as one independent solve and scheduled seven-day
review. Level-5 outside assistance caused `--independent` to fail with exit 2; the
ordinary helped debrief remained valid. All results stayed user-reported/unverified,
and all solution files remained unchanged. The evaluator removed its fixtures.

## Code review and external checks

Independent code review found clock rollback on paused finish, contradictory
terminal verdicts for one submission, malformed config types, and an MCP diagnostic
cleanup hang after an exited launcher. Each received a failing regression test and
a targeted correction. Unknown-to-terminal judge reconciliation remains supported.
The reviewer's focused follow-up found no remaining material issues, measured the
original inherited-stdout timeout reproduction at 0.11 seconds, and ran `make check`
successfully with 33 tests. Windows diagnostic cleanup was not tested.

The pinned MCP server 1.4.0 initialized with protocol 2024-11-05, exposed nine
public tools, and returned public Two Sum metadata. Its authenticated judge tool
definitions were inspected in the installed package. Authenticated execution and
VS Code sign-in were not exercised. These checks do not claim the current Codex
conversation has reloaded the new project MCP configuration.
