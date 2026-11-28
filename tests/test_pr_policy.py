"""Regression tests for the `linked-task` checker embedded in `.github/workflows/pr-policy.yml`.

The checker is the Python script in the workflow's single `run: |` step. These tests read that
exact text out of the workflow file and execute it with `subprocess.run` replaced by an
in-memory GitHub double, so the policy under test is the one CI runs, not a copy. Nothing here
touches the network, a credential or a real label.

Run from the repository root:  python3 -m unittest discover -s tests -p 'test_*.py'
"""

import contextlib
import io
import json
import os
import pathlib
import re
import subprocess
import textwrap
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "pr-policy.yml"

HEAD = "a" * 40
STALE = "b" * 40
PAGE = 30  # the REST API's default page size

DEFAULT_ENV = {
    "GITHUB_REPOSITORY": "owner/repo",
    "PR_NUMBER": "7",
    "PRIORITY_LABELS": "P0,P1,P2,P3",
    "BLOCKED_LABEL": "blocked:owner",
    "CATEGORY_PREFIX": "kind:",
    "TRACKING_LABEL": "kind:tracking",
    "READY_LABEL": "status:ready",
    "RECORD_PATHS": "docs/adr/",
    "APPROVAL_MODE": "manual",
    "INTEGRATION_BRANCH": "main",
    "DEFAULT_BRANCH": "main",
    "BASE_REF": "main",
    "HEAD_REF": "claude/feature",
    "REVIEW_REQUIRED_LABEL": "review:required",
    "PRIORITY_CAP": "",
    "OWNER_CATEGORIES": "",
    "OWNER_LOGIN": "owner",
    "HEAD_SHA": HEAD,
    "PR_AUTHOR": "author",
    "PR_AUTHOR_TYPE": "User",
    "BOT_AUTHORS": "",
    "GITHUB_EVENT_NAME": "pull_request",
    "GITHUB_RUN_ID": "900",
}
WORKFLOW_ID = 55  # the workflow the current run (GITHUB_RUN_ID) belongs to


def embedded_script():
    """Return the dedented Python source of the workflow's `run: |` step."""
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if line.strip() == "shell: python" and lines[index + 1].strip() == "run: |":
            indent = len(lines[index + 1]) - len(lines[index + 1].lstrip())
            body = []
            for next_line in lines[index + 2:]:
                if next_line.strip() and (len(next_line) - len(next_line.lstrip())) <= indent:
                    break
                body.append(next_line)
            return textwrap.dedent("\n".join(body)) + "\n"
    raise AssertionError("no `shell: python` step with a `run: |` block in pr-policy.yml")


class ApiError(Exception):
    """A `gh api` failure: exit code plus what gh writes to stderr and stdout."""

    def __init__(self, returncode, stderr, stdout=""):
        super().__init__(stderr)
        self.returncode, self.stderr, self.stdout = returncode, stderr, stdout


NO_PARENT = ApiError(1, "gh: Not Found (HTTP 404)\n", '{"message":"Not Found","status":"404"}\n')


class FakeGitHub:
    """Stands in for `subprocess.run` and answers the `gh` calls the checker makes."""

    def __init__(self, body="Closes #42", files=("src/app.py",), issues=None, parents=None, head_pulls=None, timelines=None, reviews=None):
        self.body = body
        self.files = list(files)
        # what `gh api repos/{repo}/commits/{sha}/pulls` answers for the head: a list of pull
        # requests, or an ApiError; by default this pull request alone
        self.head_pulls = [{"number": 7, "state": "open", "head": {"sha": HEAD}}] if head_pulls is None else head_pulls
        # the commit the pull request head is at; a test moves it to stand for a new push
        self.head = HEAD
        # issue number -> (labels, state)
        self.issues = dict(issues or {42: (["P2", "kind:chore", "status:ready"], "OPEN")})
        # issue number -> parent number, or an ApiError for the parent lookup; absent means 404
        self.parents = dict(parents or {})
        # issue number -> list of timeline events (one page), or an ApiError; absent means the
        # owner applied every label the issue carries
        self.timelines = dict(timelines or {})
        # what `gh api repos/{repo}/pulls/{n}/reviews` answers: a list of reviews in the
        # order GitHub returns them (oldest first), an ApiError, or a raw string; by default
        # the pull request has no review
        self.reviews = [] if reviews is None else reviews
        # what `gh api repos/{repo}/pulls/{n}/commits` answers: a list of commits, oldest
        # first, an ApiError or a raw string; read only for a listed bot author (ADR 0014)
        self.commits = []
        # what `gh api repos/{repo}/actions/runs/{GITHUB_RUN_ID}` answers, or an ApiError
        self.current_run = {"id": 900, "workflow_id": WORKFLOW_ID}
        # the `pull_request` runs of the workflow on the head: a list of runs, an ApiError or
        # a raw string; `run_polls`, when set, is answered first, one entry per lookup
        self.runs = []
        self.run_polls = []
        # what the re-run call answers: None (HTTP 201, empty body) or an ApiError
        self.rerun = None
        self.sleeps = []
        self.calls = []

    def __call__(self, args, check=False, capture_output=False, text=False, **kwargs):
        self.calls.append(list(args))
        assert args[0] == "gh", f"only gh is faked, got {args!r}"
        assert capture_output and text, "the checker must capture gh output as text"
        try:
            stdout = self._dispatch(args[1:])
        except ApiError as error:
            if check:
                raise subprocess.CalledProcessError(error.returncode, args, error.stdout, error.stderr)
            return subprocess.CompletedProcess(args, error.returncode, error.stdout, error.stderr)
        return subprocess.CompletedProcess(args, 0, stdout, "")

    def _dispatch(self, args):
        if args[:2] == ["pr", "view"]:
            assert args[2] == DEFAULT_ENV["PR_NUMBER"] and args[3:5] == ["--repo", "owner/repo"]
            fields = args[args.index("--json") + 1]
            if fields == "body":
                return json.dumps({"body": self.body})
            if fields == "files":
                return json.dumps({"files": [{"path": path} for path in self.files]})
        if args[:2] == ["issue", "view"]:
            number = int(args[2])
            assert args[3:5] == ["--repo", "owner/repo"] and args[args.index("--json") + 1] == "labels,state"
            if number not in self.issues:
                raise ApiError(1, "GraphQL: Could not resolve to an issue or pull request (HTTP 404)\n")
            labels, state = self.issues[number]
            return json.dumps({"labels": [{"name": name} for name in labels], "state": state})
        if args[0] == "api" and re.fullmatch(r"repos/owner/repo/commits/[0-9a-f]{40}/pulls", args[-1]):
            assert args[-1].split("/")[4] == self.head, "the lookup must use the pull request head"
            assert args[1:3] == ["--paginate", "--slurp"], "the pull requests at the head must be read in full, as pages"
            if isinstance(self.head_pulls, ApiError):
                raise self.head_pulls
            # --slurp: one array per page, 30 items each as the API pages by default
            pages = [self.head_pulls[i:i + PAGE] for i in range(0, len(self.head_pulls), PAGE)] or [[]]
            return json.dumps(pages)
        if args[0] == "api" and args[-1] == f"repos/owner/repo/pulls/{DEFAULT_ENV['PR_NUMBER']}/reviews":
            assert args[1:3] == ["--paginate", "--slurp"], "the reviews must be read in full, as pages"
            if isinstance(self.reviews, ApiError):
                raise self.reviews
            if isinstance(self.reviews, str):
                return self.reviews
            return json.dumps([self.reviews[i:i + PAGE] for i in range(0, len(self.reviews), PAGE)] or [[]])
        if args[0] == "api" and args[-1] == f"repos/owner/repo/pulls/{DEFAULT_ENV['PR_NUMBER']}/commits?per_page=100":
            assert args[1:3] == ["--paginate", "--slurp"], "the commits must be read in full, as pages"
            if isinstance(self.commits, ApiError):
                raise self.commits
            if isinstance(self.commits, str):
                return self.commits
            return json.dumps([self.commits[i:i + 100] for i in range(0, len(self.commits), 100)] or [[]])
        if args == ["api", f"repos/owner/repo/actions/runs/{DEFAULT_ENV['GITHUB_RUN_ID']}"]:
            if isinstance(self.current_run, ApiError):
                raise self.current_run
            return json.dumps(self.current_run)
        if args[0] == "api" and args[-1].startswith("repos/owner/repo/actions/workflows/"):
            assert args == ["api", f"repos/owner/repo/actions/workflows/{WORKFLOW_ID}/runs?head_sha={self.head}&event=pull_request&per_page=100"], args
            runs = self.run_polls.pop(0) if self.run_polls else self.runs
            if isinstance(runs, ApiError):
                raise runs
            return runs if isinstance(runs, str) else json.dumps({"total_count": len(runs), "workflow_runs": runs})
        match = re.fullmatch(r"repos/owner/repo/actions/runs/(\d+)/rerun", args[-1]) if args[0] == "api" else None
        if match:
            assert args[1:3] == ["--method", "POST"], "a re-run is a POST"
            if isinstance(self.rerun, ApiError):
                raise self.rerun
            return ""
        match = re.fullmatch(r"repos/owner/repo/issues/(\d+)/parent", args[1]) if args[0] == "api" else None
        if match:
            parent = self.parents.get(int(match.group(1)), NO_PARENT)
            if isinstance(parent, ApiError):
                raise parent
            return json.dumps({"number": parent, "state": "open"})
        match = re.fullmatch(r"repos/owner/repo/issues/(\d+)/timeline", args[-1]) if args[0] == "api" else None
        if match:
            assert args[1:3] == ["--paginate", "--slurp"], "the timeline must be read in full, as pages"
            number = int(match.group(1))
            owner = DEFAULT_ENV["OWNER_LOGIN"]
            timeline = self.timelines.get(number, [labeled(name, owner) for name in self.issues.get(number, ([], ""))[0]])
            if isinstance(timeline, ApiError):
                raise timeline
            return json.dumps([timeline])  # --slurp: one array per page
        raise AssertionError(f"unexpected gh call: {args!r}")

    def review_calls(self):
        return [call for call in self.calls if call[0] == "gh" and call[1] == "api" and call[-1].endswith("/reviews")]

    def rerun_calls(self):
        return [call[-1] for call in self.calls if call[0] == "gh" and call[1] == "api" and call[-1].endswith("/rerun")]

    def actions_calls(self):
        return [call for call in self.calls if call[0] == "gh" and call[1] == "api" and "/actions/" in call[-1]]

    def commit_calls(self):
        return [call for call in self.calls if call[0] == "gh" and call[1] == "api" and "/commits?" in call[-1]]

    def timeline_calls(self):
        return [call for call in self.calls if call[0] == "gh" and call[1] == "api" and call[-1].endswith("/timeline")]


def run_policy(fake, **env):
    """Execute the embedded checker against `fake`; return (exit code, printed output)."""
    environment = {**DEFAULT_ENV, **env}
    output = io.StringIO()
    with mock.patch.dict(os.environ, environment, clear=False), mock.patch.object(subprocess, "run", fake), \
            mock.patch("time.sleep", getattr(fake, "sleeps", []).append), contextlib.redirect_stdout(output):
        try:
            exec(compile(embedded_script(), str(WORKFLOW), "exec"), {"__name__": "pr_policy"})
        except SystemExit as stop:
            code = stop.code
        else:
            raise AssertionError("the checker must end with sys.exit")
    return (0 if code is None else int(code)), output.getvalue()


def review(login="grok-conductor[bot]", state="APPROVED", commit=HEAD, body="", at="2026-11-23T10:00:00Z", association=None, kind=None):
    """One entry of the pull request reviews list, as the REST API returns it. By default a
    login ending in `[bot]` is an app's bot with no association, `author` is the repository
    owner's own login, and any other login is a collaborator."""
    bot = login.endswith("[bot]")
    if association is None:
        association = "NONE" if bot else "OWNER" if login.lower() == "author" else "COLLABORATOR"
    return {"user": {"login": login, "type": kind or ("Bot" if bot else "User")}, "state": state, "commit_id": commit,
            "body": body, "submitted_at": at, "author_association": association}


def ready(*extra, priority="P2", category="kind:chore"):
    return [label for label in (priority, category, "status:ready", *extra) if label]


class PolicyTest(unittest.TestCase):
    def assertRejected(self, fake, message, **env):
        code, output = run_policy(fake, **env)
        self.assertEqual(code, 1, output)
        self.assertIn("::error::", output)
        self.assertIn(message, output)
        return output

    def assertAccepted(self, fake, **env):
        code, output = run_policy(fake, **env)
        self.assertEqual(code, 0, output)
        self.assertNotIn("::error::", output)
        return output


class ClosingTaskTests(PolicyTest):
    def test_valid_open_ready_task_is_accepted(self):
        output = self.assertAccepted(FakeGitHub())
        self.assertIn("Task #42 is ready", output)

    def test_repeated_references_to_the_same_task_count_once(self):
        self.assertAccepted(FakeGitHub(body="Closes #42\n\nFixes #42, resolves #42."))

    def test_missing_task_link_is_rejected(self):
        self.assertRejected(FakeGitHub(body="No task here."), "must name the task it closes")

    def test_quoted_closing_keywords_do_not_count(self):
        # The motivating cases: #92 and #94 (2026-11-07) went red on a closing keyword that the
        # body only quoted. Plain text names #10; the code span and the blockquote name nothing.
        body = "Closes #10\n\nThe check rejects a body with `closes #11` in it.\n\n> fixes #12 was the old wording\n"
        fake = FakeGitHub(body=body, issues={10: (ready(), "OPEN"), 11: (ready(), "OPEN"), 12: (ready(), "OPEN")})
        output = self.assertAccepted(fake)
        self.assertIn("Task #10 is ready", output)
        self.assertEqual([call[3] for call in fake.calls if call[1] == "issue"], ["10"])

    def test_fenced_code_blocks_are_quoted_text(self):
        body = "Closes #42\n\n```\nCloses #43\nresolves #44\n```\n\n~~~text\nfixes #45\n~~~\n"
        self.assertAccepted(FakeGitHub(body=body))

    def test_unterminated_fence_quotes_to_the_end_of_the_body(self):
        self.assertAccepted(FakeGitHub(body="Closes #42\n\n```\nCloses #43\n"))

    def test_longer_closing_fence_ends_the_block(self):
        # #155: CommonMark closes a fence on a run at least as long as the opener. The exact
        # backreference used to miss it and quote the rest of the body, dropping "Closes #42".
        self.assertAccepted(FakeGitHub(body="```\nCloses #43\n````\n\nCloses #42\n"))
        self.assertAccepted(FakeGitHub(body="~~~\nfixes #43\n~~~~~\nCloses #42\n"))

    def test_shorter_or_other_character_fence_does_not_close_the_block(self):
        # Inside a four-backtick block, a three-backtick line or a tilde line is content.
        self.assertAccepted(FakeGitHub(body="Closes #42\n\n````\n```\nCloses #43\n~~~~\nfixes #44\n````\n"))

    def test_double_backtick_span_holding_a_backtick_is_quoted_text(self):
        self.assertAccepted(FakeGitHub(body="Closes #42\n\nWrite `` `closes #43` `` in the hint.\n"))

    def test_plain_keyword_after_a_quoted_one_still_counts(self):
        fake = FakeGitHub(body="`closes #43`\n\n> fixes #44\n\nCloses #42\n")
        self.assertAccepted(fake)
        fake = FakeGitHub(body="`closes #42`\n\n> fixes #42\n")
        self.assertRejected(fake, "must name the task it closes")

    def test_quoted_keyword_naming_a_second_task_no_longer_splits_the_pull_request(self):
        fake = FakeGitHub(body="Closes #42\n\n`Closes #43`", issues={42: (ready(), "OPEN"), 43: (ready(), "OPEN")})
        self.assertAccepted(fake)
        fake = FakeGitHub(body="Closes #42 and closes #43\n\n`fixes #44`", issues={42: (ready(), "OPEN"), 43: (ready(), "OPEN")})
        self.assertRejected(fake, "names 2 distinct tasks (#42, #43)")

    def test_quoted_reference_does_not_count_on_the_record_only_path(self):
        fake = FakeGitHub(body="Refs #42\n\n`refs #43`", files=["docs/adr/0008-example.md"])
        self.assertAccepted(fake)

    def test_nonexistent_task_is_one_error_line_with_the_gh_output(self):
        # `gh issue view` on a number that is no issue exits nonzero; the check reports it,
        # never a traceback.
        fake = FakeGitHub(body="Closes #4242")
        output = self.assertRejected(fake, "Could not read task #4242 (gh issue view exit 1)")
        self.assertIn("Could not resolve to an issue or pull request (HTTP 404)", output)
        self.assertNotIn("Traceback", output)
        self.assertEqual(output.count("::error::"), 1)

    def test_two_distinct_closing_tasks_are_rejected(self):
        fake = FakeGitHub(body="Closes #42 and closes #43", issues={42: (ready(), "OPEN"), 43: (ready(), "OPEN")})
        self.assertRejected(fake, "exactly one task")

    def test_missing_ready_label_is_rejected(self):
        self.assertRejected(FakeGitHub(issues={42: (["P2", "kind:chore"], "OPEN")}), "missing the 'status:ready' label")

    def test_closed_task_is_rejected(self):
        self.assertRejected(FakeGitHub(issues={42: (ready(), "CLOSED")}), "closed")

    def test_owner_blocked_task_cannot_be_closed_by_a_pull_request(self):
        self.assertRejected(FakeGitHub(issues={42: (["blocked:owner", "kind:chore", "status:ready"], "OPEN")}), "blocked:owner")

    def test_blocked_is_a_flag_and_never_stands_in_for_a_priority(self):
        output = self.assertRejected(FakeGitHub(issues={42: (["blocked:owner", "kind:chore", "status:ready"], "OPEN")}), "no priority label")
        self.assertIn("no pull request closes an owner-blocked record", output)
        self.assertEqual(output.count("::error::"), 1, output)

    def test_blocked_task_with_a_priority_still_cannot_be_closed_and_fails_with_one_error_line(self):
        output = self.assertRejected(FakeGitHub(issues={42: (ready("blocked:owner"), "OPEN")}), "carries 'blocked:owner'; no pull request closes an owner-blocked record")
        self.assertNotIn("no priority label", output)
        self.assertEqual(output.count("::error::"), 1, output)

    def test_tracking_record_cannot_be_closed_by_a_pull_request(self):
        self.assertRejected(FakeGitHub(issues={42: (["kind:tracking", "status:ready"], "OPEN")}), "kind:tracking")

    def test_missing_priority_is_rejected(self):
        self.assertRejected(FakeGitHub(issues={42: (["kind:chore", "status:ready"], "OPEN")}), "no priority label")

    def test_two_priorities_are_rejected(self):
        self.assertRejected(FakeGitHub(issues={42: (ready("P1"), "OPEN")}), "more than one priority label")

    def test_missing_category_is_rejected(self):
        self.assertRejected(FakeGitHub(issues={42: (["P2", "status:ready"], "OPEN")}), "expected exactly one 'kind:' label, found 0")

    def test_two_categories_are_rejected(self):
        self.assertRejected(FakeGitHub(issues={42: (ready("kind:docs"), "OPEN")}), "expected exactly one 'kind:' label, found 2")

    def test_custom_label_names_are_honoured(self):
        custom = dict(PRIORITY_LABELS="prio/high,prio/low", BLOCKED_LABEL="waiting", CATEGORY_PREFIX="type/",
                      TRACKING_LABEL="type/epic", READY_LABEL="go")
        self.assertAccepted(FakeGitHub(issues={42: (["prio/low", "type/docs", "go"], "OPEN")}), **custom)
        output = self.assertRejected(FakeGitHub(), "missing the 'go' label", **custom)
        self.assertIn("expected exactly one 'type/' label, found 0", output)
        self.assertRejected(FakeGitHub(issues={42: (["prio/low", "type/epic", "go"], "OPEN")}), "type/epic", **custom)

    def test_invalid_approval_mode_is_rejected(self):
        self.assertRejected(FakeGitHub(), "CONDUCTOR_APPROVAL_MODE must be 'manual' or 'auto'", APPROVAL_MODE="later")


class ApprovalModeTests(PolicyTest):
    def test_manual_mode_accepts_any_base(self):
        self.assertAccepted(FakeGitHub(), APPROVAL_MODE="manual", INTEGRATION_BRANCH="dev", BASE_REF="main")

    def test_auto_mode_rejects_a_wrong_integration_target(self):
        self.assertRejected(FakeGitHub(), "target the integration branch 'dev'", APPROVAL_MODE="auto",
                            INTEGRATION_BRANCH="dev", BASE_REF="main")

    def test_auto_mode_accepts_the_integration_branch(self):
        output = self.assertAccepted(FakeGitHub(), APPROVAL_MODE="auto", INTEGRATION_BRANCH="dev", BASE_REF="dev")
        self.assertIn("base 'dev' accepted", output)

    def test_auto_mode_accepts_the_promotion_into_the_default_branch(self):
        output = self.assertAccepted(FakeGitHub(), APPROVAL_MODE="auto", INTEGRATION_BRANCH="dev",
                                     BASE_REF="main", HEAD_REF="dev", DEFAULT_BRANCH="main")
        self.assertIn("(promotion)", output)


class ParentTests(PolicyTest):
    def _with_parent(self, parent_labels, parent_state="OPEN"):
        return FakeGitHub(issues={42: (ready(), "OPEN"), 7: (parent_labels, parent_state)}, parents={42: 7})

    def test_confirmed_no_parent_response_is_accepted(self):
        fake = FakeGitHub(parents={42: NO_PARENT})
        output = self.assertAccepted(fake)
        self.assertNotIn("Parent", output)
        self.assertIn(["gh", "api", "repos/owner/repo/issues/42/parent"], fake.calls)

    def test_open_readied_parent_is_accepted_in_auto(self):
        output = self.assertAccepted(self._with_parent(["P1", "kind:feature", "status:ready"]), APPROVAL_MODE="auto")
        self.assertIn("Parent #7 of task #42 is open", output)

    def test_tracking_parent_without_priority_is_accepted(self):
        self.assertAccepted(self._with_parent(["kind:tracking", "status:ready"]), APPROVAL_MODE="auto")

    def test_parent_may_carry_a_priority_and_the_blocked_flag_together(self):
        self.assertAccepted(self._with_parent(["P1", "blocked:owner", "kind:feature", "status:ready"]), APPROVAL_MODE="auto")
        self.assertAccepted(self._with_parent(["P1", "blocked:owner", "kind:feature"]))

    def test_blocked_parent_without_a_priority_is_rejected(self):
        output = self.assertRejected(self._with_parent(["blocked:owner", "kind:feature", "status:ready"]), "Parent #7 of task #42 is not a workable record: no priority label")
        self.assertIn("'blocked:owner' is a flag beside a priority, not in place of one", output)
        self.assertEqual(output.count("::error::"), 1, output)

    def test_closed_parent_is_rejected(self):
        self.assertRejected(self._with_parent(["P1", "kind:feature", "status:ready"], "CLOSED"), "parent is closed")

    def test_unready_parent_is_rejected_in_auto_but_not_in_manual(self):
        self.assertRejected(self._with_parent(["P1", "kind:feature"]), "inherits readiness only from a readied parent",
                            APPROVAL_MODE="auto")
        self.assertAccepted(self._with_parent(["P1", "kind:feature"]), APPROVAL_MODE="manual")

    def test_parent_with_two_categories_is_rejected(self):
        self.assertRejected(self._with_parent(["P1", "kind:feature", "kind:docs", "status:ready"]),
                            "Parent #7 of task #42 is not a workable record")

    def test_parent_permission_failure_fails_the_check(self):
        fake = FakeGitHub(parents={42: ApiError(1, "gh: Resource not accessible by integration (HTTP 403)\n")})
        output = self.assertRejected(fake, "Could not read the parent of task #42")
        self.assertIn("HTTP 403", output)

    def test_parent_server_failure_fails_the_check(self):
        fake = FakeGitHub(parents={42: ApiError(1, "gh: Server Error (HTTP 502)\n")})
        self.assertRejected(fake, "Could not read the parent of task #42")

    def test_parent_transport_failure_fails_the_check(self):
        fake = FakeGitHub(parents={42: ApiError(4, "error connecting to api.github.com\n")})
        self.assertRejected(fake, "Could not read the parent of task #42")


class ReviewRequiredTests(PolicyTest):
    """ADR 0011, #126: a review is a native GitHub review of the head, read from the pull
    request's reviews. Nothing in the pull request body records one."""

    def _labelled(self, reviews=None, body="Closes #42"):
        return FakeGitHub(body=body, issues={42: (ready("review:required"), "OPEN")}, reviews=reviews)

    def _one_error_naming_the_head(self, output):
        errors = [line for line in output.splitlines() if line.startswith("::error::")]
        self.assertEqual(len(errors), 1, output)
        self.assertIn(f"head {HEAD}", errors[0])
        self.assertNotIn("Traceback", output)

    def test_no_review_is_rejected_with_one_error_naming_the_head(self):
        output = self.assertRejected(self._labelled(), "no review of the head counts (none submitted)")
        self.assertIn("Task #42 requires a review (it carries 'review:required')", output)
        self._one_error_naming_the_head(output)

    def test_approving_review_of_the_head_is_accepted(self):
        output = self.assertAccepted(self._labelled([review()]))
        self.assertIn(f"Review of head {HEAD} by grok-conductor[bot] (approved).", output)

    def test_comment_review_of_the_head_by_another_login_is_accepted(self):
        output = self.assertAccepted(self._labelled([review(state="COMMENTED", body="No findings.")]))
        self.assertIn("(commented)", output)

    def test_body_review_line_is_no_longer_read(self):
        body = f"Closes #42\n\n## Review\n\n- Reviewer: Codex, reviewed SHA: {HEAD}\n"
        self._one_error_naming_the_head(self.assertRejected(self._labelled(body=body), "no review of the head counts"))

    def test_review_of_an_earlier_commit_does_not_count(self):
        output = self.assertRejected(self._labelled([review(commit=STALE)]), "no review of the head counts (1 of an earlier commit)")
        self._one_error_naming_the_head(output)

    def test_new_push_turns_the_check_red_again(self):
        fake = self._labelled([review()])
        self.assertAccepted(fake)
        fake.head = "c" * 40
        fake.head_pulls = [{"number": 7, "state": "open", "head": {"sha": fake.head}}]
        output = self.assertRejected(fake, "no review of the head counts (1 of an earlier commit)", HEAD_SHA=fake.head)
        self.assertIn(f"head {fake.head}", output)

    def test_head_comparison_ignores_case(self):
        self.assertAccepted(self._labelled([review(commit=HEAD.upper())]))

    def test_request_for_changes_on_the_head_is_rejected(self):
        output = self.assertRejected(self._labelled([review(state="CHANGES_REQUESTED")]),
                                     "the latest verdict of grok-conductor[bot] on the head requests changes")
        self._one_error_naming_the_head(output)

    def test_each_reviewers_latest_verdict_on_the_head_decides(self):
        approved_then_changes = [review(at="2026-11-23T10:00:00Z"), review(login="codex[bot]", state="CHANGES_REQUESTED", at="2026-11-23T11:00:00Z")]
        self.assertRejected(self._labelled(approved_then_changes), "the latest verdict of codex[bot] on the head requests changes")
        changes_then_approved = [review(state="CHANGES_REQUESTED", at="2026-11-23T10:00:00Z"), review(at="2026-11-23T11:00:00Z")]
        self.assertAccepted(self._labelled(changes_then_approved))

    def test_request_for_changes_on_an_earlier_commit_does_not_hold_a_reviewed_head(self):
        self.assertAccepted(self._labelled([review(state="CHANGES_REQUESTED", commit=STALE), review(at="2026-11-23T11:00:00Z")]))

    def test_pending_and_dismissed_reviews_do_not_count(self):
        self.assertRejected(self._labelled([review(state="PENDING"), review(state="DISMISSED")]), "no review of the head counts (none submitted)")

    def test_author_login_review_without_the_reviewer_line_does_not_count(self):
        output = self.assertRejected(self._labelled([review(login="author", state="COMMENTED", body="Looks fine to me.")]),
                                     "1 of the head by the pull request author's login without a first line 'Reviewer: <runtime>'")
        self._one_error_naming_the_head(output)

    def test_author_login_review_starting_with_the_reviewer_line_counts(self):
        output = self.assertAccepted(self._labelled([review(login="Author", state="COMMENTED", body="Reviewer: Codex\n\nNo findings.")]))
        self.assertIn(f"Review of head {HEAD} by Author (commented).", output)

    def test_reviewer_line_must_start_the_text_and_name_a_runtime(self):
        for body in ("No findings.\nReviewer: Codex", "Reviewer:", "Reviewer:\nCodex", None):
            with self.subTest(body=body):
                self.assertRejected(self._labelled([review(login="author", state="COMMENTED", body=body)]), "no review of the head counts")

    def test_author_login_reply_does_not_override_a_request_for_changes(self):
        reviews = [review(state="CHANGES_REQUESTED", at="2026-11-23T10:00:00Z"), review(login="author", state="COMMENTED", at="2026-11-23T11:00:00Z")]
        self.assertRejected(self._labelled(reviews), "requests changes")

    def test_comment_review_never_clears_a_request_for_changes(self):
        changes = review(state="CHANGES_REQUESTED", at="2026-11-23T10:00:00Z")
        later = dict(state="COMMENTED", at="2026-11-23T11:00:00Z")
        for name, comment in (("the reviewer's own inline reply", review(**later)),
                              ("another reviewer's comment", review(login="codex[bot]", body="lgtm", **later)),
                              ("the author's Reviewer line", review(login="author", body="Reviewer: claude\n\nFine.", **later))):
            with self.subTest(comment=name):
                self.assertRejected(self._labelled([changes, comment]), "the latest verdict of grok-conductor[bot] on the head requests changes")

    def test_another_reviewers_approval_does_not_clear_a_request_for_changes(self):
        reviews = [review(state="CHANGES_REQUESTED", at="2026-11-23T10:00:00Z"), review(login="codex[bot]", at="2026-11-23T11:00:00Z")]
        self.assertRejected(self._labelled(reviews), "the latest verdict of grok-conductor[bot] on the head requests changes")

    def test_dismissed_request_for_changes_no_longer_holds_the_head(self):
        self.assertAccepted(self._labelled([review(state="DISMISSED", at="2026-11-23T10:00:00Z"), review(login="codex[bot]", at="2026-11-23T11:00:00Z")]))

    def test_verdict_order_follows_the_submission_time_not_the_list_order(self):
        reviews = [review(at="2026-11-23T11:00:00Z"), review(state="CHANGES_REQUESTED", at="2026-11-23T10:00:00Z")]
        self.assertAccepted(self._labelled(reviews))

    def test_review_by_an_outside_account_does_not_count(self):
        for association in ("NONE", "CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", "FIRST_TIMER", "MANNEQUIN", "", None):
            for state in ("COMMENTED", "APPROVED"):
                with self.subTest(association=association, state=state):
                    outsider = review(login="passer-by", state=state, body="lgtm", association=association or "")
                    if association is None:
                        del outsider["author_association"]
                    output = self.assertRejected(self._labelled([outsider]), "1 of the head by an account that is neither an owner, member or collaborator of owner/repo nor a bot")
                    self._one_error_naming_the_head(output)

    def test_outside_account_can_neither_hold_nor_clear_a_head(self):
        outsider = review(login="passer-by", state="CHANGES_REQUESTED", association="NONE", at="2026-11-23T11:00:00Z")
        self.assertAccepted(self._labelled([review(), outsider]))
        self.assertRejected(self._labelled([review(state="CHANGES_REQUESTED"), review(login="passer-by", association="NONE", at="2026-11-23T11:00:00Z")]),
                            "requests changes")

    def test_owner_member_collaborator_and_bot_reviews_count(self):
        for association in ("OWNER", "MEMBER", "COLLABORATOR", "member"):
            with self.subTest(association=association):
                self.assertAccepted(self._labelled([review(login="colleague", association=association)]))
        self.assertAccepted(self._labelled([review(login="grok-conductor[bot]", association="NONE")]))
        self.assertRejected(self._labelled([review(login="looks-like[bot]", association="NONE", kind="User")]), "no review of the head counts")

    def test_review_without_a_commit_does_not_count(self):
        for commit in (None, ""):
            with self.subTest(commit=commit):
                self.assertRejected(self._labelled([review(commit=commit)]), "no review of the head counts (1 of an earlier commit)")

    def test_author_login_comparison_ignores_case(self):
        unnamed = review(login="AUTHOR", state="COMMENTED", body="Looks fine.", association="OWNER")
        self.assertRejected(self._labelled([unnamed]), "by the pull request author's login without a first line")
        self.assertRejected(self._labelled([review(login="author", state="COMMENTED", body="Looks fine.")]), "by the pull request author's login without a first line", PR_AUTHOR="Author")

    def test_review_on_the_second_page_is_read(self):
        reviews = [review(commit=STALE) for _ in range(PAGE)] + [review()]
        self.assertAccepted(self._labelled(reviews))

    def test_task_that_requires_no_review_reads_no_reviews(self):
        fake = FakeGitHub(reviews=ApiError(1, "gh: must not be called\n"))
        output = self.assertAccepted(fake)
        self.assertIn("Task #42 requires no review of the head", output)
        self.assertEqual(fake.review_calls(), [])

    def test_custom_review_label_is_honoured(self):
        fake = FakeGitHub(issues={42: (ready("needs-review"), "OPEN")})
        self.assertRejected(fake, "it carries 'needs-review'", REVIEW_REQUIRED_LABEL="needs-review")

    def test_record_only_reference_to_a_task_that_requires_review_needs_one(self):
        fake = FakeGitHub(body="Refs #42", files=["docs/adr/0008-example.md"], issues={42: (ready("review:required"), "OPEN")})
        self.assertRejected(fake, "no review of the head counts")
        fake.reviews = [review()]
        self.assertAccepted(fake)


class ReviewRequirementTests(PolicyTest):
    """#126 criterion 4: the check computes when a review is required. A priority above the
    assistant cap or an owner-only category requires one in both approval modes, with or
    without the review label; the label adds the requirement to any other task."""

    CAPPED = dict(PRIORITY_CAP="P2", OWNER_CATEGORIES="kind:security")

    def _task(self, labels, reviews=None):
        return FakeGitHub(issues={42: (labels, "OPEN")}, reviews=reviews)

    def test_priority_above_the_cap_requires_a_review_without_the_label_in_both_modes(self):
        for mode in ("manual", "auto"):
            for priority in ("P0", "P1"):
                with self.subTest(mode=mode, priority=priority):
                    output = self.assertRejected(self._task(ready(priority=priority)), "no review of the head counts", APPROVAL_MODE=mode, **self.CAPPED)
                    self.assertIn(f"Task #42 requires a review (priority {priority} is above the assistant cap P2)", output)
                    self.assertAccepted(self._task(ready(priority=priority), [review()]), APPROVAL_MODE=mode, **self.CAPPED)

    def test_owner_only_category_requires_a_review_at_any_priority_in_both_modes(self):
        for mode in ("manual", "auto"):
            with self.subTest(mode=mode):
                labels = ready(priority="P3", category="kind:security")
                output = self.assertRejected(self._task(labels), "category kind:security is owner-only", APPROVAL_MODE=mode, **self.CAPPED)
                self.assertIn("requires a review", output)
                self.assertAccepted(self._task(labels, [review()]), APPROVAL_MODE=mode, **self.CAPPED)

    def test_task_at_or_below_the_cap_requires_none_and_the_label_adds_it(self):
        for mode in ("manual", "auto"):
            for priority in ("P2", "P3"):
                with self.subTest(mode=mode, priority=priority):
                    fake = self._task(ready(priority=priority))
                    self.assertAccepted(fake, APPROVAL_MODE=mode, **self.CAPPED)
                    self.assertEqual(fake.review_calls(), [])
                    self.assertRejected(self._task(ready("review:required", priority=priority)), "it carries 'review:required'", APPROVAL_MODE=mode, **self.CAPPED)

    def test_cap_other_than_p2_moves_the_requirement(self):
        self.assertAccepted(self._task(ready(priority="P1")), PRIORITY_CAP="P1")
        self.assertRejected(self._task(ready(priority="P0")), "priority P0 is above the assistant cap P1", PRIORITY_CAP="P1")
        self.assertRejected(self._task(ready(priority="P2")), "priority P2 is above the assistant cap P3", PRIORITY_CAP="P3")

    def test_custom_priority_scale_orders_the_requirement(self):
        scale = dict(PRIORITY_LABELS="urgent,normal,low", PRIORITY_CAP="normal")
        self.assertRejected(self._task(ready(priority="urgent")), "priority urgent is above the assistant cap normal", **scale)
        self.assertAccepted(self._task(ready(priority="normal")), **scale)

    def test_cap_and_categories_unset_leave_only_the_label(self):
        for mode in ("manual", "auto"):
            with self.subTest(mode=mode):
                fake = self._task(ready(priority="P0", category="kind:security"))
                self.assertAccepted(fake, APPROVAL_MODE=mode)
                self.assertEqual(fake.review_calls(), [])
                self.assertRejected(self._task(ready("review:required", priority="P0")), "it carries 'review:required'", APPROVAL_MODE=mode)

    def test_every_reason_is_named(self):
        labels = ready("review:required", priority="P0", category="kind:security")
        self.assertRejected(self._task(labels), "priority P0 is above the assistant cap P2; category kind:security is owner-only; it carries 'review:required'", **self.CAPPED)


class ReviewFailureTests(PolicyTest):
    """#126 criterion 8: every failure the review code can meet is one `::error::` line, never
    a traceback, and fails the check."""

    def _labelled(self, reviews=None):
        return FakeGitHub(issues={42: (ready("review:required"), "OPEN")}, reviews=reviews)

    def _closed(self, fake, message, **env):
        output = self.assertRejected(fake, message, **env)
        self.assertEqual(sum(line.startswith("::error::") for line in output.splitlines()), 1, output)
        self.assertNotIn("Traceback", output)
        return output

    def test_unreadable_reviews_fail_the_check(self):
        for error in (ApiError(1, "gh: Resource not accessible by integration (HTTP 403)\n"), ApiError(1, "gh: Server Error (HTTP 502)\n"),
                      ApiError(1, "error connecting to api.github.com\n"), ApiError(1, "")):
            with self.subTest(error=error.stderr):
                output = self._closed(self._labelled(error), "could not read the reviews of the pull request (gh api exit 1)")
                self.assertIn(error.stderr.strip() or "no output", output)

    def test_unparseable_reviews_fail_the_check(self):
        for raw in ("not json", '{"message": "Bad credentials"}', "[[1]]", '[["review"]]', "null", '[[{"state": 5}]]'):
            with self.subTest(raw=raw):
                self._closed(self._labelled(raw), "could not parse the reviews of the pull request")

    def test_review_without_a_user_does_not_count(self):
        ghost = {"user": None, "state": "APPROVED", "commit_id": HEAD, "body": None, "submitted_at": None, "author_association": "MEMBER"}
        self._closed(self._labelled([ghost]), "no review of the head counts")

    def test_missing_head_fails_the_check_before_any_lookup(self):
        for head in ("", "  ", "not-a-sha", HEAD[:39]):
            with self.subTest(head=head):
                fake = self._labelled([review()])
                self._closed(fake, "The event carries no pull request head SHA", HEAD_SHA=head)
                self.assertEqual(fake.calls, [])

    def test_missing_author_fails_the_check_when_a_review_is_required(self):
        fake = self._labelled([review()])
        self._closed(fake, "the event carries no pull request author", PR_AUTHOR="")
        self.assertEqual(fake.review_calls(), [])

    def test_missing_author_is_not_read_when_no_review_is_required(self):
        self.assertAccepted(FakeGitHub(), PR_AUTHOR="")


def workflow_run(run_id=800, conclusion="failure", status="completed", number=10, attempt=1):
    """One entry of a workflow's run list, as the REST API returns it."""
    return {"id": run_id, "run_number": number, "run_attempt": attempt, "event": "pull_request", "head_sha": HEAD,
            "status": status, "conclusion": conclusion if status == "completed" else None}


class ReviewRerunTests(PolicyTest):
    """#142: the merge follows the `pull_request` run on the head, so the review-event run
    re-runs that one when the two conclude differently, and says so when it cannot."""

    REVIEW_EVENT = {"GITHUB_EVENT_NAME": "pull_request_review"}

    def _fake(self, reviews=(), runs=(), labels=None):
        fake = FakeGitHub(issues={42: (labels or ready("review:required"), "OPEN")}, reviews=list(reviews))
        fake.runs = list(runs)
        return fake

    def _closed(self, fake, message):
        output = self.assertRejected(fake, message, **self.REVIEW_EVENT)
        self.assertEqual(sum(line.startswith("::error::") for line in output.splitlines()), 1, output)
        self.assertNotIn("Traceback", output)
        return output

    def test_a_passing_review_reruns_the_red_pull_request_run(self):
        fake = self._fake([review()], [workflow_run(800, "failure")])
        output = self.assertAccepted(fake, **self.REVIEW_EVENT)
        self.assertEqual(fake.rerun_calls(), ["repos/owner/repo/actions/runs/800/rerun"])
        self.assertIn("Re-ran 'pull_request' run 800", output)

    def test_a_request_for_changes_reruns_the_green_pull_request_run(self):
        fake = self._fake([review(state="CHANGES_REQUESTED")], [workflow_run(800, "success")])
        output = self._closed(fake, "requests changes")
        self.assertEqual(fake.rerun_calls(), ["repos/owner/repo/actions/runs/800/rerun"])
        self.assertIn("Re-ran 'pull_request' run 800", output)

    def test_a_run_that_already_agrees_is_left_alone(self):
        for reviews, conclusion, code in (([review()], "success", 0), ([], "failure", 1)):
            with self.subTest(conclusion=conclusion):
                fake = self._fake(reviews, [workflow_run(800, conclusion)])
                self.assertEqual(run_policy(fake, **self.REVIEW_EVENT)[0], code)
                self.assertEqual(fake.rerun_calls(), [])

    def test_a_cancelled_or_skipped_run_is_rerun(self):
        for conclusion in ("cancelled", "skipped", "timed_out", None):
            with self.subTest(conclusion=conclusion):
                fake = self._fake([review()], [dict(workflow_run(800), conclusion=conclusion)])
                self.assertAccepted(fake, **self.REVIEW_EVENT)
                self.assertEqual(len(fake.rerun_calls()), 1)

    def test_the_newest_run_and_attempt_is_the_one_compared(self):
        runs = [workflow_run(801, "success", number=11), workflow_run(800, "failure", number=10), workflow_run(799, "failure", number=9)]
        fake = self._fake([review()], runs)
        self.assertAccepted(fake, **self.REVIEW_EVENT)
        self.assertEqual(fake.rerun_calls(), [])
        fake = self._fake([review()], list(reversed(runs)) + [workflow_run(802, "failure", number=12)])
        self.assertAccepted(fake, **self.REVIEW_EVENT)
        self.assertEqual(fake.rerun_calls(), ["repos/owner/repo/actions/runs/802/rerun"])

    def test_a_run_in_progress_is_waited_for_before_it_is_compared(self):
        fake = self._fake([review()], [workflow_run(800, "failure")])
        fake.run_polls = [[workflow_run(800, status="in_progress")], [workflow_run(800, status="queued")]]
        self.assertAccepted(fake, **self.REVIEW_EVENT)
        self.assertEqual(fake.sleeps, [10, 10])
        self.assertEqual(len(fake.rerun_calls()), 1)

    def test_a_run_that_never_completes_fails_the_check(self):
        fake = self._fake([review()], [workflow_run(800, status="in_progress")])
        self._closed(fake, "'pull_request' run 800 on the head is still in_progress after three minutes")
        self.assertEqual(sum(fake.sleeps), 180)
        self.assertEqual(fake.rerun_calls(), [])

    def test_no_pull_request_run_on_the_head_fails_the_check(self):
        self._closed(self._fake([review()], []), "no 'pull_request' run of this workflow exists on head")

    def test_a_refused_rerun_fails_the_check(self):
        for error in (ApiError(1, "gh: Resource not accessible by integration (HTTP 403)\n"), ApiError(1, "gh: Server Error (HTTP 502)\n"), ApiError(1, "")):
            with self.subTest(error=error.stderr):
                fake = self._fake([review()], [workflow_run(800, "failure")])
                fake.rerun = error
                output = self._closed(fake, "could not re-run the 'pull_request' run of this check on the head (gh api exit 1: ")
                self.assertIn(error.stderr.strip() or "no output", output)
                self.assertIn("actions: write", output)

    def test_unreadable_runs_fail_the_check(self):
        for attribute, answer in (("current_run", ApiError(1, "gh: Not Found (HTTP 404)\n")), ("current_run", {"id": 900}),
                                  ("runs", ApiError(1, "gh: Server Error (HTTP 502)\n")), ("runs", "not json"),
                                  ("runs", '{"message": "Bad credentials"}'), ("runs", '{"workflow_runs": [5]}'),
                                  ("runs", '{"workflow_runs": [{"id": 1}]}'), ("runs", "null")):
            with self.subTest(attribute=attribute, answer=str(answer)):
                fake = self._fake([review()], [workflow_run(800, "failure")])
                setattr(fake, attribute, answer)
                self._closed(fake, "could not re-run the 'pull_request' run of this check on the head")
                self.assertEqual(fake.rerun_calls(), [])

    def test_a_failed_rerun_is_reported_beside_the_review_failure(self):
        fake = self._fake([review(state="CHANGES_REQUESTED")], [workflow_run(800, "success")])
        fake.rerun = ApiError(1, "gh: Resource not accessible by integration (HTTP 403)\n")
        code, output = run_policy(fake, **self.REVIEW_EVENT)
        self.assertEqual(code, 1, output)
        self.assertEqual(sum(line.startswith("::error::") for line in output.splitlines()), 2, output)

    def test_nothing_is_rerun_on_a_pull_request_event(self):
        fake = self._fake([review()], [workflow_run(800, "failure")])
        self.assertAccepted(fake)
        self.assertEqual(fake.actions_calls(), [])

    def test_nothing_is_rerun_when_the_task_requires_no_review(self):
        fake = self._fake([review()], [workflow_run(800, "failure")], labels=ready())
        self.assertAccepted(fake, **self.REVIEW_EVENT)
        self.assertEqual(fake.actions_calls(), [])

    def test_the_token_may_rerun_and_the_events_do_not_cancel_each_other(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^permissions:\n  actions: write\n  contents: read\n  issues: read\n  pull-requests: read\njobs:")
        self.assertIn("group: pr-policy-${{ github.event.pull_request.number }}-${{ github.event_name }}", text)

    def test_the_readme_caller_grants_the_rerun(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        caller = readme[readme.index("name: PR policy"):readme.index("pr-policy.yml@")]
        self.assertRegex(caller, r"(?m)^\s*permissions:\n\s*actions: write\n")


class WorkflowTriggerTests(unittest.TestCase):
    """#126 criterion 5 and #155: submitting, dismissing or editing a review runs the check,
    here and in an adopter's caller."""

    TRIGGER = re.compile(r"^(\s*)pull_request_review:\n\1  types: \[submitted, dismissed, edited\]$", re.M)

    def test_the_workflow_runs_on_a_submitted_review(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertRegex(text, self.TRIGGER)
        self.assertIn("PR_AUTHOR: ${{ github.event.pull_request.user.login }}", text)

    def test_the_readme_caller_runs_on_a_submitted_review(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        caller = readme[readme.index("name: PR policy"):readme.index("pr-policy.yml@")]
        self.assertRegex(caller, self.TRIGGER)

    def test_the_template_has_no_review_section(self):
        template = (ROOT / ".github" / "pull_request_template.md").read_text(encoding="utf-8")
        self.assertNotRegex(template, r"(?m)^##\s+Review\b")
        self.assertNotIn("reviewed SHA", template)
        self.assertRegex(template, r"(?m)^- Implementer runtime:")


class SharedHeadTests(PolicyTest):
    """One branch, one head, one pull request: a second open pull request at the same head
    commit would let its green check run satisfy branch protection for this one."""

    def _pull(self, number, state="open", sha=HEAD):
        return {"number": number, "state": state, "head": {"sha": sha}}

    def test_sole_pull_request_at_the_head_is_accepted(self):
        output = self.assertAccepted(FakeGitHub())
        self.assertIn(f"Head {HEAD} belongs to this pull request alone", output)

    def test_second_open_pull_request_at_the_same_head_is_rejected(self):
        fake = FakeGitHub(head_pulls=[self._pull(7), self._pull(8)])
        output = self.assertRejected(fake, "also the head of open pull request #8")
        self.assertIn("one branch, one head, one pull request", output)

    def test_shared_head_is_rejected_even_on_the_record_only_path(self):
        fake = FakeGitHub(body="Refs #42", files=["docs/adr/0008-example.md"], head_pulls=[self._pull(7), self._pull(9)])
        self.assertRejected(fake, "also the head of open pull request #9")

    def test_second_open_pull_request_on_the_second_page_is_rejected(self):
        # More than one page of pull requests at the head, the other open one past the first
        # page: an unpaginated lookup would stop at 30 and pass.
        pulls = [self._pull(7)] + [self._pull(100 + i, state="closed") for i in range(PAGE)] + [self._pull(8)]
        self.assertGreater(len(pulls), PAGE)
        fake = FakeGitHub(head_pulls=pulls)
        self.assertRejected(fake, "also the head of open pull request #8")
        self.assertEqual([call for call in fake.calls if call[-1].endswith("/pulls")],
                         [["gh", "api", "--paginate", "--slurp", f"repos/owner/repo/commits/{HEAD}/pulls"]])

    def test_many_closed_pull_requests_at_the_head_are_still_accepted(self):
        pulls = [self._pull(7)] + [self._pull(100 + i, state="closed") for i in range(PAGE + 5)]
        self.assertAccepted(FakeGitHub(head_pulls=pulls))

    def test_closed_pull_request_at_the_same_head_is_accepted(self):
        self.assertAccepted(FakeGitHub(head_pulls=[self._pull(7), self._pull(8, state="closed")]))

    def test_open_pull_request_that_merely_contains_the_commit_is_accepted(self):
        self.assertAccepted(FakeGitHub(head_pulls=[self._pull(7), self._pull(8, sha=STALE)]))

    def test_head_lookup_failure_fails_the_check(self):
        fake = FakeGitHub(head_pulls=ApiError(1, "gh: Resource not accessible by integration (HTTP 403)\n"))
        output = self.assertRejected(fake, f"Could not list the pull requests at head {HEAD}")
        self.assertIn("HTTP 403", output)


BOT = "dependabot[bot]"


def bot_commit(sha=HEAD, author=BOT, author_type="Bot", committer="web-flow", verified=True):
    """One entry of the pull request commits list, as the REST API returns it. By default a
    commit as Dependabot makes it: the bot is the author, GitHub's web-flow the committer,
    and GitHub signed it. `author=None` is a commit whose author email matches no account."""
    return {"sha": sha,
            "author": None if author is None else {"login": author, "type": author_type},
            "committer": None if committer is None else {"login": committer, "type": "User"},
            "commit": {"verification": {"verified": verified, "reason": "valid" if verified else "unsigned"}}}


class BotAuthorTests(PolicyTest):
    """ADR 0014 (#169): a repository may list bot authors whose pull requests need no task,
    and the exemption holds only while every commit on the pull request is that bot's own."""

    BOT_ENV = {"PR_AUTHOR": BOT, "PR_AUTHOR_TYPE": "Bot", "BOT_AUTHORS": BOT, "HEAD_REF": "dependabot/npm/qs-6.16.2"}
    NO_TASK = "The pull request body must name the task it closes"

    def _fake(self, commits=None, **kwargs):
        fake = FakeGitHub(body="Bumps qs from 6.16.0 to 6.16.2.", files=["package-lock.json"], **kwargs)
        fake.commits = [bot_commit()] if commits is None else commits
        return fake

    def test_unset_variable_leaves_a_bot_pull_request_failing_as_before(self):
        fake = self._fake()
        output = self.assertRejected(fake, self.NO_TASK, **{**self.BOT_ENV, "BOT_AUTHORS": ""})
        self.assertNotIn("exemption", output)
        self.assertEqual(fake.commit_calls(), [])

    def test_unlisted_bot_is_not_exempt(self):
        fake = self._fake()
        self.assertRejected(fake, self.NO_TASK, **{**self.BOT_ENV, "BOT_AUTHORS": "renovate[bot]"})
        self.assertEqual(fake.commit_calls(), [])

    def test_listed_bot_with_only_its_own_commits_passes_without_a_task(self):
        fake = self._fake(commits=[bot_commit(sha=STALE), bot_commit()])
        output = self.assertAccepted(fake, **self.BOT_ENV)
        lines = [line for line in output.splitlines() if "exemption" in line]
        self.assertEqual(len(lines), 1, output)
        self.assertIn("Bot author exemption (CONDUCTOR_BOT_AUTHORS, ADR 0014): dependabot[bot]", lines[0])
        self.assertIn("all 2 of its commits", lines[0])
        # no task, review or timeline is read for an exempt pull request
        self.assertEqual([call for call in fake.calls if call[1] in ("pr", "issue")], [])
        self.assertEqual(fake.review_calls() + fake.timeline_calls(), [])

    def test_the_list_is_comma_separated_and_case_insensitive(self):
        self.assertAccepted(self._fake(), **{**self.BOT_ENV, "BOT_AUTHORS": " renovate[bot] , Dependabot[bot] "})

    def test_a_bot_committing_as_itself_is_accepted(self):
        self.assertAccepted(self._fake(commits=[bot_commit(committer=BOT)]), **self.BOT_ENV)

    def test_one_commit_by_someone_else_ends_the_exemption(self):
        fake = self._fake(commits=[bot_commit(sha=STALE), bot_commit(author="alhanaei", author_type="User", committer="alhanaei")])
        output = self.assertRejected(fake, self.NO_TASK, **self.BOT_ENV)
        self.assertIn(f"Bot author exemption not applied to {BOT}: commit {HEAD[:12]} is by alhanaei, not by {BOT}. The usual rules hold.", output)

    def test_a_merge_commit_made_with_the_update_button_ends_the_exemption(self):
        # "Update branch" in the web interface: the person is the author, web-flow commits.
        fake = self._fake(commits=[bot_commit(sha=STALE), bot_commit(author="alhanaei", author_type="User")])
        self.assertRejected(fake, "is by alhanaei", **self.BOT_ENV)

    def test_a_mixed_pull_request_that_names_a_ready_task_follows_the_usual_rules(self):
        fake = self._fake(commits=[bot_commit(sha=STALE), bot_commit(author="alhanaei", author_type="User", committer="alhanaei")])
        fake.body = "Closes #42"
        output = self.assertAccepted(fake, **self.BOT_ENV)
        self.assertIn("exemption not applied", output)
        self.assertIn("Task #42 is ready", output)

    def test_a_forged_author_on_an_unsigned_commit_ends_the_exemption(self):
        # Anyone who can push to the bot's branch can write the bot's name and email into a
        # commit; GitHub then shows the bot as the author. Such a commit is not signed.
        fake = self._fake(commits=[bot_commit(sha=STALE), bot_commit(committer="alhanaei", verified=False)])
        self.assertRejected(fake, f"commit {HEAD[:12]} names {BOT} as its author but was committed by alhanaei", **self.BOT_ENV)

    def test_a_forged_author_signed_with_the_pushers_own_key_ends_the_exemption(self):
        fake = self._fake(commits=[bot_commit(committer="alhanaei", verified=True)])
        self.assertRejected(fake, "was committed by alhanaei", **self.BOT_ENV)

    def test_a_forged_author_and_committer_without_a_signature_ends_the_exemption(self):
        for committer in ("web-flow", BOT):
            with self.subTest(committer=committer):
                fake = self._fake(commits=[bot_commit(committer=committer, verified=False)])
                self.assertRejected(fake, "carries no signature GitHub verified", **self.BOT_ENV)

    def test_a_commit_matched_to_no_account_ends_the_exemption(self):
        fake = self._fake(commits=[bot_commit(author=None, committer=None)])
        self.assertRejected(fake, "an author GitHub matches to no account", **self.BOT_ENV)

    def test_a_user_account_carrying_the_bots_login_as_commit_author_is_not_the_bot(self):
        fake = self._fake(commits=[bot_commit(author_type="User")])
        self.assertRejected(fake, "exemption not applied", **self.BOT_ENV)

    def test_a_human_author_is_never_exempt_whatever_the_variable_holds(self):
        # The owner's own login in the list, and commits that look like a bot's.
        fake = self._fake(commits=[bot_commit(author="alhanaei", committer="alhanaei")])
        env = {**self.BOT_ENV, "PR_AUTHOR": "alhanaei", "PR_AUTHOR_TYPE": "User", "BOT_AUTHORS": f"alhanaei,{BOT}"}
        output = self.assertRejected(fake, self.NO_TASK, **env)
        self.assertIn("the account is of type User, not Bot; a person is never exempt", output)
        self.assertEqual(fake.commit_calls(), [])

    def test_the_author_is_read_from_the_event_not_from_the_pull_request_text(self):
        # A person's pull request whose text and branch claim to be the bot's.
        fake = self._fake()
        fake.body = "Author: dependabot[bot]\n\nSigned-off-by: dependabot[bot] <support@github.com>"
        env = {**self.BOT_ENV, "PR_AUTHOR": "alhanaei", "PR_AUTHOR_TYPE": "User"}
        output = self.assertRejected(fake, self.NO_TASK, **env)
        self.assertNotIn("exemption", output)
        self.assertEqual(fake.commit_calls(), [])
        script = embedded_script()
        self.assertIn('os.environ.get("PR_AUTHOR", "")', script)
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("PR_AUTHOR_TYPE: ${{ github.event.pull_request.user.type }}", text)
        self.assertIn("BOT_AUTHORS: ${{ vars.CONDUCTOR_BOT_AUTHORS }}", text)

    def test_an_event_without_the_author_type_is_not_exempt(self):
        self.assertRejected(self._fake(), "the account is of type unknown, not Bot", **{**self.BOT_ENV, "PR_AUTHOR_TYPE": ""})

    def test_single_head_rule_still_applies_to_an_exempt_pull_request(self):
        pulls = [{"number": 7, "state": "open", "head": {"sha": HEAD}}, {"number": 8, "state": "open", "head": {"sha": HEAD}}]
        fake = self._fake(head_pulls=pulls)
        output = self.assertRejected(fake, "also the head of open pull request #8", **self.BOT_ENV)
        self.assertNotIn("exemption", output)
        self.assertEqual(fake.commit_calls(), [])

    def test_base_branch_rule_in_auto_still_applies_to_an_exempt_pull_request(self):
        env = {**self.BOT_ENV, "APPROVAL_MODE": "auto", "INTEGRATION_BRANCH": "develop", "BASE_REF": "main"}
        self.assertRejected(self._fake(), "pull requests target the integration branch 'develop'", **env)

    def test_exempt_in_auto_and_on_a_review_event_without_a_rerun(self):
        fake = self._fake()
        self.assertAccepted(fake, **{**self.BOT_ENV, "APPROVAL_MODE": "auto", "GITHUB_EVENT_NAME": "pull_request_review"})
        self.assertEqual(fake.actions_calls(), [])

    def test_unreadable_commits_end_the_exemption(self):
        fake = self._fake(commits=ApiError(1, "gh: Resource not accessible by integration (HTTP 403)\n"))
        output = self.assertRejected(fake, "could not read the commits of the pull request", **self.BOT_ENV)
        self.assertIn("HTTP 403", output)
        self.assertIn(self.NO_TASK, output)

    def test_unparsable_commits_end_the_exemption(self):
        for raw in ("not json", json.dumps([[{"sha": HEAD, "author": "dependabot[bot]"}]]), json.dumps({"message": "x"})):
            with self.subTest(raw=raw):
                self.assertRejected(self._fake(commits=raw), self.NO_TASK, **self.BOT_ENV)

    def test_no_commits_or_a_list_that_misses_the_head_ends_the_exemption(self):
        self.assertRejected(self._fake(commits=[]), "the pull request lists no commit", **self.BOT_ENV)
        self.assertRejected(self._fake(commits=[bot_commit(sha=STALE)]), f"the commit list does not end at head {HEAD}", **self.BOT_ENV)

    def test_a_pull_request_at_the_commit_list_limit_is_not_exempt(self):
        commits = [bot_commit(sha=f"{index:040x}") for index in range(249)] + [bot_commit()]
        self.assertRejected(self._fake(commits=commits), "250 commits or more", **self.BOT_ENV)
        self.assertAccepted(self._fake(commits=commits[1:]), **self.BOT_ENV)

    def test_the_call_interface_is_unchanged(self):
        # A caller written for `v1` passes nothing and grants the same permissions: an input,
        # a secret or a new permission would be a `v2` change (ADR 0012).
        code = "".join(line for line in WORKFLOW.read_text(encoding="utf-8").splitlines(keepends=True) if not line.lstrip().startswith("#"))
        self.assertRegex(code, r"(?m)^  workflow_call:\n(?=\S)")
        self.assertRegex(code, r"(?m)^permissions:\n  actions: write\n  contents: read\n  issues: read\n  pull-requests: read\njobs:")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertTrue("`CONDUCTOR_BOT_AUTHORS`" in readme, "the README must document CONDUCTOR_BOT_AUTHORS")


class RecordOnlyReferenceTests(PolicyTest):
    def test_default_record_paths_name_no_handoff_file(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn(".conductor/HANDOFF.md", text)
        self.assertIn("vars.CONDUCTOR_RECORD_PATHS || 'docs/adr/'", text)

    def test_record_only_files_may_reference_the_task(self):
        fake = FakeGitHub(body="Refs #42", files=["docs/adr/0008-example.md", "docs/adr/README.md"])
        output = self.assertAccepted(fake)
        self.assertIn("Record-only pull request", output)

    def test_reference_with_a_non_record_file_is_rejected(self):
        self.assertRejected(FakeGitHub(body="Refs #42", files=["docs/adr/0008-example.md", "AGENTS.md"]),
                            "must name the task it closes")

    def test_reference_without_a_task_number_is_rejected(self):
        self.assertRejected(FakeGitHub(body="Record only.", files=["docs/adr/0008-example.md"]), "must name the task it closes")

    def test_reference_to_two_distinct_records_is_rejected(self):
        fake = FakeGitHub(body="Refs #42, refs #43", files=["docs/adr/0008-example.md"],
                          issues={42: (ready(), "OPEN"), 43: (ready(), "OPEN")})
        self.assertRejected(fake, "exactly one task")

    def test_referenced_tracking_record_stays_accepted(self):
        fake = FakeGitHub(body="Refs #42", files=["docs/adr/0008-example.md"], issues={42: (["kind:tracking"], "OPEN")})
        self.assertAccepted(fake)

    def test_referenced_blocked_record_needs_a_priority_beside_the_flag(self):
        files = ("docs/adr/0012-example.md",)
        self.assertAccepted(FakeGitHub(body="Refs #42", files=files, issues={42: (ready("blocked:owner"), "OPEN")}))
        self.assertRejected(FakeGitHub(body="Refs #42", files=files, issues={42: (["blocked:owner", "kind:chore", "status:ready"], "OPEN")}), "no priority label")

    def test_referenced_record_still_needs_ready_and_labels(self):
        fake = FakeGitHub(body="Refs #42", files=["docs/adr/0008-example.md"], issues={42: (["P2", "kind:chore"], "OPEN")})
        self.assertRejected(fake, "missing the 'status:ready' label")

    def test_closing_keyword_wins_over_a_reference(self):
        fake = FakeGitHub(body="Closes #42, refs #43", files=["docs/adr/0008-example.md"])
        output = self.assertAccepted(fake)
        self.assertNotIn("Record-only", output)


def labeled(name, actor, **extra):
    return {"event": "labeled", "label": {"name": name}, "actor": {"login": actor}, **extra}


class ThresholdTests(PolicyTest):
    """ADR 0008: in auto, a task above the assistant priority cap or in an owner-only category
    must have had `status:ready` applied by the owner, read from the issue timeline."""

    CAPPED = dict(APPROVAL_MODE="auto", PRIORITY_CAP="P2", OWNER_CATEGORIES="kind:security")

    def _task(self, labels, timeline, **kwargs):
        # A task above a threshold also requires a review of the head (ReviewRequirementTests);
        # these tests are about whose Ready it is, so the head is reviewed.
        kwargs.setdefault("reviews", [review()])
        return FakeGitHub(issues={42: (labels, "OPEN")}, timelines={42: timeline}, **kwargs)

    def test_capped_task_readied_by_the_owner_is_accepted(self):
        fake = self._task(ready(priority="P1"), [labeled("status:ready", "owner")])
        output = self.assertAccepted(fake, **self.CAPPED)
        self.assertIn("priority P1 is above the assistant cap P2", output)
        self.assertIn("readied by the owner owner", output)
        self.assertEqual(len(fake.timeline_calls()), 1)

    def test_capped_task_readied_by_another_login_is_rejected(self):
        fake = self._task(ready(priority="P0"), [labeled("status:ready", "planner-bot")])
        output = self.assertRejected(fake, "Task #42 must be readied by the owner (owner)", **self.CAPPED)
        self.assertIn("priority P0 is above the assistant cap P2", output)
        self.assertIn("last applied by planner-bot", output)

    def test_owner_only_category_readied_by_another_login_is_rejected_at_any_priority(self):
        fake = self._task(ready(priority="P3", category="kind:security"), [labeled("status:ready", "planner-bot")])
        output = self.assertRejected(fake, "category kind:security is owner-only", **self.CAPPED)
        self.assertIn("last applied by planner-bot", output)

    def test_owner_only_category_readied_by_the_owner_is_accepted(self):
        fake = self._task(ready(priority="P3", category="kind:security"), [labeled("status:ready", "owner")])
        self.assertAccepted(fake, **self.CAPPED)

    def test_the_last_labeled_event_counts(self):
        # Readied by the Planner, unlabelled, then readied by the owner: the owner's Ready stands.
        timeline = [labeled("status:ready", "planner-bot"), {"event": "unlabeled", "label": {"name": "status:ready"}, "actor": {"login": "owner"}},
                    labeled("status:ready", "owner")]
        self.assertAccepted(self._task(ready(priority="P1"), timeline), **self.CAPPED)
        self.assertRejected(self._task(ready(priority="P1"), list(reversed(timeline))), "last applied by planner-bot", **self.CAPPED)

    def test_other_labels_on_the_timeline_are_ignored(self):
        timeline = [labeled("status:ready", "owner"), labeled("P1", "planner-bot"), {"event": "commented", "actor": {"login": "planner-bot"}}]
        self.assertAccepted(self._task(ready(priority="P1"), timeline), **self.CAPPED)

    def test_owner_login_comparison_ignores_case(self):
        self.assertAccepted(self._task(ready(priority="P1"), [labeled("status:ready", "Owner")]), **self.CAPPED)

    def test_task_at_or_below_the_cap_does_not_read_the_timeline(self):
        for priority in ("P2", "P3"):
            fake = self._task(ready(priority=priority), [labeled("status:ready", "planner-bot")])
            self.assertAccepted(fake, **self.CAPPED)
            self.assertEqual(fake.timeline_calls(), [], priority)

    def test_variables_unset_leave_the_check_unchanged(self):
        # No cap and no categories: a P0 task readied by anyone passes as before and the timeline
        # is never read.
        fake = self._task(ready(priority="P0", category="kind:security"), [labeled("status:ready", "planner-bot")])
        output = self.assertAccepted(fake, APPROVAL_MODE="auto")
        self.assertEqual(fake.timeline_calls(), [])
        self.assertNotIn("threshold", output.lower())

    def test_cap_alone_and_categories_alone_each_apply(self):
        fake = self._task(ready(priority="P0"), [labeled("status:ready", "planner-bot")])
        self.assertRejected(fake, "above the assistant cap P1", APPROVAL_MODE="auto", PRIORITY_CAP="P1")
        fake = self._task(ready(priority="P0"), [labeled("status:ready", "planner-bot")])
        self.assertAccepted(fake, APPROVAL_MODE="auto", OWNER_CATEGORIES="kind:security")
        self.assertEqual(fake.timeline_calls(), [])

    def test_manual_mode_does_not_evaluate_the_thresholds(self):
        # Manual has its own, wider rule (ManualOwnerReadyTests): the cap and the categories
        # are not what decides, so an owner Ready passes and the output names no threshold.
        fake = self._task(ready(priority="P0", category="kind:security"), [labeled("status:ready", "owner")])
        output = self.assertAccepted(fake, APPROVAL_MODE="manual", PRIORITY_CAP="P2", OWNER_CATEGORIES="kind:security")
        self.assertNotIn("assistant thresholds", output)

    def test_timeline_lookup_failure_fails_the_check(self):
        fake = self._task(ready(priority="P1"), ApiError(1, "gh: Resource not accessible by integration (HTTP 403)\n"))
        output = self.assertRejected(fake, "Could not read the timeline of task #42", **self.CAPPED)
        self.assertIn("HTTP 403", output)

    def test_timeline_without_a_ready_event_fails_the_check(self):
        fake = self._task(ready(priority="P1"), [labeled("P1", "owner"), {"event": "commented", "actor": {"login": "owner"}}])
        self.assertRejected(fake, "has no 'labeled' event for 'status:ready'", **self.CAPPED)

    def test_timeline_is_read_in_pages(self):
        fake = self._task(ready(priority="P1"), [labeled("status:ready", "owner")])
        self.assertAccepted(fake, **self.CAPPED)
        self.assertEqual(fake.timeline_calls(), [["gh", "api", "--paginate", "--slurp", "repos/owner/repo/issues/42/timeline"]])

    def test_unready_capped_task_reports_the_missing_label_without_reading_the_timeline(self):
        fake = self._task(["P1", "kind:chore"], [labeled("status:ready", "planner-bot")])
        self.assertRejected(fake, "missing the 'status:ready' label", **self.CAPPED)
        self.assertEqual(fake.timeline_calls(), [])

    def test_record_only_reference_does_not_evaluate_the_thresholds(self):
        # Whose Ready it is goes unread on the record-only path; the review of the head does not.
        fake = FakeGitHub(body="Refs #42", files=["docs/adr/0008-example.md"], issues={42: (ready(priority="P1"), "OPEN")},
                          timelines={42: [labeled("status:ready", "planner-bot")]}, reviews=[review()])
        self.assertAccepted(fake, **self.CAPPED)
        self.assertEqual(fake.timeline_calls(), [])

    def test_cap_outside_the_priority_labels_is_rejected(self):
        self.assertRejected(FakeGitHub(), "CONDUCTOR_ASSISTANT_PRIORITY_CAP must be one of the priority labels", APPROVAL_MODE="auto", PRIORITY_CAP="P9")

    def test_empty_owner_login_with_thresholds_is_rejected(self):
        self.assertRejected(FakeGitHub(), "CONDUCTOR_OWNER_LOGIN is empty", APPROVAL_MODE="auto", PRIORITY_CAP="P2", OWNER_LOGIN="")

    def test_custom_priority_scale_orders_the_cap(self):
        fake = FakeGitHub(issues={42: (["prio/high", "kind:chore", "status:ready"], "OPEN")}, timelines={42: [labeled("status:ready", "planner-bot")]})
        self.assertRejected(fake, "priority prio/high is above the assistant cap prio/low", APPROVAL_MODE="auto",
                            PRIORITY_LABELS="prio/high,prio/low", PRIORITY_CAP="prio/low")


if __name__ == "__main__":
    unittest.main()


class ManualOwnerReadyTests(PolicyTest):
    """Kill switch (ADR 0009 §5, #113): in approval mode manual the readiness label on the task
    a pull request closes or references must have been applied last by the owner, at any
    priority and in any category, with no threshold variable set."""

    BOT = "grok-conductor[bot]"

    def _task(self, timeline, labels=None, **kwargs):
        return FakeGitHub(issues={42: (labels or ready(priority="P3"), "OPEN")}, timelines={42: timeline}, **kwargs)

    def _reference(self, timeline, labels=None):
        return self._task(timeline, labels, body="Refs #42", files=["docs/adr/0008-example.md"])

    def test_bot_ready_is_rejected_in_manual(self):
        fake = self._task([labeled("status:ready", self.BOT)])
        output = self.assertRejected(fake, f"'status:ready' was last applied by {self.BOT}", APPROVAL_MODE="manual")
        self.assertIn("must be readied by the owner (owner)", output)
        self.assertIn("approval mode is manual", output)
        self.assertIn("ADR 0009", output)

    def test_owner_ready_is_accepted_in_manual(self):
        fake = self._task([labeled("status:ready", "owner")])
        output = self.assertAccepted(fake, APPROVAL_MODE="manual")
        self.assertIn("readied by the owner owner (approval mode manual)", output)
        self.assertEqual(fake.timeline_calls(), [["gh", "api", "--paginate", "--slurp", "repos/owner/repo/issues/42/timeline"]])

    def test_the_same_bot_ready_within_the_cap_still_passes_in_auto(self):
        # Flipping the variable is the switch: the identical record passes in auto and fails in manual.
        timeline = [labeled("status:ready", self.BOT)]
        fake = self._task(timeline)
        self.assertAccepted(fake, APPROVAL_MODE="auto", PRIORITY_CAP="P2", OWNER_CATEGORIES="kind:security")
        self.assertEqual(fake.timeline_calls(), [])
        self.assertRejected(self._task(timeline), "last applied by", APPROVAL_MODE="manual", PRIORITY_CAP="P2", OWNER_CATEGORIES="kind:security")

    def test_the_last_labeled_event_counts_in_manual(self):
        timeline = [labeled("status:ready", "owner"), {"event": "unlabeled", "label": {"name": "status:ready"}, "actor": {"login": "owner"}},
                    labeled("status:ready", self.BOT)]
        self.assertRejected(self._task(timeline), f"last applied by {self.BOT}", APPROVAL_MODE="manual")
        self.assertAccepted(self._task(list(reversed(timeline))), APPROVAL_MODE="manual")

    def test_owner_login_comparison_ignores_case_in_manual(self):
        self.assertAccepted(self._task([labeled("status:ready", "Owner")]), APPROVAL_MODE="manual", OWNER_LOGIN="OWNER")

    def test_record_only_reference_with_a_bot_ready_is_rejected_in_manual(self):
        fake = self._reference([labeled("status:ready", self.BOT)])
        output = self.assertRejected(fake, f"'status:ready' was last applied by {self.BOT}", APPROVAL_MODE="manual")
        self.assertIn("Record-only pull request", output)

    def test_record_only_reference_with_an_owner_ready_is_accepted_in_manual(self):
        fake = self._reference([labeled("status:ready", "owner")])
        self.assertAccepted(fake, APPROVAL_MODE="manual")
        self.assertEqual(len(fake.timeline_calls()), 1)

    def test_referenced_tracking_record_without_a_ready_label_reads_no_timeline(self):
        fake = self._reference([], labels=["kind:tracking"])
        self.assertAccepted(fake, APPROVAL_MODE="manual")
        self.assertEqual(fake.timeline_calls(), [])

    def test_timeline_lookup_failure_fails_closed_in_manual(self):
        fake = self._task(ApiError(1, "gh: Resource not accessible by integration (HTTP 403)\n"))
        output = self.assertRejected(fake, "Could not read the timeline of task #42", APPROVAL_MODE="manual")
        self.assertIn("HTTP 403", output)

    def test_timeline_without_a_ready_event_fails_closed_in_manual(self):
        fake = self._task([labeled("P3", "owner"), {"event": "commented", "actor": {"login": "owner"}}])
        self.assertRejected(fake, "has no 'labeled' event for 'status:ready'", APPROVAL_MODE="manual")

    def test_ready_event_without_an_actor_fails_closed_in_manual(self):
        fake = self._task([{"event": "labeled", "label": {"name": "status:ready"}, "actor": None}])
        self.assertRejected(fake, "last applied by an unknown actor", APPROVAL_MODE="manual")

    def test_unready_task_reports_the_missing_label_without_reading_the_timeline(self):
        fake = self._task([labeled("status:ready", self.BOT)], labels=["P3", "kind:chore"])
        self.assertRejected(fake, "missing the 'status:ready' label", APPROVAL_MODE="manual")
        self.assertEqual(fake.timeline_calls(), [])

    def test_empty_owner_login_is_rejected_in_manual(self):
        self.assertRejected(FakeGitHub(), "CONDUCTOR_OWNER_LOGIN is empty", APPROVAL_MODE="manual", OWNER_LOGIN="")

    def test_custom_ready_label_is_the_one_attributed(self):
        labels = ["P3", "kind:chore", "go"]
        self.assertRejected(self._task([labeled("go", self.BOT), labeled("status:ready", "owner")], labels=labels),
                            "'go' was last applied by", APPROVAL_MODE="manual", READY_LABEL="go")
        self.assertAccepted(self._task([labeled("go", "owner")], labels=labels), APPROVAL_MODE="manual", READY_LABEL="go")
