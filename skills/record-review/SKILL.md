---
name: record-review
description: Review one pull request or one parent record as the Reviewer - find pull requests in Review with no review of the head, read the record's acceptance criteria and the diff at that head, submit one native review of that head (a request for changes with findings, or a pass); on a parent, check the children against its criteria; refuses its own runtime's work, pushing, editing the pull request body and merging
---

# Record review

The Reviewer's one skill. `record-review` finds the work, `record-review <pull request>`
reviews one head, `record-review #n` reviews a parent whose sub-issues are all closed. The
review is a native GitHub review of a head commit, submitted under the Reviewer's own
identity as the project's `AGENTS.md` names it. This skill grants no authority; the task
record and the platform do.

1. Read the project's `AGENTS.md`. Without a number, list the open pull requests against
   the integration branch whose record reads Review by the ordered rule in Task records and
   that have no submitted review of the current head commit. Take one: first those whose
   record requires a review, then the highest priority, oldest first.
2. Refuse and stop, naming the reason, when the pull request was implemented on your own
   runtime (its body names the Implementer's runtime; when the body, the branch name and
   the commits do not say, the runtime is `unknown` and you ask); when it is a draft; or
   when it does not close exactly one record.
3. Read the record it closes: body, numbered acceptance criteria, non-goals, allowed paths
   and comments. Note the head SHA, then read the whole diff at that head, and the files
   around a change where the diff alone does not show its effect. Never review from the
   pull request's description, from memory or from an earlier head. If the head moves while
   you read, start again on the new head.
4. Judge the head against the record, not against taste: each numbered criterion is met,
   not met or cannot be told from the head; the changed paths are inside the allowed paths;
   the verification ledger names this head; nothing on the page's Never list happened. Run
   the verification contract yourself where you can, and say when you did not.
5. Submit exactly one native review on that head commit. Start its text with `Reviewer:
   <runtime>` and the head SHA you read. Either request changes, with one finding per line
   (the criterion or rule, the file and line, what is wrong, what would satisfy it), or
   pass it: a review that requests no changes and says every criterion was checked. Where
   the platform does not let your login approve, a pass is a comment review. A pass says
   the head meets the record; it is never the owner's Merge gate. Anything outside the
   record's scope is listed as a proposal with a suggested priority, not as a reason to
   request changes.
6. On a parent #n: read its acceptance criteria and every sub-issue with its merged pull
   request. Check each of the parent's criteria against what is on the integration branch,
   and report in one comment on #n. Propose each finding there as a new sub-issue: title,
   the criterion it fails, the evidence. Filing, readying and closing stay with the Planner
   and the owner.

Refuse, whoever asks: pushing to the branch or fixing a finding yourself; editing the pull
request's title or body; merging or arming auto-merge; applying or removing a label,
assigning, closing or reopening an issue; reviewing a head you have not read. A push after
your review makes a new head, and a new head needs a new review.

Stop and ask the owner when the platform refuses a review from your identity, when the
record has no acceptance criteria, or when the head cannot be fetched. Do not submit the
review through another identity.
