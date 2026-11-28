"""Regression tests for the weekly report embedded in `.github/workflows/backlog-review.yml`.

The tests execute the workflow's own `run: |` script with `subprocess.run` replaced by a fake
that answers the `gh` calls the report makes, so no network is used. Run from the repository
root:

    python3 -m unittest discover -s tests -p 'test_*.py'
"""
import contextlib
import datetime
import io
import json
import os
import pathlib
import subprocess
import tempfile
import textwrap
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "backlog-review.yml"
NOW = datetime.datetime.now(datetime.timezone.utc)
HEAD = "a" * 40
OLD = "b" * 40

DEFAULT_ENV = {
    "GITHUB_REPOSITORY": "owner/repo",
    "PRIORITY_LABELS": "P0,P1,P2,P3",
    "BLOCKED_LABEL": "blocked:owner",
    "CATEGORY_PREFIX": "kind:",
    "TRACKING_LABEL": "kind:tracking",
    "READY_LABEL": "status:ready",
    "STALE_DAYS": "7",
    "REVIEW_ISSUE": "",
}


def embedded_script():
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
    raise AssertionError("no `shell: python` step with a `run: |` block in backlog-review.yml")


def days_ago(days):
    return (NOW - datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def issue(number, *labels, title="A task"):
    return {"number": number, "title": title, "labels": [{"name": name} for name in labels], "assignees": [],
            "updatedAt": days_ago(0), "createdAt": days_ago(1)}


def review(login="grok-conductor", state="COMMENTED", commit=HEAD, body="", association=None, kind=None):
    """A review node as the GraphQL search returns it. By default `grok-conductor` is an app's
    bot with no association, `author` is the repository owner and anyone else a collaborator."""
    bot = login == "grok-conductor"
    if association is None:
        association = "NONE" if bot else "OWNER" if login == "author" else "COLLABORATOR"
    return {"state": state, "body": body, "authorAssociation": association,
            "author": {"login": login, "__typename": kind or ("Bot" if bot else "User")}, "commit": {"oid": commit}}


def pull(number, *reviews, merged=None, created=30, committed=None, draft=False, title="A change", author="author"):
    return {"number": number, "title": title, "createdAt": days_ago(created), "mergedAt": merged, "isDraft": draft,
            "headRefOid": HEAD, "author": {"login": author},
            "commits": {"nodes": [{"commit": {"committedDate": days_ago(created if committed is None else committed)}}]},
            "reviews": {"nodes": list(reviews)}}


class FakeGitHub:
    def __init__(self, issues=(), merged=(), opened=()):
        self.issues, self.merged, self.opened = list(issues), merged, opened
        self.calls, self.comments = [], []

    def __call__(self, command, **kwargs):
        self.calls.append(list(command))
        if command[:3] == ["gh", "issue", "list"]:
            return subprocess.CompletedProcess(command, 0, json.dumps(self.issues), "")
        if command[:3] == ["gh", "issue", "comment"]:
            self.comments.append((command[3], command[command.index("--body") + 1]))
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:3] == ["gh", "api", "graphql"]:
            search = next(argument for argument in command if argument.startswith("q="))
            answer = self.merged if "is:merged" in search else self.opened
            if isinstance(answer, str):
                return subprocess.CompletedProcess(command, 1, "", answer)
            # two pages, as `--paginate --slurp` returns them
            pages = [{"data": {"search": {"nodes": list(answer)}}}, {"data": {"search": {"nodes": []}}}]
            return subprocess.CompletedProcess(command, 0, json.dumps(pages), "")
        raise AssertionError(f"unexpected command: {command}")


def run_report(fake, **env):
    output = io.StringIO()
    with tempfile.TemporaryDirectory() as folder:
        environment = {**DEFAULT_ENV, "GITHUB_STEP_SUMMARY": os.path.join(folder, "summary.md"), **env}
        with mock.patch.dict(os.environ, environment, clear=False), mock.patch.object(subprocess, "run", fake), \
                contextlib.redirect_stdout(output):
            try:
                exec(compile(embedded_script(), str(WORKFLOW), "exec"), {"__name__": "backlog_review"})
            except SystemExit as stop:
                code = stop.code
            else:
                raise AssertionError("the report must end with sys.exit")
    return (0 if code is None else int(code)), output.getvalue()


def section(report, title_start):
    """The bullet lines of the section whose title starts with `title_start`."""
    lines = report.splitlines()
    start = next(index for index, line in enumerate(lines) if line.startswith("## " + title_start))
    items = []
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        if line.startswith("- "):
            items.append(line[2:])
    return items


class TriageTests(unittest.TestCase):
    def test_open_tasks_without_the_ready_label_are_the_triage_list(self):
        fake = FakeGitHub(issues=[issue(1, title="Bare"), issue(2, "P2", "kind:chore", title="Labelled"),
                                  issue(3, "P2", "kind:chore", "status:ready", title="Ready")])
        code, report = run_report(fake)
        self.assertEqual(code, 0, report)
        self.assertEqual(section(report, "Triage"), ["#1 Bare (no priority, no category)", "#2 Labelled"])

    def test_blocked_does_not_stand_in_for_a_priority(self):
        fake = FakeGitHub(issues=[issue(4, "blocked:owner", "kind:chore", "status:ready", title="Blocked only"),
                                  issue(5, "P1", "blocked:owner", "kind:chore", "status:ready", title="Blocked beside")])
        _, report = run_report(fake)
        self.assertEqual(section(report, "Triage"), ["#4 Blocked only (carries `status:ready`, no priority)"])
        self.assertEqual(section(report, "Owner-blocked"), ["#4 Blocked only", "#5 Blocked beside"])

    def test_the_notebook_issue_and_a_tracking_parent_are_not_missing_anything(self):
        fake = FakeGitHub(issues=[issue(66, title="Backlog"), issue(7, "kind:tracking", title="Parent")])
        _, report = run_report(fake, REVIEW_ISSUE="66")
        self.assertEqual(section(report, "Triage"), ["#7 Parent"])
        self.assertEqual(fake.comments[0][0], "66")

    def test_the_closing_line_no_longer_asks_to_propose_before_filing(self):
        _, report = run_report(FakeGitHub())
        self.assertNotIn("propose, wait for approval, then file", report)
        self.assertIn("Filing needs no approval", report)


class UnreadMergeTests(unittest.TestCase):
    def test_merged_pull_request_without_a_review_is_listed(self):
        fake = FakeGitHub(merged=[pull(10, merged=days_ago(1), title="Unread"), pull(11, review(), merged=days_ago(1))])
        code, report = run_report(fake)
        self.assertEqual(code, 0, report)
        items = section(report, "Merged since 2026-11-23")
        self.assertEqual(len(items), 1, items)
        self.assertTrue(items[0].startswith("#10 Unread (merged "), items)

    def test_a_merge_before_the_cutover_is_not_listed(self):
        fake = FakeGitHub(merged=[pull(140, merged="2026-11-23T17:41:02Z"), pull(141, merged="2026-11-23T18:27:56Z", title="Cutover")])
        _, report = run_report(fake)
        self.assertEqual([item.split(" (")[0] for item in section(report, "Merged since")], ["#141 Cutover"])
        search = next(argument for call in fake.calls for argument in call if argument.startswith("q=") and "is:merged" in argument)
        self.assertEqual(search, "q=repo:owner/repo is:pr is:merged merged:>=2026-11-23")

    def test_a_review_counts_as_linked_task_counts_it(self):
        counted = [review("grok-conductor"), review("codex", state="APPROVED"), review("codex", commit=OLD),
                   review("author", body="Reviewer: claude, read after the merge")]
        ignored = [review("author", body="Thanks, fixed."), review("stranger", association="NONE"),
                   review("codex", state="PENDING"), review("codex", state="DISMISSED")]
        merged = [pull(20 + index, entry, merged=days_ago(1)) for index, entry in enumerate(counted)]
        merged += [pull(40 + index, entry, merged=days_ago(1)) for index, entry in enumerate(ignored)]
        _, report = run_report(FakeGitHub(merged=merged))
        self.assertEqual([item.split(" ")[0] for item in section(report, "Merged since")], ["#40", "#41", "#42", "#43"])


class WaitingHeadTests(unittest.TestCase):
    def test_open_pull_request_unreviewed_for_longer_than_the_stale_days_is_listed(self):
        fake = FakeGitHub(opened=[pull(50, created=9, title="Waiting"), pull(51, created=3), pull(52, review(), created=9)])
        _, report = run_report(fake)
        self.assertEqual(section(report, "Open pull requests"), [f"#50 Waiting (head {HEAD[:7]} unreviewed for 9 days)"])

    def test_a_review_of_an_earlier_commit_is_not_a_review_of_the_head(self):
        fake = FakeGitHub(opened=[pull(53, review(commit=OLD), created=20, committed=8, draft=True)])
        _, report = run_report(fake)
        self.assertEqual(section(report, "Open pull requests"), [f"#53 A change (head {HEAD[:7]} unreviewed for 8 days, draft)"])

    def test_a_new_commit_restarts_the_wait_and_the_variable_moves_it(self):
        fake = FakeGitHub(opened=[pull(54, created=20, committed=3)])
        _, report = run_report(fake)
        self.assertEqual(section(report, "Open pull requests"), ["none"])
        _, report = run_report(fake, STALE_DAYS="2")
        self.assertEqual(len(section(report, "Open pull requests whose head has had no review for more than 2 days")), 1)


class FailureTests(unittest.TestCase):
    def test_unreadable_pull_requests_are_named_in_the_report_and_fail_the_run(self):
        fake = FakeGitHub(issues=[issue(1, title="Bare")], merged="HTTP 403: Resource not accessible by integration", opened=[])
        code, report = run_report(fake, REVIEW_ISSUE="66")
        self.assertEqual(code, 1, report)
        self.assertIn("HTTP 403", section(report, "Merged since")[0])
        self.assertEqual(section(report, "Triage"), ["#1 Bare (no priority, no category)"])
        self.assertEqual(report.count("::error::"), 1)
        self.assertEqual(len(fake.comments), 1)


class WorkflowShapeTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8")

    def test_the_schedule_is_unchanged_and_reviews_can_be_read(self):
        self.assertIn('    - cron: "0 6 * * 1"', self.text)
        self.assertIn("permissions:\n  contents: read\n  issues: write\n  pull-requests: read\n", self.text)
        self.assertIn("timeout-minutes: 5", self.text)

    def test_the_cutover_is_a_constant_and_not_a_variable(self):
        self.assertIn('REVIEW_CUTOVER = "2026-11-23T18:27:56Z"', self.text)
        self.assertNotIn("vars.CONDUCTOR_REVIEW_CUTOVER", self.text)


if __name__ == "__main__":
    unittest.main()
