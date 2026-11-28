"""Tests for the verifier embedded in `.github/workflows/claude-identity.yml` (#139).

The verifier is the Python script in the workflow's `shell: python` step. These tests read
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
WORKFLOW = ROOT / ".github" / "workflows" / "claude-identity.yml"

REPO = "AhmedAlhanaei/Conductor"
APP = "claude-conductor"
BOT = APP + "[bot]"
ISSUE = 139

DEFAULT_ENV = {
    "GITHUB_EVENT_NAME": "workflow_dispatch",
    "GITHUB_REPOSITORY": REPO,
    "EXPECTED_REPOSITORY": REPO,
    "GITHUB_REF": "refs/heads/main",
    "GITHUB_ACTOR": "alhanaei",
    "GITHUB_TRIGGERING_ACTOR": "alhanaei",
    "OWNER_LOGIN": "alhanaei",
    "APP_SLUG": APP,
    "ISSUE": str(ISSUE),
}


def workflow_text():
    return WORKFLOW.read_text(encoding="utf-8")


def embedded_script():
    """Return the dedented Python source of the workflow's `shell: python` step."""
    lines = workflow_text().splitlines()
    for index, line in enumerate(lines):
        if line.strip() == "shell: python" and lines[index + 1].strip() == "run: |":
            indent = len(lines[index + 1]) - len(lines[index + 1].lstrip())
            body = []
            for next_line in lines[index + 2:]:
                if next_line.strip() and (len(next_line) - len(next_line.lstrip())) <= indent:
                    break
                body.append(next_line)
            return textwrap.dedent("\n".join(body)) + "\n"
    raise AssertionError("no `shell: python` step with a `run: |` block in claude-identity.yml")


class ApiError(Exception):
    def __init__(self, stderr="gh: Not Found (HTTP 404)\n"):
        super().__init__(stderr)
        self.stderr = stderr


class FakeGitHub:
    """Stands in for `subprocess.run`: one repository's issues and their comments."""

    def __init__(self, issues=None, comments=None, post_author=None, post_error=None, list_error=None):
        self.issues = {ISSUE: self.issue(ISSUE)} if issues is None else dict(issues)
        self.comments = {number: list(items) for number, items in (comments or {}).items()}
        self.post_author = post_author or {"login": BOT, "type": "Bot", "app": APP}
        self.post_error, self.list_error = post_error, list_error
        self.calls, self.posted = [], []

    @staticmethod
    def issue(number, state="open", pull=False, repo=REPO):
        data = {"number": number, "state": state, "url": f"https://api.github.com/repos/{repo}/issues/{number}"}
        if pull:
            data["pull_request"] = {"url": f"https://api.github.com/repos/{repo}/pulls/{number}"}
        return data

    @staticmethod
    def comment(number, body, login=BOT, kind="Bot", app=APP, ident=1):
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
        assert capture_output and text, "the verifier must capture gh output as text"
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
            return json.dumps([items[i:i + 100] for i in range(0, len(items), 100)] or [[]])
        match = re.fullmatch(rf"repos/{REPO}/issues/(\d+)/comments", args[2]) if args[:2] == ["--method", "POST"] else None
        if match:
            assert args[3:] == ["--input", "-"], "the body must travel as JSON on stdin"
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

    def field(self, name):
        return dict(line.split("=", 1) for line in self.output.splitlines()).get(name)


def verify(github, **overrides):
    """Execute the embedded verifier once against the double."""
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


class VerifierCase(unittest.TestCase):
    def failed(self, run, text):
        self.assertEqual(run.code, 1, run.stdout)
        self.assertIn("::error::", run.stdout)
        self.assertIn(text, run.stdout)
        self.assertEqual(run.output, "", "a failed run reports no verified comment")

    def refused(self, run, github, text):
        self.failed(run, text)
        self.assertEqual(github.posted, [], "a refusal must post nothing")


class Verified(VerifierCase):
    def test_posts_one_fixed_comment_and_verifies_its_author(self):
        github = FakeGitHub()
        run = verify(github)
        self.assertEqual(run.code, 0, run.stdout)
        self.assertEqual(run.field("result"), "posted")
        url = f"https://github.com/{REPO}/issues/{ISSUE}#issuecomment-9001"
        self.assertEqual(run.field("comment-url"), url)
        self.assertIn(url, run.summary)
        self.assertIn(f"`{BOT}`", run.summary)
        (number, body), = github.posted
        self.assertEqual(number, ISSUE)
        self.assertIn("Claude App identity test (#139)", body)

    def test_a_closed_test_issue_is_still_the_target(self):
        # The pull request that adds the workflow closes #139 before the first dispatch.
        github = FakeGitHub(issues={ISSUE: FakeGitHub.issue(ISSUE, state="closed")})
        run = verify(github)
        self.assertEqual(run.code, 0, run.stdout)
        self.assertEqual(len(github.posted), 1)

    def test_a_second_run_posts_nothing_and_verifies_the_first_comment(self):
        github = FakeGitHub()
        first = verify(github)
        second = verify(github)
        self.assertEqual(second.code, 0, second.stdout)
        self.assertEqual(second.field("result"), "verified-earlier")
        self.assertEqual(second.field("comment-url"), first.field("comment-url"))
        self.assertEqual(len(github.posted), 1)

    def test_a_same_text_comment_by_someone_else_is_not_the_earlier_comment(self):
        body = verify(github := FakeGitHub()) and github.posted[0][1]
        other = FakeGitHub(comments={ISSUE: [FakeGitHub.comment(ISSUE, body, "alhanaei", "User", None)]})
        run = verify(other)
        self.assertEqual(run.code, 0, run.stdout)
        self.assertEqual(run.field("result"), "posted")


class WrongCaller(VerifierCase):
    def test_another_event_is_refused(self):
        github = FakeGitHub()
        self.refused(verify(github, GITHUB_EVENT_NAME="pull_request"), github, "only a manual dispatch")

    def test_another_repository_is_refused(self):
        github = FakeGitHub()
        self.refused(verify(github, GITHUB_REPOSITORY="someone/fork"), github, "only in its own repository")

    def test_another_ref_is_refused(self):
        github = FakeGitHub()
        self.refused(verify(github, GITHUB_REF="refs/heads/claude/branch"), github, "dispatch the workflow on main")

    def test_another_actor_is_refused(self):
        github = FakeGitHub()
        self.refused(verify(github, GITHUB_ACTOR="mallory"), github, "the caller is not the owner")

    def test_a_rerun_triggered_by_someone_else_is_refused(self):
        github = FakeGitHub()
        self.refused(verify(github, GITHUB_TRIGGERING_ACTOR="mallory"), github, "the caller is not the owner")

    def test_an_unset_owner_is_refused(self):
        github = FakeGitHub()
        self.refused(verify(github, OWNER_LOGIN=""), github, "the caller is not the owner")

    def test_the_owner_login_compares_without_case(self):
        run = verify(FakeGitHub(), OWNER_LOGIN="AlHanaei")
        self.assertEqual(run.code, 0, run.stdout)

    def test_no_call_reaches_github_for_a_wrong_caller(self):
        github = FakeGitHub()
        verify(github, GITHUB_ACTOR="mallory")
        self.assertEqual(github.calls, [])


class WrongApp(VerifierCase):
    def test_another_app_slug_is_refused_before_any_call(self):
        github = FakeGitHub()
        self.refused(verify(github, APP_SLUG="codex-conductor"), github, "does not belong to the claude-conductor App")
        self.assertEqual(github.calls, [])

    def test_a_missing_app_slug_is_refused(self):
        github = FakeGitHub()
        self.refused(verify(github, APP_SLUG=None), github, "does not belong to the claude-conductor App")


class WrongAuthor(VerifierCase):
    def mismatch(self, **author):
        github = FakeGitHub(post_author={"login": BOT, "type": "Bot", "app": APP, **author})
        run = verify(github)
        self.failed(run, "identity mismatch")
        self.assertIn("stop and tell the owner", run.stdout)
        self.assertEqual(run.summary, "")

    def test_the_owner_login_as_author_fails(self):
        self.mismatch(login="alhanaei", type="User", app=None)

    def test_another_bot_as_author_fails(self):
        self.mismatch(login="codex-conductor[bot]", app="codex-conductor")

    def test_the_bot_login_with_user_type_fails(self):
        self.mismatch(type="User")

    def test_the_bot_login_through_another_app_fails(self):
        self.mismatch(app="grok-by-xai")

    def test_the_bot_login_without_an_app_marker_fails(self):
        self.mismatch(app=None)

    def test_an_earlier_comment_with_the_bot_login_but_wrong_type_fails(self):
        body = verify(github := FakeGitHub()) and github.posted[0][1]
        forged = FakeGitHub(comments={ISSUE: [FakeGitHub.comment(ISSUE, body, BOT, "User", None)]})
        run = verify(forged)
        self.failed(run, "identity mismatch")
        self.assertEqual(forged.posted, [])


class WrongTarget(VerifierCase):
    def test_an_unreadable_issue_stops(self):
        github = FakeGitHub(issues={})
        self.refused(verify(github), github, "could not be read")

    def test_a_pull_request_is_refused(self):
        github = FakeGitHub(issues={ISSUE: FakeGitHub.issue(ISSUE, pull=True)})
        self.refused(verify(github), github, "is a pull request")

    def test_a_redirected_issue_is_refused(self):
        github = FakeGitHub(issues={ISSUE: FakeGitHub.issue(ISSUE, repo="someone/else")})
        self.refused(verify(github), github, "moved or redirected")

    def test_a_non_numeric_issue_is_refused(self):
        github = FakeGitHub()
        self.refused(verify(github, ISSUE="139/comments"), github, "not an issue number")
        self.assertEqual(github.calls, [])

    def test_unreadable_comments_stop_before_posting(self):
        github = FakeGitHub(list_error=ApiError())
        self.refused(verify(github), github, "a duplicate cannot be ruled out")

    def test_a_refused_comment_stops(self):
        github = FakeGitHub(post_error=ApiError("gh: Resource not accessible by integration (HTTP 403)\n"))
        self.failed(verify(github), "GitHub refused the comment")


class WorkflowFile(unittest.TestCase):
    """The parts of the workflow the verifier cannot check from inside."""

    def setUp(self):
        self.text = workflow_text()

    def test_only_a_manual_dispatch_triggers_it(self):
        self.assertRegex(self.text, r"(?m)^on:\n  workflow_dispatch:\n\n")

    def test_the_workflow_token_has_no_permissions(self):
        self.assertRegex(self.text, r"(?m)^permissions: \{\}$")

    def test_the_app_token_asks_for_issues_write_and_nothing_else(self):
        self.assertEqual(re.findall(r"(?m)^\s+(permission-[a-z-]+): (\S+)$", self.text), [("permission-issues", "write")])

    def test_the_token_action_is_pinned_to_a_commit(self):
        uses = re.findall(r"(?m)^\s+uses: (\S+)", self.text)
        self.assertEqual(len(uses), 1)
        self.assertRegex(uses[0], r"^actions/create-github-app-token@[0-9a-f]{40}$")

    def test_the_key_and_client_id_come_from_the_named_secret_and_variable(self):
        self.assertIn("client-id: ${{ vars.CLAUDE_CONDUCTOR_CLIENT_ID }}", self.text)
        self.assertIn("private-key: ${{ secrets.CLAUDE_CONDUCTOR_PRIVATE_KEY }}", self.text)

    def test_the_early_step_repeats_the_caller_checks(self):
        for check in (
            '[[ "$GITHUB_EVENT_NAME" == workflow_dispatch ]]',
            '[[ "$GITHUB_REPOSITORY" == "$EXPECTED_REPOSITORY" ]]',
            '[[ "$GITHUB_REF" == refs/heads/main ]]',
            '"${GITHUB_ACTOR,,}" == "${OWNER_LOGIN,,}"',
            '[[ "${GITHUB_TRIGGERING_ACTOR,,}" == "${OWNER_LOGIN,,}" ]]',
        ):
            self.assertIn(check, self.text)

    def test_no_workflow_expression_sits_inside_a_script(self):
        script = embedded_script()
        self.assertNotIn("${{", script)


if __name__ == "__main__":
    unittest.main()
