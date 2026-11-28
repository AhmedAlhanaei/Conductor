# ADR 0013: A scheduled check starts the thread of a Ready record that is free to start

- Status: Accepted, not yet in force (the owner's "yes to all.", 2026-11-28 16:45 UTC in the
  claude.ai project chat, to the eight decisions of #157 round 1 as the Planner listed them
  there at 16:43 UTC; "ready 157" at 16:47 UTC; both recorded in comments on #157). Nothing
  is switched on by this record: no scheduled task exists until #159
- Date: 2026-11-28
- Deciders: repository owner
- Task record: #158 (slice 1 of #157, the top-level record)
- Amends: ADR 0005, in one point: in `auto` the go-ahead to start a thread is the Ready on
  any leaf record, the owner's Ready on a top-level or owner-only record included, not only
  the Planner's Ready on a sub-issue. ADR 0011, in one point: the Planner's move from Ready
  to Implement may be prompted by this check instead of the owner's message; who moves the
  state does not change
- Roles: decisions grilled by the Planner (project thread "Auto-start threads for Ready
  issues"); this record written by the Implementer (a project thread)

## Context

In `auto` a readied record is already the go-ahead to start its thread, but nothing starts
it. The Planner is the claude.ai project coordinator, and it wakes when the owner writes in
the project chat, not when a label changes on GitHub. A Ready record therefore waits until
the owner asks for it by hand.

The page allowed a scheduled check only as a read-only reminder: "not authority to start,
reassign or publish". Starting a thread and assigning its record is exactly what that
sentence forbids, so the rule needs a decision and one named exception.

Facts the Planner looked up on 2026-11-28, recorded on #157:

- A claude.ai scheduled task can fire into the project coordinator's session, and only the
  coordinator can start a project thread. The shortest interval is one hour. It spends
  Claude usage and no GitHub Actions minutes.
- No route is known by which a GitHub Action starts a claude.ai project thread: `unknown`
  beyond that. A workflow on label events would also bill at least one minute per event in a
  private repository.
- One issue search per repository answers most of the question; the rest needs a read of
  each hit.
- Every claude.ai session writes to GitHub as the owner's login, so GitHub cannot tell which
  session, or the owner, applied `status:ready`.
- No tool available to a claude.ai session sets GitHub's native "Blocked by" relationship.
  The owner sets it in the issue sidebar, or a session on the owner's computer does.

## Decision

The eight decisions of #157 round 1, each accepted by the owner's "yes to all.":

1. **Mechanism.** One claude.ai scheduled task fires into the project coordinator. No GitHub
   Action, no webhook, no new App or token.
2. **Interval.** Every hour.
3. **Whose Ready counts.** The owner's Ready on a top-level leaf or an owner-only record is
   also the go-ahead to start it automatically. That label exists only on the owner's own
   "ready N", so the check adds no decision of its own.
4. **One check.** One check in the Conductor claude.ai project covers four repositories:
   `AhmedAlhanaei/Conductor`, `AhmedAlhanaei/gachabot`, `AhmedAlhanaei/Media-Studio` and
   `AhmedAlhanaei/murbeh`, with at most two threads at work in total.
5. **Other modes.** In a repository whose approval mode is `manual` or `unknown`, the check
   proposes the thread to the owner and waits.
6. **Native links first.** Before switch-on, the Planner lists for the owner the open Ready
   records whose dependency is written only in the body, and the native "Blocked by" links
   are set from that list.
7. **Rollout.** A dry run on Conductor, then live on Conductor, then the other three
   repositories one at a time, each after its own dry run.
8. **The record.** #157 is `P2`, `kind:feature`.

The rule those decisions add up to follows. The text the scheduled task carries is
[`docs/auto-start-check.md`](../auto-start-check.md); where that file and this record
differ, this record governs and the file is corrected through a pull request.

### Free to start

A record is free to start when all six hold:

1. It is an open issue labelled `status:ready`.
2. It has no assignee and no open pull request that closes it.
3. It does not carry `blocked:owner`.
4. No open issue blocks it under GitHub's native "Blocked by" relationship.
5. It is a leaf: it has no sub-issues, is not `kind:tracking` and is not the Backlog issue.
6. It carries no `agent:*` label naming an assistant other than the one the thread runs.

A dependency written only in prose is not read and holds nothing back. That is why decision
6 comes before switch-on, and why the page now tells the Planner to name the native link
when it files a record that must wait.

### Order

Highest priority first, oldest first within it, across all covered repositories together:
the page's Selection rule, with `kind:security` winning a tie.

### Limit

At most two threads at work in the project at a time, counted across all covered
repositories. A run starts at most one thread, and none while two are at work. A second
thread starts only after the page's conflict review: its record's allowed paths share
nothing with the running thread's, or it waits.

### What the check writes

One thing on GitHub: the assignment of the issue when its thread starts, which the page
already gives the Planner as the move from Ready to Implement and which takes the record
out of the next run's search. The check never applies or removes `status:ready`, never
changes a priority or any other label, never files, edits, closes or comments on a record,
never sets a dependency link and never merges. It starts no Reviewer thread.

The thread it starts is an ordinary Implementer thread: Task start still applies there, the
refusal of a record whose `status:ready` is not the owner's included.

### Report-only

Each covered repository has one of three settings in the instruction file: `off` (not
searched), `report-only` or `live`. In `report-only` a run reads everything, starts nothing,
assigns nothing and reports every Ready record with the verdict "would start" or the first
condition that holds it back. A change of setting is a pull request to the instruction
file, so the rollout of decision 7 is a series of small pull requests under #159 and #160.

### A `manual` or `unknown`-mode repository

The mode is read from the "Approval mode" line of the repository's `AGENTS.md` on its
default branch; anything that does not say `auto` is `manual` or `unknown`. There the check
starts nothing and assigns nothing: it proposes the thread to the owner in the project chat,
once per record, and the owner's answer starts it. Nothing is started or proposed in a
repository whose page says the project is Parked or Closed.

### Switching it off

One step: the scheduled task is paused. The owner pauses it in claude.ai, or writes "pause
auto-start" in the project chat and the Planner pauses it. A paused task does not fire, so
nothing starts. Where claude.ai lists scheduled tasks: `unknown` to this record; #159 names
it when the task exists. Threads already started are not stopped by the pause.

## Not decided here

- The scheduled task itself, its name and its first run: #159.
- How the native "Blocked by" link is set without the owner's click: no route is known from
  a claude.ai session; #159 carries it.
- The approval mode and labels of gachabot, Media-Studio and murbeh: `unknown` until each
  one's dry run under #160.
- A scheduled Reviewer: Backlog line L15, not part of this.

## Consequences

- A record readied in a `live`, `auto`-mode repository is in Implement within about an hour
  with no message from the owner, when fewer than two threads are at work.
- A Ready label is now enough to start work. A record that should wait must say so in a form
  GitHub can be searched for: `blocked:owner`, a native "Blocked by" link, or no
  `status:ready` yet. Keeping a later slice in Triage until its predecessor merges, as #159
  and #160 are kept, stays valid.
- The limits of the check are trust only. Nothing in GitHub stops a run that breaks them;
  the assignment in the issue timeline, the thread and the weekly backlog review are where
  it shows.
- GitHub Actions minutes spent by the check: zero. It adds no workflow.
- The check depends on the coordinator being reachable by a scheduled task. If the task
  cannot fire or cannot be paused, that is a stop condition of #157, not something to work
  around.
