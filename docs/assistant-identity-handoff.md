# Assistant identity handoff

What an assistant repeats to get its own GitHub identity on a Conductor repository and to
prove a write was made by it. It hands the procedure Codex went through (#132, #134) to
Claude, Grok and any later assistant, as #136 asks. The rule is in
[`AGENTS.md`](../AGENTS.md), "Identity and attribution"; which writes each App has been shown
to make is the table in [`assistant-attribution.md`](assistant-attribution.md). Record: #137.

The source of this file is the
[Planner handoff on #136](https://github.com/AhmedAlhanaei/Conductor/issues/136#issuecomment-7084992687),
published by `codex-conductor[bot]`.

## The pattern

1. The owner creates a GitHub App for the assistant and installs it on the repository with
   the least permission the write needs. This is an access change: the owner's, never a
   session's.
2. The key stays where the assistant cannot read it. For Codex and Claude that is GitHub
   Actions: a repository variable holds the App's client ID and a repository secret one
   private key. For Grok it is Grok's own environment, which mints the installation token.
3. A write is requested, not made directly: a workflow on `main` is dispatched, mints a token
   scoped to that one permission, makes the write, then reads GitHub's answer and fails unless
   the author is the App's bot, type `Bot`, through that App.
4. A retry never duplicates: the request carries a stable ID or the write has a fixed target,
   and a second run returns the first result.
5. The evidence is the object's permalink and the run. A capability is demonstrated when both
   exist and a record links them; until then it is pending.

## Per assistant

| | Codex | Claude | Grok |
| --- | --- | --- | --- |
| Bot login | `codex-conductor[bot]` | `claude-conductor[bot]` | `grok-conductor[bot]` |
| Where the key is | Actions | Actions | Grok's environment |
| Variable | `CODEX_CONDUCTOR_CLIENT_ID`, and `CONDUCTOR_DEFAULT_PLANNER` set to `codex` | `CLAUDE_CONDUCTOR_CLIENT_ID` | none in this repository |
| Secret | `CODEX_CONDUCTOR_PRIVATE_KEY` | `CLAUDE_CONDUCTOR_PRIVATE_KEY` | none in this repository |
| App permission in use | Issues: read and write | Issues: read and write | Pull requests: write, shown by its reviews; the rest `unknown` from this repository |
| Workflow | `codex-planner-identity.yml` (proof), `codex-planner-comment.yml` (comments) | `claude-identity.yml` (one fixed comment on #139) | none: Grok calls the API itself |
| Dispatch inputs | `issue`, `request_id`, `message` | none | not applicable |
| Usage | [`codex-planner-comments.md`](codex-planner-comments.md) | the header of `claude-identity.yml` | ADR 0009 |
| Records | #132, #134, #136 | #139, #146, #147 | #108, #143, #149 |

Every workflow also needs `CONDUCTOR_OWNER_LOGIN` to name the owner's login when the
repository belongs to an organization: unset, it falls back to the organization's name and
every run is refused.

## Who is who in a run

Three names appear around an App write, and they are different facts:

- The dispatcher: the login that started the run. An assistant that dispatches through the
  owner's account or connector is recorded as the owner.
- The approving owner: whoever's words authorize the act. Only a message of the owner's shows
  it; no field of the run does.
- The GitHub actor: the App's bot, which the run verifies.

The caller check "owner only" in these workflows therefore proves less than it reads: it
passes for any session that works under the owner's login.

## What each assistant still has to repeat

- Codex: the live run and the retry of #136 (issue creation, one label applied and removed,
  each attributed to the bot). When it is done, #136 adds the issue timeline and both run
  links here and moves the row in `assistant-attribution.md`.
- Claude: the capability run of #146, through the workflow of #147 (create a sub-issue, the
  Issues writes, each actor checked). Reviews and pull requests as the App have no record.
- Grok: `status:ready` as the bot has no live example recorded. Its reviews are shown.
- Gemini: nothing exists; steps 1 to 5 above from the start, on a record the owner readies.

## Until then

Ordinary work does not wait for an App. It goes through the owner-account route with a credit
in the text, as `assistant-attribution.md` describes. What does wait is any act whose actor a
gate or a check reads: an owner Ready, a required review, a Grok Ready or review.
