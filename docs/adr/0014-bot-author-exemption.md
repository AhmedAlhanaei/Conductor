# ADR 0014: An opt-in list of bot authors whose pull requests need no task

- Status: Accepted (the owner's "Yes to all. Ready 167", 2026-11-28 19:35:38 UTC in the
  claude.ai project chat, to the six decisions of the #167 round; decision 3 is this record,
  decision 4 its priority and `review:required`; both recorded in a comment on #167). In
  force in a repository only once its owner sets `CONDUCTOR_BOT_AUTHORS`; no repository has
  set it when this record lands
- Date: 2026-11-28
- Deciders: repository owner
- Task record: #169 (a slice of #167, the top-level record)
- Amends: nothing. It adds one named exception to the page's rule that every change starts
  from a record, and leaves ADR 0003 (gates), ADR 0005 (modes), ADR 0008 (thresholds) and
  ADR 0011 (states, native reviews) as they are
- Release: MINOR under ADR 0012, `v1.1.0`. The `workflow_call` interface and the permissions
  a caller grants are unchanged, so a caller written for `v1` needs no edit
- Roles: decision grilled by the Planner (project thread "Unblock merges across Conductor
  repos"); this record written by the Implementer (a project thread)

## Context

`linked-task` refuses a pull request that closes no task. A Dependabot pull request closes
none, so every one of them is red, and under a ruleset that requires `linked-task` none can
merge. Media-Studio had 15 open on 2026-11-28. The page says a red bot pull request is fixed
or closed at the backlog review, but gave it no way to turn green short of the owner filing
and readying a task for each dependency bump.

Facts read on 2026-11-28, for this record:

- The pull request's author and account type are in the event payload
  (`pull_request.user.login`, `pull_request.user.type`). Dependabot's are `dependabot[bot]`
  and `Bot`. Nothing a person writes in a title, body or branch name changes them.
- A commit's author is not such a fact. GitHub shows as author whichever account matches the
  email written into the commit, and anyone who can push to the bot's branch can write the
  bot's email there. An author check alone would let a person add a commit to a bot's pull
  request and keep the exemption.
- Dependabot's own commits carry more than the author. Read on Media-Studio commit
  `431cb402d67d` (pull request 1318): author `dependabot[bot]`, committer GitHub's
  `web-flow`, and a PGP signature in the commit object, which GitHub reports as a verified
  signature. A person cannot produce that combination: a commit they sign is verified
  against their own account as committer, and a commit that names `web-flow` or the bot as
  committer without GitHub's signature is unverified.
- The commits of a pull request are listed by `GET /repos/{repo}/pulls/{n}/commits`, which
  needs `pull-requests: read`, a permission every `v1` caller already grants. The list holds
  at most 250 commits.
- Whether a run that Dependabot itself triggers sees repository and organization variables
  is not stated in GitHub's documentation. A GitHub staff comment of 2023-03-13 on community
  discussion 44088 says it does. Not shown live for this record: `unknown` until the first
  Dependabot run in a repository that sets the variable. If such a run saw no variables, the
  check would fail as it does today, never pass by default.

## Decision

1. A new variable, `CONDUCTOR_BOT_AUTHORS`: comma-separated logins, compared without regard
   to case. Unset or empty, nothing changes and no commit list is read.
2. A pull request is exempt from the task requirement when all of these hold:
   - its author's login, from the event, is in the list;
   - its author's account type, from the event, is `Bot`. A person's login in the list
     exempts nothing;
   - every commit on the pull request has that bot as its author (an account of type `Bot`),
     that bot or `web-flow` as its committer, and a signature GitHub verified;
   - the commit list was read, holds between 1 and 249 commits and ends at the head.
3. When any of these fails for a listed author, the check prints one line saying why the
   exemption was not applied and goes on to the usual rules. A mixed pull request that names
   a Ready task therefore passes as any other; one that names none fails as today.
4. When the exemption applies, the check prints one line naming it and passes. It reads no
   task, no review and no timeline. The rules that come before it still apply: the base
   branch in `auto` and one head, one pull request.
5. `verify` is untouched and still required. The exemption says only that no record is
   needed, not that the change is good.
6. An exempt pull request is never merged or armed for auto-merge by a session, in `manual`
   and in `auto` alike: its merge is the owner's click. No record carries an owner's Ready
   for it, so the Merge gate is the only decision the owner takes on it, and it stays his.
   This is a rule of the page, held by trust: GitHub does not stop a session from arming
   auto-merge.
7. The exemption follows commits, so it ends when a person adds one, also through the
   "Update branch" button, which commits a merge in the person's name. The owner asks the
   bot to rebase instead (`@dependabot rebase`).

## Alternative rejected: auto-filed tasks

A workflow, or the bot, files a task for each bot pull request and the pull request closes
it. Rejected by the owner (#167, decision 3):

- The task would need `status:ready`. In `manual` the check accepts that label only from
  the owner, so a bot's or a workflow's Ready is refused and the owner is back to readying
  one issue per dependency bump by hand.
- In `auto` a workflow readying its own top-level records is exactly what the Ready gate
  exists to prevent.
- Each bump would leave a record with no problem statement and no acceptance criteria, which
  is noise in the task list and in the weekly review.
- It needs a write permission on issues that the checker does not have and a `v1` caller
  does not grant.

Also not taken: matching on the branch name (`dependabot/...`), which anyone can create, and
trusting `github.actor`, which names whoever caused the latest event, not who wrote the
commits.

## Not decided here

- Which repository sets the variable, and to which bots. That is each owner's step, after
  the release.
- A bot whose commits are not signed by GitHub, such as one that pushes with plain git, is
  not exempt even when listed. Making it so would need another proof that the commit is the
  bot's own; none is proposed.
- Auto-merge of bot pull requests, at any risk level. Out of scope by the record's non-goals.
- Whether exempt pull requests should appear in the weekly list of merges nobody reviewed.

## Consequences

- An owner who lists `dependabot[bot]` sees its pull requests go green on `linked-task` and
  merges the ones `verify` passes. One who does not sees no change.
- The exemption is a hole in "every change starts from a record", bounded by the list, by
  the account type and by the signature on every commit. What a listed bot may change is
  whatever that bot is configured to change; listing a bot is trusting its configuration.
- A person with push access can end the exemption on a bot's pull request, by pushing a
  commit, but cannot gain it for a commit of their own.
- The first live run on a Dependabot pull request, in the first repository that sets the
  variable, is the evidence for the variables question above and for the signature reading
  through the API; until then both rest on the reading recorded in Context and on the tests,
  which run the checker against faked answers.
- Release: `v1.1-rc1` tested on an adopter, then `v1.1.0` and `v1` moved, by the owner
  (ADR 0012).
