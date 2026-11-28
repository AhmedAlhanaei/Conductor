---
name: task-finish
description: Finish one task - run the verification contract on the exact head, re-read the record, open one pull request with Closes #n and the ledger, arm squash auto-merge in approval mode auto, fix on a red check or a request for changes; --stopped posts one handoff comment instead of a pull request; --report is the Planner's closing report on a parent whose last child closed; writes no other comment, label, assignment or review
---

# Task finish

The second and last time Conductor speaks in a task. `task-finish` turns the branch into a
reviewable pull request with evidence, or records an honest stop. A finish without evidence
that matches the exact head is a stopped finish, never a done one. The pull request is the
report: this skill posts no milestone, claim or release comment.

1. Commit everything that belongs to the task. Evidence must name the SHA it ran on, so
   nothing may be uncommitted.
2. Run every applicable row of the verification contract in the project's `AGENTS.md` from
   its stated cwd on the exact head. Do not infer commands from another repository or from
   memory. Record for each row: command, cwd, passed or failed, output lines that matter,
   tested SHA. If a row fails, fix, commit and run again; never skip, disable or quarantine
   a check to get green.
3. Before the pull request opens, read the record #n and its comments again. Answer a new
   comment from the owner first. Pause and ask when the record itself changed since the
   task started: its body, its labels, its parent, or it was closed.
4. Push the branch and open one pull request against the integration branch from the
   repository's template: `Closes #n`; what changed and why; the verification ledger with
   tested SHAs; the runtime that implemented it; merge danger (two-way or one-way door,
   blast radius); the credit when the pull request is opened through another account
   ("Claude implemented the change. Opened through `<login>`."); a "Found and left" block
   with every finding outside the task's scope, one line each with a suggested priority. Fill the criterion-to-evidence table from the
   record's numbered acceptance criteria, one row each with evidence, result and tested
   SHA, before the pull request opens. Nothing found mid-task is done here.
5. When the project's approval mode is `auto` and the task is a sub-issue of a readied
   parent, enable GitHub auto-merge with squash as soon as the pull request is open, while
   the checks still run; GitHub merges it when the required checks are green. In `manual`
   the owner merges.
6. Drive the pull request to green: on a red check or a review that requests changes,
   reproduce and fix locally on the same branch, put the fixes for several findings in one
   push within the record's push budget, and update the ledger to the new head. Where the
   record requires a review, wait for the Reviewer's review of the head; when `main` moved
   under the pull request, update the branch with `main`.
7. Check attribution before reporting. For each write of the task (the pull request, a
   comment, a dispatched App run), read back the actor GitHub recorded and compare it with
   the route named at the start. An owner-account write carries its credit in the text: add
   it where it is missing. An App write names the App's bot, type `Bot`, as author or as the
   actor of that exact event: link it. A wrong actor on a gate, a review or an App-only
   write is reported to the owner with its evidence; never repeat a write to change how its
   history looks. A credit satisfies no gate and no review.
8. Stopping instead (`task-finish --stopped`), when context, quota, access or the owner's
   decision runs out: open no pull request and post one handoff comment on #n, the only
   comment this skill writes. Gather every fact from GitHub and `git` (the record, `git
   log`, `git status`), never from memory or chat; write `unknown` for what is not known.

   ```
   **Handoff.** <role> on <runtime>, <reference>, <UTC time>. Branch `<branch>` at
   `<head SHA>`. Pushed: <branch and head | none>. Unpushed or local: <what | none>.
   Evidence: <rows run and their result | none>. Decisions: <one line each | none>.
   Blockers: <open blockers | none>. Found and left: <one line each | none>. Next step:
   <one sentence a fresh session can execute>.
   ```

9. The closing report (`task-finish --report`) is the Planner's, never the Implementer's:
   when the last child of a tracking or top-level parent closes, one comment on the parent,
   every fact read from GitHub. A pull request is accepted (merged and not reverted within
   14 days), closed unmerged, reverted or pending; only a record is Rejected. In approval
   mode `auto` the Planner then closes the parent as completed; in `manual` the owner does.

   ```
   **Closing report.** Planner on <runtime>, <reference>, <UTC time>.

   | Child | Pull request | Merge SHA | Pull request is |
   | --- | --- | --- | --- |
   | #n <title> | #m | <SHA> | accepted, closed unmerged, reverted or pending |

   Rejected children: <#n, closed as not planned or duplicate: the reason | none>.

   | Success criterion | Evidence | Result |
   | --- | --- | --- |
   | 1. <from the parent's "Success criteria (parent only)", or its acceptance criteria> | <test, inspection or link> | met or not met |

   Verification evidence: <rows and tested SHAs>. Decisions: <one line each | none>.
   Push-budget overruns: <child and count | none>. Found and left: <one line each | none>.
   Next record to open: <#n or a one-line proposal | none>.
   ```

Refuse, whoever asks: merging by hand; reviewing or approving your own pull request;
applying or removing a label, assigning, closing or reopening any issue (the Planner's
close of a parent after its closing report apart); a second pull request for the task. The
record's state moves by what GitHub holds, never by this skill.

Stop and ask the owner when the pull request would close a task other than the one you
started, or when a verification row needs a tool the session cannot install.
