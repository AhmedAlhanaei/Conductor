---
name: task-finish
description: Finish one task - run the verification contract on the exact head, re-read the record, open one pull request with Closes #n and the ledger, arm squash auto-merge in approval mode auto, fix on a red check or a request for changes; --stopped posts one handoff comment instead of a pull request; writes no other comment, label, assignment or review
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
   blast radius); a "Found and left" block with every finding outside the task's scope, one
   line each with a suggested priority. Fill the criterion-to-evidence table from the
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
7. Stopping instead (`task-finish --stopped`), when context, quota, access or the owner's
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

Refuse, whoever asks: merging by hand; reviewing or approving your own pull request;
applying or removing a label, assigning, closing or reopening any issue; a second pull
request for the task. The record's state moves by what GitHub holds, never by this skill.

Stop and ask the owner when the pull request would close a task other than the one you
started, or when a verification row needs a tool the session cannot install.
