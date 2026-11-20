# ADR 0010: adopters call `pr-policy.yml` at a tag instead of copying it

- Status: Proposed (the owner accepts or rejects it; nothing here is in force)
- Date: 2026-11-20
- Deciders: repository owner
- Task record: #115 (Backlog #66 line X5 with L14 folded in)
- Amends: nothing. ADR 0006 keeps "copy the two workflows" until the owner accepts this record
- Roles: spike run and this record written by the Implementer (a project thread)

## Context

ADR 0006 has every adopting project copy `pr-policy.yml` and `ci.yml`. Copies go stale: the
adopting repository used for this spike still carried a 63-line `pr-policy.yml` from before
the Ready label, the review gate, the thresholds and the cost defaults existed. A reusable
workflow called at a tag would give every adopter the current checker with one line.

The spike added `workflow_call:` to the `on:` block of both workflows (two lines, nothing
else) and ran one caller from a private, user-owned adopting repository against this
repository's branch `claude/project-thread-4uwc2u` at `d74a317`. The run is
`actions/runs/44731845653` in that repository, 2026-11-20 11:57 UTC, 12 seconds; the
repository is private and is not named here, the link is on the owner's project thread. The
caller, 12 lines without comments:

```yaml
name: Conductor caller spike
on:
  pull_request_review:
    types: [submitted]
permissions:
  contents: read
  issues: read
  pull-requests: read
jobs:
  policy:
    uses: alhanaei/Conductor/.github/workflows/pr-policy.yml@claude/project-thread-4uwc2u
  ci:
    uses: alhanaei/Conductor/.github/workflows/ci.yml@claude/project-thread-4uwc2u
```

The trigger was a submitted review and the commits carried a skip marker, because that
repository's own test workflow runs a macOS job on every push and pull request and the record
allows ten billed minutes. An adopter uses `on: pull_request`; the called workflow read the
pull request from the event payload either way.

## Findings

Each answer is what the run showed, what GitHub's documentation says where the run could not
show it (marked "docs"), or `unknown`.

(a) Check names. The called jobs reported as `policy / linked-task` and `ci / verify`:
`<caller job id> / <called job name>`. A reusable workflow cannot report under the bare name
`linked-task`. An adopter that calls instead of copying must therefore change the required
check in branch protection, an owner step, from `linked-task` to the new name; with the caller
job named `linked-task` the name is `linked-task / linked-task`. Until that edit a protected
branch waits forever on a check that no longer reports. Conductor's own checks keep their
names, because its own pull requests still trigger the workflows directly.

(b) Private caller, public workflow. Yes: a private user-owned repository called this public
repository's workflows with no setting, secret or token added. Observed at a branch ref. At a
tag: `unknown`, since no tag exists here; the run metadata shows GitHub resolving the ref to a
commit SHA, and docs treat a branch, a tag and a SHA alike.

(c) What the called `linked-task` reads. Everything came from the caller: the log shows
`BLOCKED_LABEL: blocked`, which is the adopting repository's own `CONDUCTOR_BLOCKED_LABEL`
variable, not this repository's value; the pull request number, head and base came from the
caller's event; and the check read the caller's issue and failed it correctly for a missing
`status:ready`. The caller granted `contents: read`, `issues: read` and `pull-requests: read`
at workflow level and that was enough. Docs: the called workflow can lower these permissions
but never raise them. With no `permissions:` in the caller: `unknown`, not run; docs say the
repository's default token permissions then apply, which on a restricted default would not
include `issues: read`. Organization-level variables: `unknown`, not run.

(d) Is `ci.yml` worth calling. No. The called `verify` checked out the adopter, passed the
whitespace and actionlint steps, then ran this repository's own last row,
`python3 -m unittest discover -s tests -p 'test_*.py'`, against the adopter's test directory
and failed with 24 import errors. Each project replaces the rows, so there is nothing shared
to call; only the cost defaults in the header are common, and those are comments. Only
`pr-policy.yml` is a candidate.

(e) Tags. No tag exists on this repository. Cloud threads cannot push tags, so creating and
moving one is an owner step each time the checker changes:
`git tag -f v1 <merge SHA> && git push --force origin v1`. A moved tag reaches every adopter
on its next pull request event with no pull request in the adopter; that is the benefit and
the risk, since a bad checker turns every adopter red at once and the fix is a second tag
move. A branch named `v1` that only moves by pull request would avoid the owner's terminal,
at the price of a second protected branch: `unknown` whether that is wanted, not tested.

(f) Billed minutes. The same as a copy. The caller job itself takes no runner; each called job
ran once on `ubuntu-latest` (5 s and 8 s). GitHub's usage endpoint returned 0 billable ms for
both jobs of this run, which is not trusted as a price; by the rounding rule on the page each
job is one billed minute in a private repository, exactly what the copied job costs. Docs:
runner time is billed to the caller. Calling changes staleness, not cost. Calling `ci.yml` too
would add a second job, one more minute per run, for nothing (d).

(g) Moving under an organization. The owner is part of the `uses:` path, and docs say GitHub
Actions follows no redirect for actions or reusable workflows after a rename; the transfer
page promises redirects for links and git only. Every caller written before the move would
have to be edited after it, and until then its check would not report. Observed: `unknown`,
no move was made. Organization variables: `unknown`, as in (c). If the organization is
created, move this repository first and write the callers once.

## Recommendation

Pending. The record's stop condition holds a recommendation back while (a) means adopters
must edit branch protection; the owner's answer is recorded here before this record is
proposed for acceptance.
