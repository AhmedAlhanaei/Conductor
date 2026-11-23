---
name: task-start
description: Start one readied task - read the record and its state, refuse without status:ready, a record meant for another assistant or one already being worked elsewhere, branch from the integration branch, pick up from the newest handoff comment, record the baseline and keep the allowed paths in view; writes no comment, label or assignment
---

# Task start

Conductor speaks twice per task. This is the first time: `task-start #n` turns a readied task
record into a bounded piece of work on one branch. Between this and `task-finish` the
assistant's own practice runs. This skill grants no authority; the task record and the
platform do.

1. Read the project's `AGENTS.md`, then the record #n with its comments, labels, assignees
   and linked pull requests, through your own GitHub access. Read its state by the ordered
   rule in Task records. Pick up from the newest handoff comment on #n: its head SHA, what
   is pushed or unpushed, blockers and next step are the starting state. Do not describe
   the task from memory.
2. Refuse and stop, naming the fact that is missing, when #n is not open; when it lacks the
   `status:ready` label; when, in approval mode `auto`, it is above the assistant priority
   cap or in an owner-only category and its `status:ready` is not the owner's; when an
   `agent:*` label names another assistant; or when it is already being worked elsewhere:
   an open pull request closes it, it is assigned to someone other than the identity you
   work under, or a branch holds work for it that no handoff comment accounts for.
3. Write nothing on the record. Post no claim comment, apply no label and assign nobody:
   the Planner's assignment of the issue is the claim, and `status:ready` is the owner's
   or the Planner's. When the record is Ready but unassigned, say so in your first message
   and leave the assignment to the Planner.
4. Branch from the project's integration branch (`main` unless `AGENTS.md` names another) as
   `<assistant>/<slug>-<date>`, or keep the branch the runtime assigned. Record the baseline
   in your first message: base SHA, dirty state, known failures.
5. Keep three lines in view for the rest of the task: the task and its allowed paths; what
   is never yours (merging, pushing to the integration branch, rewriting history, and any
   label, assignment, close or state of an issue); how to finish (`task-finish`). Work only
   inside the allowed paths; anything found outside them is left for `task-finish`.

Stop and ask the owner when the record has no allowed paths, when the integration branch
cannot be fetched, or when the task would need a service, secret or connector you cannot
reach.
