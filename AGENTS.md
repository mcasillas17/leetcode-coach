# Working in this repository

For LeetCode practice, mock interviews, hints, solution reviews, and progress
questions, read `.agents/skills/leetcode-coach/SKILL.md`. Use its local tracker
instead of estimating durations or changing the SQLite database directly.

The user writes practice solutions. During coaching, discuss an improvement
without editing their solution unless they explicitly ask you to edit it.

For development of the coach itself, use the design in
`docs/superpowers/specs/2026-09-20-leetcode-coach-design.md`. The coaching
restrictions do not prevent implementing the tracker or writing test fixtures.
Run `make check` after code changes. Keep runtime progress, credentials, solutions,
backups, and generated reports out of commits.
