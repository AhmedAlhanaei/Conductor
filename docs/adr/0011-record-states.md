# ADR 0011: The states of a record are read from GitHub, and the Implementer moves none

- Status: Accepted (owner decisions of 2026-11-21 in the claude.ai project chat, recorded on
  #124: the state model, 17:55 to 19:54 UTC, ending "Yes to all. What is next"; "Yes to all"
  to thirteen decisions at 20:42 UTC; "Ready 124" at 20:52 UTC; "Yes" to the ten decisions
  of the conflict review at 21:05 UTC)
- Date: 2026-11-21
- Deciders: repository owner
- Task record: #125 (slice 1 of #124, the top-level record)
- Amends: ADR 0003 (File is no longer a gate; the owner's decisions are Ready, Merge and
  Reject; the status list), ADR 0005 (who moves what in each mode), ADR 0006 (a third skill),
  ADR 0007 (how a review is recorded and when one is required), ADR 0008 (the thresholds
  also decide when a review is required), ADR 0009 (`agent:grok`; which pull requests Grok
  reviews) and ADR 0010 (the caller's trigger; the first tag)
- Roles: decision grilled by the Planner (project threads "Find better status tracking" and
  "Check open issues for conflicts"); this record written by the Implementer (a project
  thread)

## Context

The page gave a record five statuses: Backlog, Ready, In progress (claimed), Review and Done.
Two of them were read from GitHub (the `status:ready` label, the merge). The other three were
read from comments a session writes: the claim, the milestone, the release. A comment is not
a fact GitHub holds: it can be missing, late or wrong, and the session that does the work
was also the one reporting where the work stood. Closed records did not say whether the work
was done or dropped. File was an owner gate, so an idea could not become an issue without
the owner, and the Backlog issue (#66) grew into a second queue.

Read on 2026-11-21 at `main` 3414d0a (the evidence is in the first comment of #124):
`GET /repos/{owner}/{repo}/issues` returns `state_reason` and `sub_issues_summary`; check
runs are readable by name per commit; the `status:` search does not see Actions checks; all
50 merged pull requests had no native review.

## Terms

"State" is the word for where a record stands in its lifecycle, and the only word this
record and the page use for it. "Status" survives in one place, the name of the label
`status:ready`. GitHub's own issue state, open or closed with a close reason, is one of the
facts a state is read from, not a state. The owner asked on 2026-11-21 whether the two words
mean the same; the wording here follows the Planner's recommendation and is not an owner
decision.

## Decision

### The states

A state names the work the record is waiting for (Ready is the one name that does not).
A leaf record is in Triage, Ready, Implement, Review, Rework or Merge, then Done or
Rejected. A parent, any record with sub-issues, is in Triage, Ready, Implement or Review,
then Done or Rejected. Blocked and "review pending" after a merge are flags or conditions
beside a state, never states.

The state is defined by one ordered rule over facts GitHub holds; the first match wins, so a
record is in exactly one state. Nobody writes a state, and no label, board or workflow moves
one.

Leaf: closed as completed is Done; closed as not planned or duplicate is Rejected; an open
pull request that closes it with every required check green on the head is Merge; with
`verify` red on the head, or the newest review of the head requesting changes, is Rework, as
is a record reopened after a revert (open, with a merged pull request and no open one); any
other open pull request is Review; open, `status:ready` and assigned is Implement; open and
`status:ready` is Ready; open is Triage.

Parent: Done and Rejected as a leaf; open with every sub-issue closed is Review; open with a
sub-issue open is Implement; otherwise as a leaf.

### Who moves a state

Never the Implementer. It keeps the work: one branch, one pull request, arming auto-merge,
fixes, and one handoff comment only when it stops without a pull request.

| Move | The act on GitHub | Who |
| --- | --- | --- |
| into Triage | open an issue | anyone |
| Triage to Ready | apply `status:ready` with a comment naming the approval | the owner in `manual`, on a top-level record, above the assistant priority cap and in an owner-only category; the Planner for any other sub-issue in `auto`; `grok-conductor[bot]` for that sub-issue in `grok` |
| Ready to Implement | assign the issue | the Planner, when it starts the thread; in `manual` after the owner agrees to the thread |
| Implement to Review | the pull request opens | GitHub |
| Review to Rework | a review requesting changes, or a red `verify` | the Reviewer, or GitHub |
| Rework to Review | a push | GitHub |
| Review to Merge | every required check green on the head | GitHub, after the Reviewer's native review where one is required |
| Merge to Done | the merge | GitHub auto-merge for a sub-issue in `auto`; the owner otherwise and on promotion |
| Done to Rework | reopen after a revert | the owner; the Planner too in `auto` |
| any state to Rejected | close as not planned or duplicate, with the reason | the owner |
| parent Implement to Review | the last sub-issue closes | GitHub |
| parent Review to Implement | a finding is filed as a new sub-issue | the Planner files; Ready as for any sub-issue |
| parent Review to Done | the closing report, then close | the Planner in `auto`, the owner in `manual` |

Priority and kind enter through the two thresholds of ADR 0008: above the cap, or in an
owner-only category, the Ready is the owner's and a review is required.

### The owner's three decisions

Ready and Merge are gates. Reject is the owner's decision, reachable from any state and
recorded by closing the record as not planned or duplicate with the reason. File is not a
gate: anyone may file, and every issue starts in Triage. The Backlog issue stays as an
optional notebook of one-line ideas; it is not a state and not a queue. A parent with at
least one finished child closes as Done and its unfinished children are Rejected.

A session applies `status:ready` to a top-level record only on the owner's own message
naming that record, with a comment naming the message; never on its own judgment. The
Ready comment on #124 quotes the owner's rule of 2026-11-20, "we are supposed to be able to
ready issues from chat"; the page forbade it in its Never list until this record.

A parent never has a pull request of its own. Its own work is filed as a sub-issue. The
sentence that gave a record with sub-issues a `Refs #n` pull request is removed; the
record-only `Refs #n` path of `linked-task` for `docs/adr/` is unchanged.

### The thirteen decisions

As accepted on 2026-11-21 20:42 UTC and listed in the first comment of #124:

1. A state is defined by an ordered rule over REST reads of GitHub facts; searches are
   shortcuts for the queues a search can answer.
2. A parent's Review is done by a Reviewer on another runtime when the parent carries
   `review:required`, and by the Planner otherwise.
3. Blocked is the existing `blocked:owner` label only, as a flag beside the priority, with a
   comment saying what is awaited. Native "blocked by" links wait.
4. After a revert, the Planner may reopen the record in `auto`.
5. #124 is filed at P2 with `review:required`, with four slices.
6. The Never item on approving a pull request "as a merge authorization" is reworded: a
   Reviewer's native review of a head is allowed; approving in place of the owner's Merge
   gate is not.
7. `kind` stays one axis and means the type of work; `kind:security` wins any tie; areas
   are each adopting project's own `area:*` labels, which Conductor ignores.
8. `agent:*` stays and means "who may implement", read once when work starts. `agent:grok`
   becomes unused.
9. `linked-task` computes the review requirement from the record; `review:required` only
   adds the requirement elsewhere. As accepted: P0, P1 and owner-only categories. As
   amended at 21:05 UTC: above the assistant priority cap or in an owner-only category, in
   both approval modes.
10. The issue form requires only a title, a problem and a parent at filing. Every other
    Ready fact is required before Ready.
11. The form gains one optional field, "Success criteria (parent only)".
12. `linked-task` does not check the fields of an issue body.
13. P2 and P3 records without `review:required` may merge unread; the weekly backlog review
    lists the merged pull requests still unreviewed. Review on everything was offered and
    not taken.

### What this record changes in earlier records

Their decided text is not rewritten; each carries an "Amended by: ADR 0011" line.

- ADR 0003: File is no longer a human gate. The owner's three decisions are Ready, Merge
  and Reject. The status list and the single backlog queue give way to the states above and
  to the Backlog issue as an optional notebook.
- ADR 0005: the table of who does what in each mode is replaced by "Who moves a state"
  above. Filing leaves it; the Planner's assignment of the issue enters it; the Planner may
  reopen after a revert in `auto`.
- ADR 0006: a third skill, `record-review`, joins `task-start` and `task-finish` (#127).
- ADR 0007: the review of a head is recorded as a native GitHub review of that head instead
  of a line in the pull request body, and `linked-task` computes when one is required
  (#126). The Reviewer on another runtime stands.
- ADR 0008: the assistant priority cap and the owner-only categories also decide when a
  review is required, not only whose Ready a sub-issue needs.
- ADR 0009: `agent:grok` is unused, since `agent:*` now means who may implement and Grok
  never implements. Grok reviews the pull requests in Review that have no review of the
  head, not those whose checks are green.
- ADR 0010: an adopter's caller also runs on a submitted review (`pull_request_review`).
  No tag is created before #128 merges; the first tag, `v1`, is on that head.

## Open, not decided

Whether a review counts only when it comes from a login other than the pull request
author's. Every Claude session acts as the owner's login, so under the strict reading Claude
could review no pull request opened under that account, and under the loose reading the
check cannot tell a Claude Reviewer from the Claude Implementer. The owner decides after one
bot review of a head has been shown on a live pull request. Until then #126 criterion 3
stands as written.

Not tested, so `unknown`: whether a native review can be submitted on a merged pull request;
whether `grok-conductor[bot]` may submit a review or be a requested reviewer; which of two
`linked-task` results on one head the required check honours when they come from different
events; whether the `review:none` search drops a pull request after a comment-only review.

## Alternatives considered

- A GitHub Projects board, status labels moved by a workflow, draft pull requests as a
  state, and native "blocked by" links. Not taken: they are the non-goals of #124, which
  asks for no new label and no new workflow.
- Review on every record. Offered to the owner and not taken (decision 13).

## Consequences

- With this record (#125): this file; the seven "Amended by" lines; `AGENTS.md` states the
  rule, who moves each state, the two gates and Reject, the flags, `kind` and `agent:*`;
  `README.md` agrees.
- The page is ahead of the checks and the skills until the other slices merge. Still as
  before, by design of the split: the `Reviewer: ..., reviewed SHA: ...` line in the pull
  request body and the label-only review requirement (#126); the claim, milestone and
  release comments and the opening sentence of Roles (#127); the form that requires every
  Ready fact, `blocked:owner` in place of a priority in the first sentence of Task records,
  the closing report wording, and the weekly list of unreviewed merges, which
  `backlog-review.yml` does not produce yet (#128).
- Until the Planner assigns issues, a record being worked on without a pull request reads
  Ready, not Implement.
- A record with an open sub-issue reads Implement whether or not it carries `status:ready`.
- The Backlog issue, being an open issue without `status:ready`, reads Triage under the
  rule although it is not a record.
- `docs/lifecycle.md` says the model is not in force; that line is stale from this merge.
- Owner steps, after #128 and not before: tag `v1`; save the changed skills to the account;
  paste the page into the project instructions once.
- Unchanged: the two approval modes and `grok`, the thresholds, branch protection, the two
  required checks, the labels (none added) and the workflows (none added).

## Rollback

Restore `AGENTS.md` and `README.md` from the commit before this one, delete this record and
remove the seven "Amended by: ADR 0011" lines. No setting, label, variable or workflow was
changed, so nothing else needs undoing.

## Source

#124 with its first comment (the thirteen decisions, the ordered rule, the evidence) and its
conflict-review comment (the ten decisions of 21:05 UTC); #125 and its amendment comment.
The owner's messages were given in the claude.ai project chat and are quoted on those
records; this record was written from the records, not from the chat.
