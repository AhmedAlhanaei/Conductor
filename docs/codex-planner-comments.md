# Codex Planner comments

How a Codex session acting as Planner publishes a comment under its own GitHub identity,
`codex-conductor[bot]`, instead of the owner's login. Record: #134; identity proof: #132.

A Codex session cannot hold the App key. It asks for publication by dispatching
`.github/workflows/codex-planner-comment.yml` on `main`; the key stays in Actions, and the
workflow posts the comment, checks who GitHub says wrote it and returns the permalink.

## Submit

Three inputs, all required:

| Input | Value |
| --- | --- |
| `issue` | number of an open issue of this repository (not a pull request) |
| `request_id` | a stable ID for this one message: 8 to 64 characters of `A-Z a-z 0-9 . _ -`, starting with a letter or digit, for example `plan-124-round-2` |
| `message` | the comment, Markdown, at most 60,000 characters; published as written |

```sh
gh workflow run codex-planner-comment.yml --repo AhmedAlhanaei/Conductor --ref main \
  -f issue=124 -f request_id=plan-124-round-2 -f message="$(cat message.md)"
```

Without `gh`: GitHub, Actions, "Codex Planner comment", "Run workflow" on `main`
(https://github.com/AhmedAlhanaei/Conductor/actions/workflows/codex-planner-comment.yml), or
`POST /repos/AhmedAlhanaei/Conductor/actions/workflows/codex-planner-comment.yml/dispatches`
with `{"ref": "main", "inputs": {...}}`.

Choose the request ID before the first attempt and keep it for every retry of the same
message. Write it down with the message: the ID is what makes a retry safe.

## Receive the permalink

The run is named `Codex Planner comment on #<issue> (<request_id>)`, so it can be found by
the request ID:

```sh
gh run list --repo AhmedAlhanaei/Conductor --workflow codex-planner-comment.yml --limit 5
gh run view <run id> --repo AhmedAlhanaei/Conductor --log | grep -E '(published|reused): https://'
```

A successful run prints `published: <permalink>` or `reused: <permalink>`, writes the same
permalink with the verified author, the requester, the request ID and the payload SHA-256 to
the run summary, and sets the job outputs `comment-url` and `result`. A failed run prints one
`::error::` line with the reason and returns no permalink.

## What the workflow checks

In this order; the first failure stops the run, and nothing is published unless the reason
says otherwise.

1. Caller. The event is a manual dispatch of this repository on `refs/heads/main`. The
   actor and the triggering actor are the owner: `CONDUCTOR_OWNER_LOGIN`, else the
   repository owner. This is checked once before the App token is minted and again by the
   publisher.
2. Role. The effective Planner is Codex: the repository variable
   `CONDUCTOR_DEFAULT_PLANNER` equals `codex`. The token belongs to the `codex-conductor`
   App. Setting the variable to anything else switches publication off.
3. Inputs. The issue number, request ID and message have the shapes in the table above.
4. Target. GitHub answers for that number with an open issue of this repository: not a
   pull request, not closed, not missing, and not an issue that was transferred and now
   redirects elsewhere.
5. Retry. Every comment on the issue is read. If `codex-conductor[bot]` already published
   this request ID there with the same issue and message, the run returns that comment
   (`reused`) and posts nothing. With a different message it fails with `conflict`; even a
   whitespace change counts. A marker in anyone else's comment, or quoted inside a message,
   is ignored.
6. Author. After posting, GitHub's answer must name `codex-conductor[bot]`, type `Bot`,
   through the `codex-conductor` App. Otherwise the run fails with `identity mismatch` and
   names the comment: stop and tell the owner.

The published comment is the message, a rule, and one line naming the App, the requester, the
request ID and the run, followed by a hidden marker with the request ID and the payload hash:

```
<message>

---
_Published for the Codex Planner by `codex-conductor`. Requested by `alhanaei`, request `plan-124-round-2`, [run](...)._
```

## Retry

- The run failed before publishing (any `refused`, `wrong target` or `conflict`): fix the
  cause and dispatch again. Keep the request ID unless the message changes.
- The run failed while posting or its result is unknown: dispatch again with the same
  request ID, issue and message. If the comment exists it is returned, otherwise it is
  published once.
- The message must change: use a new request ID. The first comment stays; this workflow
  never edits or deletes.

## Limits

- The message is data. It reaches the script through the environment and GitHub as a JSON
  body; it is never part of a command line and never echoed in an error. It is still
  published as written, so `@mentions` notify and issue references link.
- "Who requested" is the GitHub login that dispatched the run. An assistant that dispatches
  through the owner's own account or connector is recorded as the owner; GitHub offers no
  finer fact.
- A request ID is unique per issue. The same ID on another issue is another request.
- Runs are serialized. GitHub keeps one waiting run per group, so of several dispatched at
  once only the newest waiting one survives; dispatch one, read its result, then the next.
- Scope is issue comments. Labels, the Ready gate, pull request reviews, merges, Projects and
  repository settings are outside it (ADR 0009 covers Grok's Ready and review).
- Each run bills one rounded-up minute on a private repository.

## Owner setup

Already in place since #132: the `codex-conductor` App installed on this repository with
Issues read and write, the variables `CODEX_CONDUCTOR_CLIENT_ID` and
`CONDUCTOR_DEFAULT_PLANNER`, and the secret `CODEX_CONDUCTOR_PRIVATE_KEY`.
`CONDUCTOR_OWNER_LOGIN` must name the owner's login, because in an organization the
repository owner is the organization.
