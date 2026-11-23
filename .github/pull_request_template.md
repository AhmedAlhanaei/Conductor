<!-- Project-owned template. Copy to .github/pull_request_template.md. -->
## Task

Closes #
<!-- One task only: the body names no other task after a closing keyword, not even quoted in code or a blockquote. -->

- Implementer runtime: <for example Claude Code; the Reviewer runs on another and submits a GitHub review of the head, nothing is written here>

## What changed and why

## Verification against the exact head

| Check | Command or procedure, cwd | Result (passed / failed / not run) | Tested SHA |
| --- | --- | --- | --- |
| | | | |

One row per numbered acceptance criterion of the record, filled before the pull request opens:

| Acceptance criterion | Evidence | Result (passed / failed / not run) | Tested SHA |
| --- | --- | --- | --- |
| 1. | | | |

- Pushes to the open pull request: <n> of <budget from the record, default 2>
- Billed Actions minutes for this pull request: <n, or "0, public repository">
- Lead time from `status:ready` to merge: <n, or "not merged yet"; read from the issue timeline and the merge>

## Merge danger

- Door: two-way (one revert commit undoes it, no data or external effect) or one-way (migration, published artifact, external call, deletion, credential or access change). State which and why.
- Blast radius: what else breaks if this is wrong, and who notices first.

## Found and left

- Findings proposed as new records or added as comments on existing ones, not done here:
