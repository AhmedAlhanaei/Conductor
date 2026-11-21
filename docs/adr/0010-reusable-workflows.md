# ADR 0010: adopters call `pr-policy.yml` at a tag instead of copying it

- Status: Accepted (the owner's "Accept adr", 2026-11-20 23:54 UTC, on the project thread
  that ran the spike; logged on #115 and applied under #121). Proposed from 2026-11-20
  12:16 UTC until then
- Date: 2026-11-20
- Deciders: repository owner
- Task record: #115 (Backlog #66 line X5 with L14 folded in)
- Amends: ADR 0006, in one point: adopters call `pr-policy.yml` at a tag instead of copying
  it. `ci.yml` is still copied, and everything else in ADR 0006 stands
- Amended by: ADR 0011 (an adopter's caller also runs on a submitted review; the first tag,
  `v1`, follows slice 4 of #124, #128, and no tag is created before it)
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

The owner lifted the stop condition on 2026-11-20 at 12:14 UTC, on the project thread's
decision card: recommend calling `pr-policy.yml` only, with the one-time rename of the
required check accepted.

1. Adopters call `pr-policy.yml` at the tag `v1` and stop copying it. The checker, its tests
   and its variables stay in this repository; the adopter keeps its `CONDUCTOR_*` variables.
2. Adopters keep copying `ci.yml` and replacing its rows, as today (d).
3. Each adopter's owner renames the required check once, from `linked-task` to
   `linked-task / linked-task`, in the same sitting as the caller's merge (a).
4. The owner creates `v1` on the merge commit of this record's pull request and moves it when
   the checker changes (e). A checker change is tested here by `verify` before the tag moves.
5. If this repository moves under an organization, it moves before the first adopter
   switches, or every caller is edited again after the move (g).
6. Conductor's own pull requests keep triggering both workflows directly; nothing changes
   here but the two `workflow_call:` lines, which are inert until something calls them.

Not decided here: amending ADR 0006 and the README adoption checklist, which follow the
owner's acceptance as their own record; and the three `unknown` answers (a tag ref,
a caller without `permissions:`, organization variables), which the first adopter's switch
answers.

The adopter's whole `.github/workflows/pr-policy.yml`:

```yaml
name: PR policy
on:
  pull_request:
    types: [opened, edited, synchronize, reopened]
permissions:
  contents: read
  issues: read
  pull-requests: read
jobs:
  linked-task:
    uses: AhmedAlhanaei/Conductor/.github/workflows/pr-policy.yml@v1
```

For the README checklist, if accepted: "Add the eleven-line caller above as
`.github/workflows/pr-policy.yml`, then require the check `linked-task / linked-task`."

## Acceptance note, 2026-11-20

Added under #121 when the owner accepted this record; the text above is otherwise as proposed.

- The repository moved under the organization `AhmedAlhanaei` on 2026-11-20, after the spike
  and before any adopter switched, as recommendation 5 asks. Finding (g) applied to this
  record itself: the adopter's caller above now reads `AhmedAlhanaei/Conductor/...`. The
  spike caller under Context keeps `alhanaei/Conductor/...`, because that is the path that
  was run.
- Recommendation 4 says `v1` goes on "the merge commit of this record's pull request", which
  was 47f53a7 and carries the old path in this file. The owner creates `v1` on the merge
  commit of the pull request that closes #121, or on a later head of `main`, not on 47f53a7.
  Until the tag exists the caller's ref does not resolve.
- "Not decided here" is settled for ADR 0006 and the README by #121: ADR 0006 carries the
  "Amended by" line and the README checklist carries the caller and the check name. The three
  `unknown` answers stay open until the first adopter switches.
