# ADR 0012: A release candidate tag is tested on an adopter before `v1` moves

- Status: Accepted (the owner's "yes to all.", 2026-11-28 15:02 UTC in the claude.ai project
  chat, to the three questions of #152 as the Planner put them at 15:01 UTC; recorded in the
  Ready comment on #152)
- Date: 2026-11-28
- Deciders: repository owner
- Task record: #152 (sub-issue of #124)
- Amends: ADR 0010, in three points: an adopter's caller names a tag or a commit SHA and
  never a branch; `v1` moves only after a release candidate tag passed on an adopter
  (recommendation 4 and finding (e) tested a change by `verify` here only); each release
  also gets an exact tag that never moves. ADR 0011, in one point: the first tag on the
  merge commit of #128 is `v1-rc1`, and `v1` follows on the same commit
- Roles: questions put by the Planner (the project coordinator); this record written by the
  Implementer (a project thread)

## Context

Every merge lands on `main`, and until this record no tag existed. ADR 0010 has adopters call
`pr-policy.yml` at the tag `v1` and has the owner move that tag when the checker changes. A
moved tag reaches every adopter on its next pull request event, so a bad checker turns every
adopter red at once. ADR 0010 names one test before the move: `verify` on this repository.
`verify` runs the checker's unit tests; it does not run the checker as a called workflow in
another repository, with that repository's variables, token permissions and required check
name. The first place a change met those was an adopter's real pull request.

## Decision

1. `main` is the staging line. Conductor's own pull requests run the workflows from `main`
   directly, so every change is used here first. Nothing outside this repository calls `main`
   or any other branch.
2. An adopter's caller names a tag or a commit SHA after the `@`, never a branch: `@v1` to
   follow releases, an exact tag or a 40-character SHA to stay on one release until its own
   pull request changes the line.
3. Every release goes out as a release candidate first. The owner cuts `v1-rcN` on the `main`
   commit to release. N counts up by one for every candidate and is never reused; a candidate
   tag never moves and is not deleted.
4. One adopter tests the candidate: GachaBot today. Its caller points at the candidate on a
   pull request branch, and that one pull request is the test (the checklist below). A
   workflow file is read from the pull request's head, so the candidate ref never has to
   merge into the adopter.
5. When the checklist passes, the owner promotes the same commit: an exact tag `v1.MINOR.PATCH`
   that never moves, and `v1` moved onto it. The adopter's caller returns to `v1` before its
   pull request merges. When the checklist fails, nothing is promoted: the fix lands on `main`
   through its own record and a new candidate is cut.
6. Exact tags: the first release is `v1.0.0`. PATCH rises for a fix that changes no rule;
   MINOR rises for anything else a caller written for `v1` still works with. A release that
   needs an edit in the caller (a new permission, a new trigger, a renamed job) is not a `v1`
   release: it is `v2`, with its own candidates `v2-rcN`, and `v1` stays where it was.
7. A rollback moves `v1` back to the previous exact tag. Exact tags and candidates stay.
8. No staging branch. A branch between `main` and the release would need a second pull
   request and a second merge for every change, and every check would run twice, billed by
   the minute in a private adopter; it would also be a second protected branch for the owner
   to keep. A tag costs no run and no merge.
9. Tags stay the owner's step: a cloud session cannot push a tag, and no workflow creates
   one.

## What "behaves as on Conductor" means

One pull request in the adopter, whose branch changes the caller's ref to the candidate.
All three must hold on it:

1. The check reports under the name `linked-task / linked-task`.
2. With no task named in the pull request body, the check fails and its log has exactly one
   `::error::` line.
3. After the body is edited to close a task that is Ready (`Closes #n`; the edit triggers
   the check again), the check passes.

Two pushes at most: the candidate ref, then `v1` after the promotion.

## Owner commands

Run in a clone of this repository. `SHA` is the 40-character `main` commit to release.

Candidate:

```sh
git fetch origin main
git tag v1-rc1 SHA
git push origin v1-rc1
```

Promotion, after the checklist passed on that candidate:

```sh
git tag v1.0.0 SHA
git tag -f v1 SHA
git push origin v1.0.0
git push --force origin refs/tags/v1
```

The first promotion creates `v1`, so `-f` and `--force` do nothing then; from the second
release on they move the tag. `--force` here touches one tag and no branch.

Rollback, `v1.0.0` standing for the previous release:

```sh
git tag -f v1 'v1.0.0^{commit}'
git push --force origin refs/tags/v1
```

Before the second release there is no previous one to return to: the first release is
repaired by a new candidate and a new promotion.

The first release: `v1-rc1`, then `v1.0.0` and `v1`, all on
`79613a7f9cc6e866ecd8e8c443397a8e3cdfae37`, the merge commit of #128.

## Not known

- A reusable workflow called at a tag: `unknown`, as in ADR 0010 finding (b); no tag existed
  when this was written. GitHub's documentation treats a tag, a branch and a SHA alike and
  puts no limit on a hyphen in the name. The first candidate answers it.
- Whether a moved tag is resolved fresh on the next run or from a cache: `unknown`. The first
  release cannot show it, because `v1` is created there, not moved; the second release does.
  Check the commit the adopter's run resolved `v1` to after that move.
- If either fails, stop: no promotion, and the evidence goes to #152 or a new record.

## Consequences

- An adopter on `@v1` gets each release on its next pull request event, after one adopter
  has run it. An adopter that wants no change without its own pull request pins an exact tag
  or a SHA.
- A release costs the owner two visits to a terminal and one pull request in the test
  adopter.
- The test adopter carries the risk of each candidate, on one pull request and not on its
  default branch.
- A fault the checklist does not cover still reaches every `@v1` adopter; the rollback is one
  tag move.
