# Issue tracker

Use GitHub Issues in `alexsaccone/signalScout`. Pass
`--repo alexsaccone/signalScout` to `gh issue` commands to target this repo
from any checkout or branch. If `gh` is unavailable, use the GitHub REST API
for the same repository.

- Publish a spec or ticket with `gh issue create`. Use `--body-file` for
  multiline text.
- Fetch a ticket with `gh issue view <number> --comments`. Queue work with
  `gh issue list` and the relevant state and label filters.
- Apply triage labels with `gh issue edit`. Use `gh issue comment` to record
  decisions and `gh issue close` to close resolved issues.
- Use GitHub sub-issues and issue dependencies where available. Otherwise
  use `Part of #<number>` and `Blocked by: #<number>` in the issue body.

**PRs as a request surface: no.**

## Wayfinding operations

Use a `wayfinder:map` issue as the parent and link each child ticket.
Label children `wayfinder:<type>` for `research`, `prototype`, `grilling`,
or `task`. Pick the first open, unassigned child whose blockers are
closed. Assign it before starting. Post the answer and close the child
when resolved, then link the result from the map's Decisions-so-far.
