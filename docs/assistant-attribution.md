# Assistant attribution on GitHub

How an assistant's contribution to a Conductor issue, pull request, review or state change is
recorded. The rule is in [`AGENTS.md`](../AGENTS.md), "Identity and attribution"; this file is
the procedure, and it is the same from a phone, a desktop or a coding session. What an
assistant repeats to get and prove its own App identity is in
[`assistant-identity-handoff.md`](assistant-identity-handoff.md). Record: #137.

## Three separate facts

| Fact | Question | Evidence |
| --- | --- | --- |
| Role | What is this session doing on this record? | The record, the Planner's assignment of the issue, the pull request's Implementer line |
| Authority | Who allowed this act? | The owner's own message, the approval mode, the record's scope |
| Actor | Which account did GitHub record? | The author of the object, or the actor and App on the timeline event |

An assignment, a mention and access to an account each answer a different question. None of
them stands in for another.

## What each assistant can do, as of 2026-11-28

"Demonstrated" means a live GitHub object exists whose author or actor is the App, and the
link is given. "Pending" means allowed or planned but not shown live: treat it as unavailable
until its record closes. `unknown` means no record says.

| Assistant | Own identity | Demonstrated | Pending or not available |
| --- | --- | --- | --- |
| Codex | `codex-conductor[bot]`, key held in Actions | Issue comments through `codex-planner-comment.yml` (#132, #134; for example [this comment on #136](https://github.com/AhmedAlhanaei/Conductor/issues/136#issuecomment-7084992687)) | Issue creation and label changes: pending #136. `status:ready` on a sub-issue: not decided, no record. Reviews: no record |
| Grok | `grok-conductor[bot]`, installation token held in Grok's environment | A native review that `linked-task` counted ([pull request 145](https://github.com/AhmedAlhanaei/Conductor/pull/145#pullrequestreview-6027591238), #143) and a request for changes that turned it red ([pull request 150](https://github.com/AhmedAlhanaei/Conductor/pull/150#pullrequestreview-6098896961), #149) | `status:ready` as the bot: allowed in `grok` mode by ADR 0009, no live example recorded. Any push, branch or pull request: never (ADR 0009) |
| Claude | `claude-conductor[bot]`, key held in Actions; a cloud session cannot hold it | One fixed issue comment through `claude-identity.yml` ([comment on #139](https://github.com/AhmedAlhanaei/Conductor/issues/139#issuecomment-7242989176)) | Issue creation, labels, sub-issue link, `status:ready`: pending #146 and #147. Reviews and pull requests as the App: no record. Every write from a Claude session is recorded as the login it works under, type User, no App marker |
| Gemini | none | `unknown` | `unknown` |

A record that moves a row from pending to demonstrated edits this table in its own pull
request and gives the link.

## Before writing

1. Read the record and its newest handoff. Name the acting assistant, its role, the target and
   the authority for the act. Check the owner gates in `AGENTS.md`.
2. If the actor matters, use the actor that holds the act, or hand off to it:
   - Ready on a top-level record, above the assistant priority cap or in an owner-only
     category: the owner, or a session on the owner's own message naming the record.
   - Any Grok Ready or review: `grok-conductor[bot]` (ADR 0009).
   - A required review: a Reviewer on a runtime other than the Implementer's, as a native
     GitHub review of the head (ADR 0011).
   - A write this file lists as pending for your App: not through the App yet. Use the
     owner-account route if the act is ordinary; otherwise stop and ask.
3. Otherwise the work is ordinary and may go through another account, usually the owner's.
   Put the credit in the text being submitted: the assistant, what it actually did, the
   submitting account. For a label or another write without a text field, put the credit in
   the record's next comment and link the affected item.

| Situation | Text |
| --- | --- |
| Codex planned an issue that is filed through the owner's account | "Prepared by Codex as Planner. Filed through `alhanaei`." |
| Claude implemented a change | "Claude implemented the change. Pull request opened through `alhanaei`." |
| A session readies a record on the owner's message | "Ready on the owner's message of <date, place>: '<quote>'. Label applied by Claude through `alhanaei`." |
| The App publishes a Codex Planner comment | Nothing to add: the comment names the App, the requester, the request ID and the run |

A credit records contribution. It cannot satisfy a check on the authenticated actor, establish
an independent review, or prove which model composed a text. Credit only the assistant that
did the work. Name a bot in code style (`codex-conductor[bot]`), not as an `@mention`:
whether a mention resolves to the App is `unknown`.

## Three walk-throughs

**An owner-account write.** Claude, Implementer of #137, opens its pull request from a cloud
session. Role: the record is Ready and labelled `agent:claude`. Authority: the owner's "start
137" and the record's allowed paths. Actor: GitHub will record `alhanaei`, because the session
works under that login. Route: owner-account. The pull request body therefore carries
"Implementer runtime: Claude Code" and the credit line. Finish check: the author is `alhanaei`
and the credit is in the body. Nothing more is claimed: the event does not show that the owner
opened it.

**A verified bot comment.** Codex, as Planner, has a round of questions for #124. Role and
authority: Planner comments on existing records need no approval. Actor: it matters, since
the comment should read as Codex's, and the App has been shown to make this write. Route: App.
Codex dispatches `codex-planner-comment.yml` with the issue, a request ID and the message
(`docs/codex-planner-comments.md`). Finish check: the run summary's permalink shows the author
`codex-conductor[bot]`, type Bot. The "requested by" login is whoever dispatched, which for an
assistant on the owner's connector is the owner's login.

**A restricted action: Grok's review.** A pull request closes a `review:required` record
implemented by Claude. Role: Grok is Reviewer. Authority: ADR 0009 and the record. Actor: it
is the whole point, because `linked-task` reads the review's author. Route: App only. Grok
submits a native review of the head with the `grok-conductor` installation token. Finish
check: the review's author is `grok-conductor[bot]`, type Bot, and its commit is the head. If
Grok can only reach GitHub through a connector that acts as the owner, it does not submit:
a review from the author's login counts only when it starts `Reviewer: <runtime>`, and that
the Reviewer is another runtime is then trust only. It hands the review to a session that can
use the App and says so. A credit line does not turn an owner-login review into Grok's.

## Finish check

Before reporting success, compare each write with the route chosen:

- Owner-account write: the issue, pull request or comment contains the credit.
- App write: the object's author, or the actor and App of the timeline event for that exact
  change, is the App.
- A credit missing from a text: correct that text.
- A wrong actor on a gate, a review or an App-only write: keep the evidence and report it to
  the owner. Do not repeat the write to change how its history looks; that duplicates work.

## What is enforced

- The Codex comment and Claude identity workflows check the caller and the App author at run
  time and fail on a mismatch.
- `linked-task` reads the actor of `status:ready` in `manual`, above the priority cap and in
  owner-only categories, and compares it with `CONDUCTOR_OWNER_LOGIN`. It reads the author of
  a required review and counts an owner, member, collaborator or bot.
- Everything else here is procedure, and trust only. No check can tell whether an assistant
  helped with a write made under the owner's login, and a mandatory mention would also flag
  human-only work.

## Known limits

- An event by `alhanaei` does not show whether the owner or a session acted. The owner's
  decisions are evidenced by the owner's message that the record's comment names.
- A review by Claude of a pull request opened under the same login cannot be verified as
  independent; it counts on its first line alone (ADR 0011).
- The "owner only" caller check of the App workflows passes for any session that works under
  the owner's login, so a bot author proves the App made the write, not who decided it.
