"""Tests for the publisher embedded in `.github/workflows/codex-planner-comment.yml` (#134).

The publisher is the Python script in the workflow's `shell: python` step. These tests read
that exact text out of the workflow file and execute it with `subprocess.run` replaced by an
in-memory GitHub double, so the code under test is the code Actions runs, not a copy. Nothing
here touches the network, a credential or a real issue.

Run from the repository root:  python3 -m unittest discover -s tests -p 'test_*.py'
"""

import contextlib
import io
import json
import os
import pathlib
import re
import subprocess
import tempfile
import textwrap
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "codex-planner-comment.yml"

REPO = "AhmedAlhanaei/Conductor"
BOT = "codex-conductor[bot]"
PAGE = 100
REQUEST = "plan-2026-11-22-a"
MESSAGE = "Round 1 for #7: three questions.\n\n1. Keep the cap at P2? Recommended: yes."

DEFAULT_ENV = {
    "GITHUB_EVENT_NAME": "workflow_dispatch",
    "GITHUB_REPOSITORY": REPO,
    "EXPECTED_REPOSITORY": REPO,
    "GITHUB_REF": "refs/heads/main",
    "GITHUB_ACTOR": "alhanaei",
    "GITHUB_TRIGGERING_ACTOR": "alhanaei",
    "GITHUB_SERVER_URL": "https://github.com",
    "GITHUB_RUN_ID": "555",
    "PLANNER": "codex",
    "OWNER_LOGIN": "alhanaei",
    "APP_SLUG": "codex-conductor",
    "ISSUE": "7",
    "REQUEST_ID": REQUEST,
    "MESSAGE": MESSAGE,
}


def workflow_lines():
    return WORKFLOW.read_text(encoding="utf-8").splitlines()


def embedded_script():
    """Return the dedented Python source of the workflow's `shell: python` step."""
    lines = workflow_lines()
    for index, line in enumerate(lines):
        if line.strip() == "shell: python" and lines[index + 1].strip() == "run: |":
            indent = len(lines[index + 1]) - len(lines[index + 1].lstrip())
            body = []
            for next_line in lines[index + 2:]:
                if next_line.strip() and (len(next_line) - len(next_line.lstrip())) <= indent:
                    break
                body.append(next_line)
            return textwrap.dedent("\n".join(body)) + "\n"
    raise AssertionError("no `shell: python` step with a `run: |` block in codex-planner-comment.yml")


class ApiError(Exception):
    def __init__(self, stderr="gh: Not Found (HTTP 404)\n"):
        super().__init__(stderr)
        self.stderr = stderr


class FakeGitHub:
    """Stands in for `subprocess.run`: one repository's issues and their comments."""

    def __init__(self, issues=None, comments=None, post_author=None, post_error=None, list_error=None):
        # issue number -> the JSON GitHub answers for it, or an ApiError
        self.issues = {7: self.issue(7)} if issues is None else dict(issues)
        self.comments = {number: list(items) for number, items in (comments or {}).items()}
        self.post_author = post_author or {"login": BOT, "type": "Bot", "app": "codex-conductor"}
        self.post_error, self.list_error = post_error, list_error
        self.calls, self.posted = [], []

    @staticmethod
    def issue(number, state="open", pull=False, repo=REPO):
        data = {"number": number, "state": state, "url": f"https://api.github.com/repos/{repo}/issues/{number}"}
        if pull:
            data["pull_request"] = {"url": f"https://api.github.com/repos/{repo}/pulls/{number}"}
        return data

    @staticmethod
    def comment(number, body, login=BOT, kind="Bot", app="codex-conductor", ident=1):
        return {
            "id": ident,
            "body": body,
            "user": {"login": login, "type": kind},
            "performed_via_github_app": {"slug": app} if app else None,
            "html_url": f"https://github.com/{REPO}/issues/{number}#issuecomment-{ident}",
        }

    def __call__(self, args, input=None, capture_output=False, text=False, **kwargs):
        self.calls.append(list(args))
        assert args[:2] == ["gh", "api"], f"only gh api is faked, got {args!r}"
        assert capture_output and text, "the publisher must capture gh output as text"
        try:
            stdout = self._dispatch(args[2:], input)
        except ApiError as error:
            return subprocess.CompletedProcess(args, 1, "", error.stderr)
        return subprocess.CompletedProcess(args, 0, stdout, "")

    def _dispatch(self, args, stdin):
        match = re.fullmatch(rf"repos/{REPO}/issues/(\d+)", args[-1])
        if match and len(args) == 1:
            answer = self.issues.get(int(match.group(1)), ApiError())
            if isinstance(answer, ApiError):
                raise answer
            return json.dumps(answer)
        match = re.fullmatch(rf"repos/{REPO}/issues/(\d+)/comments\?per_page=100", args[-1])
        if match:
            assert args[:2] == ["--paginate", "--slurp"], "the comments must be read in full, as pages"
            if self.list_error:
                raise self.list_error
            items = self.comments.get(int(match.group(1)), [])
            return json.dumps([items[i:i + PAGE] for i in range(0, len(items), PAGE)] or [[]])
        match = re.fullmatch(rf"repos/{REPO}/issues/(\d+)/comments", args[2]) if args[:2] == ["--method", "POST"] else None
        if match:
            assert args[3:] == ["--input", "-"], "the body must travel as JSON on stdin, never as an argument"
            number = int(match.group(1))
            body = json.loads(stdin)["body"]
            self.posted.append((number, body))
            if self.post_error:
                raise self.post_error
            author = self.post_author
            made = self.comment(number, body, author["login"], author["type"], author["app"], ident=9000 + len(self.posted))
            self.comments.setdefault(number, []).append(made)
            return json.dumps(made)
        raise AssertionError(f"unexpected gh call: {args!r}")


class Run:
    def __init__(self, code, stdout, output, summary):
        self.code, self.stdout, self.output, self.summary = code, stdout, output, summary

    @property
    def url(self):
        return dict(line.split("=", 1) for line in self.output.splitlines()).get("comment-url")

    @property
    def result(self):
        return dict(line.split("=", 1) for line in self.output.splitlines()).get("result")


def publish(github, **overrides):
    """Execute the embedded publisher once against the double."""
    with tempfile.TemporaryDirectory() as folder:
        out, summary = os.path.join(folder, "out"), os.path.join(folder, "summary")
        env = {**DEFAULT_ENV, "GITHUB_OUTPUT": out, "GITHUB_STEP_SUMMARY": summary, **overrides}
        env = {key: value for key, value in env.items() if value is not None}
        stdout, code = io.StringIO(), 0
        with mock.patch.dict(os.environ, env, clear=True), mock.patch("subprocess.run", github), contextlib.redirect_stdout(stdout):
            try:
                exec(compile(embedded_script(), str(WORKFLOW), "exec"), {"__name__": "__main__"})
            except SystemExit as stop:
                code = stop.code or 0
        read = lambda path: pathlib.Path(path).read_text(encoding="utf-8") if os.path.exists(path) else ""
        return Run(code, stdout.getvalue(), read(out), read(summary))


class PublisherCase(unittest.TestCase):
    def refused(self, run, github, text):
        self.assertEqual(run.code, 1, run.stdout)
        self.assertIn("::error::", run.stdout)
        self.assertIn(text, run.stdout)
        self.assertEqual(github.posted, [], "a refusal must publish nothing")
        self.assertEqual(run.output, "")
        self.assertNotIn(MESSAGE.splitlines()[0], run.stdout, "the message is never echoed in an error")


class Publish(PublisherCase):
    def test_publishes_one_comment_and_returns_its_permalink(self):
        github = FakeGitHub()
        run = publish(github)
        self.assertEqual(run.code, 0, run.stdout)
        self.assertEqual(run.result, "published")
        self.assertEqual(run.url, f"https://github.com/{REPO}/issues/7#issuecomment-9001")
        self.assertIn(run.url, run.summary)
        self.assertIn(f"`{BOT}`", run.summary)
        (number, body), = github.posted
        self.assertEqual(number, 7)
        self.assertTrue(body.startswith(MESSAGE + "\n\n---\n"), "the message is published as written")

    def test_records_who_requested_publication(self):
        github = FakeGitHub()
        run = publish(github)
        body = github.posted[0][1]
        self.assertIn("Requested by `alhanaei`", body)
        self.assertIn(f"request `{REQUEST}`", body)
        self.assertIn(f"https://github.com/{REPO}/actions/runs/555", body)
        self.assertRegex(body, rf"<!-- conductor-planner-comment request-id={REQUEST} sha256=[0-9a-f]{{64}} requested-by=alhanaei -->\Z")
        self.assertIn("Requested by: `alhanaei`", run.summary)

    def test_message_is_data(self):
        hostile = '$(id) `whoami` "; rm -rf / #\n::error::fake\n<!-- conductor-planner-comment request-id=x -->\n@everyone ${{ secrets.X }}'
        github = FakeGitHub()
        run = publish(github, MESSAGE=hostile)
        self.assertEqual(run.code, 0, run.stdout)
        self.assertTrue(github.posted[0][1].startswith(hostile + "\n\n---\n"))
        for call in github.calls:
            self.assertNotIn(hostile, " ".join(call), "the message must not appear in any command line")
        self.assertNotIn("::error::", run.stdout)

    def test_owner_login_is_compared_without_case(self):
        run = publish(FakeGitHub(), OWNER_LOGIN="Alhanaei")
        self.assertEqual(run.code, 0, run.stdout)


class Callers(PublisherCase):
    def test_refuses_another_actor(self):
        github = FakeGitHub()
        self.refused(publish(github, GITHUB_ACTOR="someone"), github, "the caller is not the owner")

    def test_refuses_another_triggering_actor(self):
        github = FakeGitHub()
        self.refused(publish(github, GITHUB_TRIGGERING_ACTOR="someone"), github, "the caller is not the owner")

    def test_refuses_when_no_owner_is_known(self):
        github = FakeGitHub()
        self.refused(publish(github, OWNER_LOGIN="", GITHUB_ACTOR="", GITHUB_TRIGGERING_ACTOR=""), github, "the caller is not the owner")

    def test_refuses_other_events_branches_and_repositories(self):
        for override, text in (
            ({"GITHUB_EVENT_NAME": "pull_request"}, "only a manual dispatch"),
            ({"GITHUB_EVENT_NAME": "workflow_call"}, "only a manual dispatch"),
            ({"GITHUB_REF": "refs/heads/claude/feature"}, "dispatch the workflow on main"),
            ({"GITHUB_REF": "refs/tags/main"}, "dispatch the workflow on main"),
            ({"GITHUB_REPOSITORY": "fork/Conductor"}, "only from its own repository"),
        ):
            with self.subTest(override):
                github = FakeGitHub()
                self.refused(publish(github, **override), github, text)
                self.assertEqual(github.calls, [], "nothing is read before the caller is accepted")


class Roles(PublisherCase):
    def test_refuses_when_the_planner_is_not_codex(self):
        for planner in ("", "claude", "grok", "Codex", "codex "):
            with self.subTest(planner):
                github = FakeGitHub()
                self.refused(publish(github, PLANNER=planner), github, "role mismatch")

    def test_refuses_another_apps_token(self):
        for slug in ("", "grok-conductor", "codex-conductor-dev"):
            with self.subTest(slug):
                github = FakeGitHub()
                self.refused(publish(github, APP_SLUG=slug), github, "role mismatch")

    def test_fails_when_github_attributes_the_comment_to_someone_else(self):
        for author in (
            {"login": "alhanaei", "type": "User", "app": None},
            {"login": "grok-conductor[bot]", "type": "Bot", "app": "grok-conductor"},
            {"login": BOT, "type": "User", "app": "codex-conductor"},
            {"login": BOT, "type": "Bot", "app": None},
        ):
            with self.subTest(author):
                run = publish(FakeGitHub(post_author=author))
                self.assertEqual(run.code, 1)
                self.assertIn("identity mismatch", run.stdout)
                self.assertEqual(run.output, "", "no permalink is returned for a misattributed comment")


class Targets(PublisherCase):
    def test_refuses_malformed_issue_numbers(self):
        for issue in ("", "0", "07", "-7", "7a", "7 ", "7/comments", "../../pulls/7", "1234567890"):
            with self.subTest(issue):
                github = FakeGitHub()
                self.refused(publish(github, ISSUE=issue), github, "not an issue number")
                self.assertEqual(github.calls, [])

    def test_refuses_a_missing_issue(self):
        github = FakeGitHub()
        self.refused(publish(github, ISSUE="8"), github, "wrong target")

    def test_refuses_a_pull_request(self):
        github = FakeGitHub(issues={7: FakeGitHub.issue(7, pull=True)})
        self.refused(publish(github), github, "is a pull request")

    def test_refuses_a_closed_issue(self):
        github = FakeGitHub(issues={7: FakeGitHub.issue(7, state="closed")})
        self.refused(publish(github), github, "is not open")

    def test_refuses_an_issue_that_redirects_to_another_repository(self):
        github = FakeGitHub(issues={7: FakeGitHub.issue(12, repo="AhmedAlhanaei/gachabot")})
        self.refused(publish(github), github, "moved or redirected")

    def test_refuses_an_unreadable_answer(self):
        github = FakeGitHub(issues={7: []})
        self.refused(publish(github), github, "wrong target")


class Inputs(PublisherCase):
    def test_refuses_bad_request_ids(self):
        for request in ("", "short", "-leading-dash", "has space in it", "semi;colon-id", "x" * 65, "new\nline-id"):
            with self.subTest(request):
                github = FakeGitHub()
                self.refused(publish(github, REQUEST_ID=request), github, "the request ID must be")

    def test_refuses_empty_and_oversized_messages(self):
        for message, text in (("", "is empty"), (" \n\t", "is empty"), ("x" * 60001, "longer than")):
            with self.subTest(text):
                github = FakeGitHub()
                run = publish(github, MESSAGE=message)
                self.assertEqual(run.code, 1)
                self.assertIn(text, run.stdout)
                self.assertEqual(github.posted, [])
                self.assertEqual(github.calls, [])

    def test_accepts_the_longest_message(self):
        run = publish(FakeGitHub(), MESSAGE="x" * 60000)
        self.assertEqual(run.code, 0, run.stdout)


class Retries(PublisherCase):
    def test_a_retry_returns_the_first_comment_and_posts_nothing(self):
        github = FakeGitHub()
        first = publish(github)
        second = publish(github, GITHUB_RUN_ID="556")
        third = publish(github, GITHUB_RUN_ID="557")
        self.assertEqual((first.result, second.result, third.result), ("published", "reused", "reused"))
        self.assertEqual(first.url, second.url)
        self.assertEqual(first.url, third.url)
        self.assertEqual(len(github.posted), 1, "one request ID publishes one comment")
        self.assertIn("reused", second.summary)

    def test_a_retry_with_another_message_is_a_conflict(self):
        github = FakeGitHub()
        publish(github)
        run = publish(github, MESSAGE=MESSAGE + " Changed.")
        self.assertEqual(run.code, 1)
        self.assertIn("conflict", run.stdout)
        self.assertEqual(run.output, "")
        self.assertEqual(len(github.posted), 1)

    def test_whitespace_changes_are_a_conflict_too(self):
        github = FakeGitHub()
        publish(github)
        self.assertIn("conflict", publish(github, MESSAGE=MESSAGE + "\n").stdout)
        self.assertEqual(len(github.posted), 1)

    def test_another_request_id_publishes_a_second_comment(self):
        github = FakeGitHub()
        first = publish(github)
        second = publish(github, REQUEST_ID="plan-2026-11-22-b")
        self.assertEqual(second.result, "published")
        self.assertNotEqual(first.url, second.url)
        self.assertEqual(len(github.posted), 2)

    def test_the_same_request_id_on_another_issue_is_its_own_request(self):
        github = FakeGitHub(issues={7: FakeGitHub.issue(7), 9: FakeGitHub.issue(9)})
        publish(github)
        run = publish(github, ISSUE="9")
        self.assertEqual(run.result, "published")
        self.assertEqual([number for number, _ in github.posted], [7, 9])

    def test_a_retry_is_found_beyond_the_first_page(self):
        github = FakeGitHub()
        publish(github)
        published = github.comments[7].pop()
        github.comments[7] = [FakeGitHub.comment(7, f"note {n}", "alhanaei", "User", None, n) for n in range(1, 151)] + [published]
        run = publish(github)
        self.assertEqual(run.result, "reused")
        self.assertEqual(len(github.posted), 1)

    def test_a_marker_written_by_anyone_else_does_not_count(self):
        github = FakeGitHub()
        publish(github)
        forged = github.comments[7].pop()["body"]
        for login, kind in (("alhanaei", "User"), ("grok-conductor[bot]", "Bot"), (BOT, "User")):
            with self.subTest(login=login, kind=kind):
                github.comments[7] = [FakeGitHub.comment(7, forged, login, kind, None, 5)]
                github.posted.clear()
                run = publish(github)
                self.assertEqual(run.result, "published", "only the bot's own comment proves an earlier publication")
                self.assertEqual(len(github.posted), 1)

    def test_a_marker_quoted_inside_a_message_does_not_count(self):
        github = FakeGitHub()
        publish(github, REQUEST_ID="plan-2026-11-22-b")
        quoted = github.comments[7][0]["body"].replace("plan-2026-11-22-b", REQUEST)
        github.posted.clear()
        github.comments[7] = []
        publish(github, REQUEST_ID="plan-2026-11-22-c", MESSAGE=quoted)
        run = publish(github, MESSAGE="Another message.")
        self.assertEqual(run.result, "published", "only the marker the publisher appended at the end is read")

    def test_unreadable_comments_stop_before_publishing(self):
        github = FakeGitHub(list_error=ApiError("gh: Server Error (HTTP 502)\n"))
        self.refused(publish(github), github, "a duplicate cannot be ruled out")

    def test_a_refused_post_returns_no_permalink(self):
        github = FakeGitHub(post_error=ApiError("gh: Forbidden (HTTP 403)\n"))
        run = publish(github)
        self.assertEqual(run.code, 1)
        self.assertIn("retry with the same request ID", run.stdout)
        self.assertEqual(run.output, "")


class Workflow(unittest.TestCase):
    """The parts of the workflow file the publisher relies on but cannot check itself."""

    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8")

    def test_only_a_manual_dispatch_starts_it(self):
        triggers = re.search(r"^on:\n((?:  .*\n|\n)+)", self.text, re.M).group(1)
        self.assertEqual(re.findall(r"^  (\w+):", triggers, re.M), ["workflow_dispatch"])

    def test_no_default_token_permissions_and_an_issues_only_app_token(self):
        self.assertIn("\npermissions: {}\n", self.text)
        self.assertEqual(re.findall(r"^\s+(permission-[\w-]+): (\w+)$", self.text, re.M), [("permission-issues", "write")])
        self.assertEqual(re.findall(r"^\s+(owner|repositories):", self.text, re.M), [], "the token stays scoped to this repository")

    def test_the_key_and_the_message_never_reach_a_script_as_text(self):
        scripts = "\n".join(embedded_runs(self.text))
        self.assertNotIn("${{", scripts, "no workflow expression is expanded inside a script")
        self.assertEqual(len(re.findall(r"secrets\.", self.text)), 1)
        self.assertIn("private-key: ${{ secrets.CODEX_CONDUCTOR_PRIVATE_KEY }}", self.text)
        self.assertEqual(len(re.findall(r"inputs\.message", self.text)), 1)
        self.assertIn("MESSAGE: ${{ inputs.message }}", self.text)

    def test_actions_are_pinned_to_a_commit(self):
        uses = re.findall(r"uses: (\S+)", self.text)
        self.assertTrue(uses)
        for action in uses:
            self.assertRegex(action, r"@[0-9a-f]{40}$")

    def test_runs_are_serialized_and_bounded(self):
        self.assertIn("group: codex-planner-comment\n  cancel-in-progress: false", self.text)
        self.assertIn("timeout-minutes: 5", self.text)

    def test_the_early_refusal_repeats_the_publishers_checks(self):
        shell = embedded_runs(self.text)[0]
        for check in ("workflow_dispatch", "EXPECTED_REPOSITORY", "refs/heads/main", "codex", "GITHUB_ACTOR", "GITHUB_TRIGGERING_ACTOR", "ISSUE", "REQUEST_ID"):
            self.assertIn(check, shell)
        self.assertLess(self.text.index("Refuse an unauthorized dispatch"), self.text.index("create-github-app-token"))


def embedded_runs(text):
    """Every `run: |` block of the workflow, in order, as dedented text."""
    lines, blocks = text.splitlines(), []
    for index, line in enumerate(lines):
        if line.strip() == "run: |":
            indent = len(line) - len(line.lstrip())
            body = []
            for next_line in lines[index + 1:]:
                if next_line.strip() and (len(next_line) - len(next_line.lstrip())) <= indent:
                    break
                body.append(next_line)
            blocks.append(textwrap.dedent("\n".join(body)))
    return blocks


if __name__ == "__main__":
    unittest.main()
