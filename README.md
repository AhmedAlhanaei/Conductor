# Conductor

Conductor is one page of rules and two GitHub checks for projects where coding assistants
(Claude Code, Codex, Cursor, Gemini CLI, Grok) do the work and one human owner keeps three
decisions: what is ready to build, what lands on the default branch, and what is rejected.
Every assistant reads the same page, [`AGENTS.md`](AGENTS.md); GitHub enforces it through
branch protection and two required checks. Nothing is generated, pinned or copied, and there
is no application runtime: this repository is documentation, workflows, templates and skills.

It is for a solo owner or a small team who want several assistants to work the same backlog
without a merge they did not decide, a task nobody filed, or a check nobody ran.

The states a record passes through, what each waits for and who moves it are in one file,
[`docs/lifecycle.md`](docs/lifecycle.md), a reference for the model the page states since
[ADR 0011](docs/adr/0011-record-states.md). The page governs; that file's status block and
its "What is live today" table were written before ADR 0011 and are behind on that point.

## How it works

**Task records.** Every change starts from a GitHub issue filed from the
[task form](.github/ISSUE_TEMPLATE/task.yml), which requires only a title, the problem and
the parent task. Before Ready the record carries one priority (`P0` to `P3`), one category
(`kind:*`) and the Ready facts: bounded outcome, acceptance criteria with the test for each,
non-goals, allowed paths, budget and stop conditions. A plan agreed in chat is not a record
([Task records](AGENTS.md#task-records)).

**Two owner gates, and Reject.** Ready (the `status:ready` label, with a comment naming the
approving message) and Merge (the pull request lands) are gates; Reject (a record closed as
not planned or duplicate, with the reason) is the owner's third decision. Filing is open to
anyone: every issue starts in Triage. Approval comes only from the owner's own words; an
assistant's message is evidence, not permission ([Owner gates](AGENTS.md#owner-gates),
[ADR 0003](docs/adr/0003-backlog-gates-and-roles.md)).

**Eight states, read from GitHub.** A record is in Triage, Ready, Implement, Review, Rework
or Merge, then Done or Rejected; a record with sub-issues is in Triage, Ready, Implement or
Review, then Done or Rejected. The state is read from labels, assignee, pull request, checks,
reviews and the close reason by one ordered rule; nobody writes it, and the Implementer moves
none ([Task records](AGENTS.md#task-records), [ADR 0011](docs/adr/0011-record-states.md)).

**Two approval modes.** In `manual` every gate is the owner's. In `auto` the owner's
Ready on a top-level record reaches its sub-issues: the Planner files and readies them, and
GitHub squash-merges a green pull request by itself. Two thresholds hold the Ready back in
`auto`: a priority cap and owner-only categories, above which the owner readies
([ADR 0005](docs/adr/0005-approval-modes.md), [ADR 0008](docs/adr/0008-thresholds-in-auto.md)).

**Four roles.** Owner (human), Planner (the project coordinator: files, grills and splits
records, never pushes), Implementer (one thread, one task, one branch, one pull request) and
Reviewer (a separate thread on a different runtime, advisory unless the record carries
`review:required`). A session holds one role at a time and declares it in its claim comment
([Roles](AGENTS.md#roles), [ADR 0007](docs/adr/0007-review-gate.md),
[ADR 0009](docs/adr/0009-grok-mode.md)).

**Two checks.** `linked-task` ([`pr-policy.yml`](.github/workflows/pr-policy.yml)) refuses a
pull request unless it closes exactly one open task that is Ready, carries one priority and
one category, and, in `auto`, was readied by the right identity; it also keeps one head to one
pull request. `verify` ([`ci.yml`](.github/workflows/ci.yml)) runs the
[verification contract](AGENTS.md#verification-contract). Both are required on the default
branch, so the rules hold even when a session ignores the page.

**Three skills.** [`task-start`](skills/task-start/SKILL.md) turns a Ready record into a
branch with a recorded baseline; [`task-finish`](skills/task-finish/SKILL.md) runs the
contract on the exact head, opens one pull request from the
[template](.github/pull_request_template.md) with the evidence ledger and arms auto-merge in
`auto`. Neither writes a claim, a milestone, a label or an assignment; a session that stops
without a pull request posts one handoff comment. Both check the role, the authority and the
account GitHub records for a write. [`record-review`](skills/record-review/SKILL.md)
is the Reviewer's: one native review of a pull request's head against its record
([Task start](AGENTS.md#task-start), [Task finish](AGENTS.md#task-finish),
[Never](AGENTS.md#never)).

**Identity and attribution.** GitHub records the account that made a write, not the assistant
that composed it. An assistant uses its own GitHub App where the actor matters and the App has
been shown to make that write; ordinary work may go through the owner's account with a credit
in the text, which satisfies no gate and no review
([Identity and attribution](AGENTS.md#identity-and-attribution),
[`docs/assistant-attribution.md`](docs/assistant-attribution.md),
[`docs/assistant-identity-handoff.md`](docs/assistant-identity-handoff.md)).

## Try it

1. Create the repository from this one with GitHub's **Use this template**.
2. Edit the first section of `AGENTS.md` to the project's facts, and its verification
   contract to the project's own commands.
   Replace the copied `.github/workflows/pr-policy.yml` with this caller, so the project
   always runs the released checker ([ADR 0010](docs/adr/0010-reusable-workflows.md)); keep
   the copied `ci.yml` and replace its rows:

   ```yaml
   name: PR policy
   on:
     pull_request:
       types: [opened, edited, synchronize, reopened]
     pull_request_review:
       types: [submitted, dismissed, edited]
   permissions:
     actions: write
     contents: read
     issues: read
     pull-requests: read
   jobs:
     linked-task:
       uses: AhmedAlhanaei/Conductor/.github/workflows/pr-policy.yml@v1
   ```

   `actions: write` is for one call: when a review is submitted, dismissed or edited on a
   task that requires one, the check re-runs its own run of the `pull_request` event on that
   head, which is the run the merge follows. Without it a review is read but someone must re-run the check.
   The ref after `@` is a tag or a commit SHA, never `main` or another branch: `main` is
   where changes are staged. `v1` moves to a release only after a release candidate tag
   passed on one adopter; an exact tag such as `v1.0.0`, or a SHA, never moves
   ([ADR 0012](docs/adr/0012-release-step.md)).
3. In GitHub, repository Settings, Secrets and variables, Actions, Variables: set
   `CONDUCTOR_APPROVAL_MODE` to `manual` or `auto`, and `CONDUCTOR_BACKLOG_REVIEW_ISSUE` to
   the pinned backlog issue if you use the weekly report. `CONDUCTOR_REVIEW_REQUIRED_LABEL`
   renames the label that adds the review requirement to a task (default `review:required`,
   ADR 0007); leave it unset to keep the default.
   In `auto`, `CONDUCTOR_ASSISTANT_PRIORITY_CAP` (default unset: no cap) is the highest
   priority an assistant may ready, `CONDUCTOR_OWNER_CATEGORIES` (default unset: none) lists
   the categories only the owner readies, and `CONDUCTOR_OWNER_LOGIN` (default the repository
   owner) is the login whose `status:ready` counts as the owner's; `linked-task` then holds a
   pull request whose task is above the cap or in the list until the owner has readied it
   (ADR 0008). In both modes the same two variables decide when a review is required: such a
   task holds the merge until its head has a GitHub review that does not request changes,
   with or without the label (ADR 0011). Conductor itself sets `P2` and `kind:security`.
4. In GitHub, repository Settings, Branches: protect the default branch with a required
   pull request, "Do not allow bypassing" on, approvals off, required checks `verify` and
   `linked-task / linked-task` (the name the caller in step 2 reports under; only Conductor
   itself, which runs the workflow directly, requires the bare `linked-task`). In Settings,
   General, Pull Requests: tick **Allow auto-merge** for `auto`.
5. Create the labels the policy uses: priorities `P0` to `P3`, `blocked:owner`, categories
   `kind:*`, `kind:tracking`, `status:ready`, and optionally `agent:claude`, `agent:codex`,
   `agent:gemini`.
6. Paste `AGENTS.md` into the assistant's project instructions where it has them, and enable
   the three skills on the account.

A policy change is one commit to `AGENTS.md`; `git log -1 -- AGENTS.md` names the revision an
assistant read.

## Adopt into an existing repository

For a repository that already has code, history and its own CI. It is a checklist: nothing is
generated, and every step is a file in one pull request or a GitHub setting. `OWNER/REPO` is
the adopting repository and `ORG` its organization, if it has one. Steps 2 to 4 are the
owner's, in the browser.

1. **Get the core files**, in one pull request in the adopting repository
   (`https://github.com/OWNER/REPO/pulls`). Copy `AGENTS.md`, `CLAUDE.md`,
   `.github/ISSUE_TEMPLATE/task.yml` and `.github/pull_request_template.md`. Do not copy
   `pr-policy.yml`: add the caller from step 2 of [Try it](#try-it), which runs the checker
   at the tag `v1`, never at `main` ([ADR 0010](docs/adr/0010-reusable-workflows.md),
   [ADR 0012](docs/adr/0012-release-step.md)). Keep the repository's
   own CI and give it one job named `verify` that runs its verification contract, with the
   cost defaults from the header of [`ci.yml`](.github/workflows/ci.yml); copy `ci.yml` and
   replace its rows only when there is no CI yet. `backlog-review.yml` is optional. In the
   same pull request, edit the first section of `AGENTS.md`, "What this project is", to the
   project's facts, and the table under "Verification contract" to its own commands. This is
   the last pull request merged without the checks.
2. **Create the labels** in GitHub, repository Issues, Labels
   (`https://github.com/OWNER/REPO/labels`): `P0` to `P3`, `blocked:owner`, one `kind:*`
   per category (`kind:feature`, `kind:bug`, `kind:docs`, `kind:chore`, `kind:security`
   and so on), `kind:tracking`, `status:ready`, `review:required`, and optionally the
   `agent:*` labels.
3. **Set the variables** in GitHub, repository Settings, Secrets and variables, Actions,
   Variables tab (`https://github.com/OWNER/REPO/settings/variables/actions`); step 3 of
   [Try it](#try-it) says what each one does. In an organization the `CONDUCTOR_*` variables
   may instead be set once at organization scope
   (`https://github.com/organizations/ORG/settings/variables/actions`) and are inherited by
   every repository the variable is shared with; a repository variable of the same name
   overrides it. Label names, the priority cap, the owner-only categories and the owner's
   login suit the organization; `CONDUCTOR_APPROVAL_MODE` and
   `CONDUCTOR_BACKLOG_REVIEW_ISSUE` belong to each repository. A repository owned by an
   organization sets `CONDUCTOR_OWNER_LOGIN` to the owner's own login: unset, it falls back
   to the organization's name, which never applies a label, so every task above a threshold
   is refused. Climb the approval modes as a ladder, one rung at a time:
   1. `CONDUCTOR_APPROVAL_MODE=manual` (or unset): every gate is the owner's.
   2. `auto` with `CONDUCTOR_ASSISTANT_PRIORITY_CAP=P3`: green pull requests merge by
      themselves, and the owner still readies every sub-issue above `P3`.
   3. The cap raised to `P2`, then further, as the merged pull requests earn it.
4. **Protect the default branch** once the pull request of step 1 has merged and both checks
   have reported on it (GitHub only offers checks it has seen). In GitHub, repository
   Settings, Branches (`https://github.com/OWNER/REPO/settings/branches`): require a pull
   request, approvals off, "Do not allow bypassing the above settings" on, required checks
   `verify` and `linked-task / linked-task`. In GitHub, repository Settings, General, Pull
   Requests (`https://github.com/OWNER/REPO/settings`): tick **Allow squash merging** and,
   for `auto`, **Allow auto-merge**.
5. **Give bot pull requests the cheap default.** Every push to a pull request runs every
   check, and a bot rebases its pull requests whenever the default branch moves. If the
   repository uses Dependabot, enable it in GitHub, repository Settings, Advanced Security
   (`https://github.com/OWNER/REPO/settings/security_analysis`) and add
   `.github/dependabot.yml` with one block like this per ecosystem:

   ```yaml
   version: 2
   updates:
     - package-ecosystem: "github-actions"   # repeat for pip, npm and so on
       directory: "/"
       schedule:
         interval: "monthly"
       open-pull-requests-limit: 2           # version updates; security updates are not counted
       groups:
         minor-and-patch:
           applies-to: version-updates
           update-types: ["minor", "patch"]
         security:
           applies-to: security-updates
           patterns: ["*"]
   ```

   That is at most two open version-update pull requests per ecosystem, minor and patch
   updates in one of them, and the security updates of an ecosystem in one more. A bot pull
   request names no task, so `linked-task` holds it until the owner gives it one; a red one
   is fixed or closed at the next backlog review, never left rebasing
   ([Task records](AGENTS.md#task-records)).
6. **Connect the assistants**: paste `AGENTS.md` into the project instructions where the
   assistant has them and enable the three skills on the account, as in step 6 of
   [Try it](#try-it). Then file the first task from the form and let one pull request close
   it.

## What is enforced, and what is trust only

Every rule on [the page](AGENTS.md), and what holds it when a session ignores the page. Each
row was read against [`pr-policy.yml`](.github/workflows/pr-policy.yml) and
[`ci.yml`](.github/workflows/ci.yml). "Trust only" means nothing in GitHub stops a session
that breaks the rule; the record, the pull request and the review are where it shows.

| Rule on the page | Enforced by |
| --- | --- |
| A pull request closes exactly one task | `linked-task` |
| That task is open, with one priority, one category, and neither `blocked:owner` nor `kind:tracking` | `linked-task` |
| That task carries `status:ready` (owner gate Ready) | `linked-task` |
| A sub-issue's parent is open with a category and a priority or `kind:tracking`, with or without `blocked:owner` beside the priority; in `auto` the parent is Ready too | `linked-task` |
| In `auto`, a task above the priority cap or in an owner-only category was readied by the owner | `linked-task`, when a threshold variable is set. It compares the login that last applied the label, so it cannot tell the owner from a session acting through the owner's account |
| In `auto`, a pull request targets the integration branch; only the promotion targets the default branch | `linked-task` |
| One branch, one head, one pull request; no second pull request at the same head | `linked-task` |
| A task above the priority cap, in an owner-only category or labelled `review:required` holds the merge until its head has a submitted GitHub review that does not request changes; a push needs a new one | `linked-task`, which reads the pull request's reviews. When one is submitted the check runs again and re-runs its `pull_request` run on the head, the one the merge follows, so a passing review unblocks the merge and a request for changes blocks it with no edit or push; on a pull request from a fork the token cannot re-run and someone re-runs the check by hand. Only an owner, member, collaborator or bot counts, a comment never clears a request for changes, and a reviewer with its own login cannot be forged. A review from the author's login counts when it starts `Reviewer: <runtime>`, so that the Reviewer is another runtime than the Implementer, and read the head, is trust only |
| A pull request that changes only record paths (`docs/adr/`) may use `Refs #n` | `linked-task` |
| A parent never has a pull request of its own; its own work is a sub-issue | Trust only. `linked-task` does not look at whether the closed task has sub-issues |
| The verification contract passes on the head | `verify`, on the pull request head. Its whitespace row, `git diff --check`, compares a clean checkout with itself and cannot fail in CI |
| Nothing lands on the default branch without a pull request and both checks green; no bypass; no force-push there | Branch protection |
| A green pull request in `auto` squash-merges by itself | GitHub native (auto-merge), once a session arms it |
| The branch is updated when `main` moved under the pull request | Trust only, unless branch protection requires branches to be up to date |
| Merge by hand; mark a draft ready; approve in place of the owner's Merge gate (a Reviewer's native review of a head is allowed) | Trust only. Branch protection limits a hand merge to a green pull request, and with approvals off an approval changes nothing |
| Edit branch protection, required checks or variables | GitHub native (admin permission) for an assistant with its own identity; trust only for a session acting through the owner's account |
| Skip, disable or quarantine a check to get green | Branch protection keeps the two check names required; a pull request that edits what `verify` runs is not detected: trust only |
| A record is filed with a title, the problem and its parent; the Ready facts are filled in before Ready | GitHub native (the three required fields of the task form) at filing through the form. The Ready facts, their content, and an issue filed without the form: trust only; `linked-task` reads labels, not issue body fields |
| Ready applied with a comment naming the approving message; approval only from the owner's own words | Trust only |
| `status:ready` on a top-level record is the owner's: applied by the owner, or by a session on the owner's own message naming the record, never on a session's judgment | Trust only below the thresholds |
| A record's state is read by the ordered rule; nobody writes it | Nothing to enforce: the state is a reading of GitHub facts, not a field. `linked-task` holds the Ready fact (`status:ready`); the checks and auto-merge are the Merge and Done facts |
| Who moves each state; the Implementer moves none; the Planner assigns the issue when it starts the thread | Trust only, apart from the Ready and Merge rows above |
| Reject is the owner's decision: closed as not planned or duplicate, by the owner or on the owner's quoted words, with one sentence giving the reason; a parent with a finished child closes as Done and its unfinished children are Rejected | Trust only |
| Blocked is `blocked:owner` beside a priority, never in place of one | `linked-task`: a task, its parent or a referenced record needs one priority whether or not it carries `blocked:owner`, and a pull request that closes a task carrying it is refused. The comment saying what is awaited: trust only |
| `P2` and `P3` records without `review:required` may merge unread; the weekly backlog review lists them | GitHub native (auto-merge) for the merge. The list: the weekly report of `backlog-review.yml`, which names the pull requests merged since 2026-11-23 with no review and the open ones whose head has waited more than `CONDUCTOR_STALE_DAYS`; reading them afterwards is trust only |
| Three levels; related work is a sub-issue; the Planner's closing report on the parent | Trust only |
| Selection order; `agent:*` labels; no claim, release or milestone comment from the Implementer; one handoff comment when a session stops without a pull request | Trust only |
| One role per session; the Planner and the Reviewer never push; at most two threads in parallel | Trust only |
| Stay inside the record's allowed paths; take exactly the task given; never widen scope | Trust only |
| The push budget; a red check fixed locally before the next push; work in progress never pushed to a pull request | Trust only |
| The verification ledger and the evidence table in the pull request body | Trust only (the template asks for them) |
| The cost defaults of `ci.yml` (trigger, concurrency, timeout, runner) | Trust only (they are in the copied file; nothing checks they stay) |
| A red bot pull request is fixed or closed at the next backlog review | Trust only |
| No force-push or rewritten history on a task branch | Trust only |
| No deploy, spend, credential or access change, non-public data, publishing outside GitHub, account rotation or credentials in files | Trust only |
| Nothing starts on a Parked or Closed project, or on a record that is not Ready | Trust only at the start; `linked-task` stops the pull request of a record that is not Ready |
| Where the actor matters, a write goes through the assistant's verified App; a write through another account credits the assistant in its text; a credit satisfies no gate | The App workflows (`codex-planner-comment.yml`, `claude-identity.yml`) fail unless GitHub names the App's bot as author, and `linked-task` reads the actor of an owner Ready and the author of a required review. The credit, and which assistant composed a write made under the owner's login: trust only |
| Scheduled checks only when asked and read-only, apart from the auto-start check and its limits (ADR 0013); a record that must wait carries the native "Blocked by" link; say what is missing and stop | Trust only |

## Status

Lifecycle Active; approval mode `auto`; latest decision [ADR
0011](docs/adr/0011-record-states.md). Conductor runs itself with these rules: its
[issues](https://github.com/AhmedAlhanaei/Conductor/issues) are the task records and the pinned
Backlog issue is an optional notebook of one-line ideas. Documentation only; no application
runtime.
It is deliberately small ([ADR 0006](docs/adr/0006-minimal-core.md)): the policy fits one page,
and anything that would need a generator, a runtime or a second copy of the rules is out.

## The files

| Path | What it is |
| --- | --- |
| `AGENTS.md` | The whole policy: project facts, roles, owner gates, task records, task start and finish, the never-do list, the verification contract. Read natively by Codex, Cursor and Gemini CLI; Claude Code reads it through `CLAUDE.md`. |
| `CLAUDE.md` | `@AGENTS.md` |
| `README.md` | This page. |
| `.gitignore` | Keeps local secrets (`.env`) and editor, OS and Python cache files out of the repository. |
| `.github/workflows/pr-policy.yml` | The `linked-task` check: a pull request closes exactly one open task that carries one priority, one category and `status:ready`, and is neither owner-blocked nor tracking; in approval mode `auto` the task's parent is ready too; a `review:required` task holds the merge until the body records a review of the head; in `auto` a task above the assistant priority cap or in an owner-only category must have been readied by the owner; the head commit must belong to this pull request alone (one branch, one head, one pull request). |
| `.github/workflows/ci.yml` | The `verify` check: `git diff --check`, `actionlint` and the checker tests. A project with code replaces the steps with its own verification contract. |
| `tests/test_pr_policy.py` | Standard-library regression tests that run the checker embedded in `pr-policy.yml` against faked `gh` answers; no network. |
| `.github/workflows/backlog-review.yml` | Optional weekly read-only backlog report. |
| `.github/ISSUE_TEMPLATE/task.yml` | The task form: title, Problem and Parent task required at filing, the Ready facts before Ready, and "Success criteria (parent only)". |
| `.github/pull_request_template.md` | `Closes #n`, the verification ledger, merge danger, review line, "Found and left". |
| `skills/task-start/SKILL.md`, `skills/task-finish/SKILL.md`, `skills/record-review/SKILL.md` | The three skills as prose steps: the two task boundaries of the Implementer and the Reviewer's review of a head; upload them as account skills. |
| `docs/adr/0002` to `0013` | Decision history. ADR 0006 records the shrink to this shape; ADR 0007 the review gate; ADR 0008 the thresholds in `auto`; ADR 0009 Grok as a readying and reviewing identity; ADR 0010 the checker called at a tag; ADR 0011 the states of a record and who moves them; ADR 0012 the release step, a candidate tag tested on an adopter before `v1` moves; ADR 0013 the auto-start check, accepted and not yet switched on. |
| `docs/auto-start-check.md` | The instruction text of the one scheduled check that is not read-only: it has the Planner start the thread of a Ready record that is free to start. The prompt of a claude.ai scheduled task, not a workflow; a change to it is a pull request. |
| `docs/assistant-attribution.md` | The attribution procedure: role, authority and actor, what each assistant's App has been shown to do and what is pending, the credit texts, three walk-throughs and the finish check. |
| `docs/assistant-identity-handoff.md` | What an assistant repeats to get and prove its own App identity: the pattern, the variable and secret names per assistant, and what each still has to show. |
| `docs/lifecycle.md` | Reference for the states of a record; the page governs. |
