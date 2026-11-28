"""Tests for the script embedded in `.github/workflows/claude-capabilities.yml` (#147).

The script is the Python text of the workflow's `shell: python` step. These tests read that
exact text out of the workflow file and execute it with `subprocess.run` replaced by an
in-memory GitHub double that keeps issues, labels, comments and events, so the code under
test is the code Actions runs, not a copy. Nothing here touches the network, a credential or
a real issue.

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
import urllib.parse
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "claude-capabilities.yml"

REPO = "AhmedAlhanaei/Conductor"
APP = "claude-conductor"
BOT = APP + "[bot]"
PARENT = 146
TITLE = "[demo] claude-conductor capability test"
OWNER = "alhanaei"
APP_ACTOR = {"login": BOT, "type": "Bot", "app": APP}
OWNER_ACTOR = {"login": OWNER, "type": "User", "app": None}

# Every write of a complete run, in order, with the step of #146 it belongs to.
WRITES = [
    ("create", "2"), ("link", "3"), ("edit_body", "4"), ("comment", "5"), ("edit_comment", "5"),
    ("label:question", "6"), ("unlabel:question", "6"), ("label:P3", "7"), ("label:kind:chore", "7"),
    ("assign", "8"), ("unassign", "8"), ("label:status:ready", "9"), ("unlabel:status:ready", "9"),
    ("close", "10"), ("reopen", "10"), ("close#2", "10"),
]
OPS = [op for op, _ in WRITES]
STEP_KEYS = ["2", "3", "4", "5", "6", "7", "8", "9", "10"]

DEFAULT_ENV = {
    "GITHUB_EVENT_NAME": "workflow_dispatch",
    "GITHUB_REPOSITORY": REPO,
    "EXPECTED_REPOSITORY": REPO,
    "GITHUB_REF": "refs/heads/main",
    "GITHUB_ACTOR": OWNER,
    "GITHUB_TRIGGERING_ACTOR": OWNER,
    "OWNER_LOGIN": OWNER,
    "APP_SLUG": APP,
    "APPROVAL_MODE": "auto",
    "PRIORITY_CAP": "P2",
    "OWNER_CATEGORIES": "kind:security",
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
    raise AssertionError("no `shell: python` step with a `run: |` block in claude-capabilities.yml")


class ApiError(Exception):
    def __init__(self, status=404):
        super().__init__(status)
        self.stderr = f"gh: refused (HTTP {status})\n"


class FakeGitHub:
    """Stands in for `subprocess.run`: one repository's issues, labels, comments and events.

    `actors` names who GitHub attributes one write to, `refuse` makes GitHub refuse a write
    (with `once`, only the first time), `lag` hides a write's event for that many reads.
    """

    def __init__(self, actors=None, refuse=None, once=False, lag=None, labels=None, parent=None):
        self.labels = {"question", "P3", "kind:chore", "status:ready", "P2", "kind:security"} if labels is None else set(labels)
        self.issues = {PARENT: self.issue(PARENT, "[task] parent", OWNER_ACTOR, labels=["P2", "kind:security", "status:ready"])}
        self.issues[PARENT].update(parent or {})
        self.actors, self.refuse, self.once, self.lag = dict(actors or {}), dict(refuse or {}), once, dict(lag or {})
        self.calls, self.done, self.attempted, self.comment_ids = [], [], [], 9000

    @staticmethod
    def user(actor):
        return {"login": actor["login"], "type": actor["type"]}

    @staticmethod
    def via(actor):
        return {"slug": actor["app"]} if actor["app"] else None

    def issue(self, number, title, actor, labels=(), body=""):
        return {
            "id": 500000 + number, "number": number, "title": title, "body": body, "state": "open",
            "state_reason": None, "labels": [{"name": name} for name in labels], "assignees": [],
            # GitHub names the App on a comment, and leaves this empty on an issue an App opens.
            "user": self.user(actor), "performed_via_github_app": self.via(actor) if actor.get("issue_marker") else None,
            "url": f"https://api.github.com/repos/{REPO}/issues/{number}",
            "html_url": f"https://github.com/{REPO}/issues/{number}",
            "_parent": None, "_events": [], "_comments": [], "_editor": None,
        }

    def add(self, issue):
        self.issues[issue["number"]] = issue
        return issue

    def demo(self):
        found = [i for i in self.issues.values() if i["title"] == TITLE and i["user"]["login"] == BOT]
        return found[0] if found else None

    @staticmethod
    def public(issue):
        return {key: value for key, value in issue.items() if not key.startswith("_")}

    def __call__(self, args, input=None, capture_output=False, text=False, **kwargs):
        self.calls.append(list(args))
        assert args[:2] == ["gh", "api"], f"only gh api is faked, got {args!r}"
        assert capture_output and text, "the script must capture gh output as text"
        try:
            stdout = self._dispatch(list(args[2:]), input)
        except ApiError as error:
            return subprocess.CompletedProcess(args, 1, "", error.stderr)
        return subprocess.CompletedProcess(args, 0, stdout, "")

    # Reads.

    def _dispatch(self, args, stdin):
        if args[0] == "--method":
            return self._write(args[1], args[2], args[3:], stdin)
        if args[0] == "graphql":
            number = int([a for a in args if a.startswith("number=")][0].split("=")[1])
            editor = self.issues[number]["_editor"]
            typename = {"Bot": "Bot", "User": "User"}[editor["type"]] if editor else None
            node = {"__typename": typename, "login": editor["login"]} if editor else None
            return json.dumps({"data": {"repository": {"issue": {"editor": node}}}})
        if args[:2] == ["--paginate", "--slurp"]:
            return json.dumps([self._list(args[2])])
        assert len(args) == 1, f"unexpected gh call: {args!r}"
        path = args[0]
        match = re.fullmatch(rf"repos/{REPO}/labels/(.+)", path)
        if match:
            name = urllib.parse.unquote(match.group(1))
            if name not in self.labels:
                raise ApiError(404)
            return json.dumps({"name": name})
        match = re.fullmatch(rf"repos/{REPO}/issues/(\d+)(/parent)?", path)
        assert match, f"unexpected gh read: {path!r}"
        issue = self.issues.get(int(match.group(1)))
        if issue is None:
            raise ApiError(404)
        if match.group(2):
            if issue["_parent"] is None:
                raise ApiError(404)
            return json.dumps(self.public(self.issues[issue["_parent"]]))
        return json.dumps(self.public(issue))

    def _list(self, path):
        if path == f"repos/{REPO}/issues?state=all&per_page=100":
            return [self.public(issue) for issue in self.issues.values()]
        match = re.fullmatch(rf"repos/{REPO}/issues/(\d+)/(events|comments)\?per_page=100", path)
        assert match, f"unexpected gh list: {path!r}"
        issue = self.issues[int(match.group(1))]
        if match.group(2) == "comments":
            return list(issue["_comments"])
        visible = []
        for event in issue["_events"]:
            if event["_hidden"] > 0:
                event["_hidden"] -= 1
            else:
                visible.append({key: value for key, value in event.items() if not key.startswith("_")})
        return visible

    # Writes.

    def _begin(self, name):
        """Name the write (a repeated one gets `#2`), then refuse it or return its actor."""
        op = name if name not in self.done else f"{name}#{self.done.count(name) + 1}"
        self.attempted.append(op)
        if op in self.refuse:
            status = self.refuse[op] if self.once is False else self.refuse.pop(op)
            raise ApiError(status)
        self.done.append(name)
        return op, self.actors.get(op, APP_ACTOR)

    def _event(self, issue, op, actor, kind, **extra):
        issue["_events"].append({
            "event": kind, "actor": self.user(actor), "performed_via_github_app": self.via(actor),
            "_hidden": self.lag.get(op, 0), **extra,
        })

    def _write(self, method, path, rest, stdin):
        payload = None
        if rest:
            assert rest == ["--input", "-"], "a payload must travel as JSON on stdin"
            payload = json.loads(stdin)
        if (method, path) == ("POST", f"repos/{REPO}/issues"):
            op, actor = self._begin("create")
            issue = self.add(self.issue(max(self.issues) + 1, payload["title"], actor, body=payload["body"]))
            return json.dumps(self.public(issue))
        if (method, path) == ("POST", f"repos/{REPO}/issues/{PARENT}/sub_issues"):
            op, actor = self._begin("link")
            child = [i for i in self.issues.values() if i["id"] == payload["sub_issue_id"]][0]
            child["_parent"] = PARENT
            self._event(child, op, actor, "parent_issue_added")
            return json.dumps(self.public(self.issues[PARENT]))
        match = re.fullmatch(rf"repos/{REPO}/issues/comments/(\d+)", path)
        if match:
            assert method == "PATCH"
            op, actor = self._begin("edit_comment")
            comment = [c for i in self.issues.values() for c in i["_comments"] if c["id"] == int(match.group(1))][0]
            comment["body"] = payload["body"]
            if "edit_comment" in self.actors:
                comment["user"], comment["performed_via_github_app"] = self.user(actor), self.via(actor)
            return json.dumps(comment)
        match = re.fullmatch(rf"repos/{REPO}/issues/(\d+)(?:/(labels|assignees|comments)(?:/(.+))?)?", path)
        assert match, f"unexpected gh write: {method} {path!r}"
        issue, part, tail = self.issues[int(match.group(1))], match.group(2), match.group(3)
        if part is None:
            assert method == "PATCH"
            if "body" in payload:
                op, actor = self._begin("edit_body")
                issue["body"], issue["_editor"] = payload["body"], actor
            elif payload["state"] == "closed":
                op, actor = self._begin("close")
                issue["state"], issue["state_reason"] = "closed", payload.get("state_reason", "completed")
                self._event(issue, op, actor, "closed")
            else:
                op, actor = self._begin("reopen")
                issue["state"], issue["state_reason"] = "open", "reopened"
                self._event(issue, op, actor, "reopened")
        elif part == "comments":
            op, actor = self._begin("comment")
            self.comment_ids += 1
            comment = {
                "id": self.comment_ids, "body": payload["body"], "user": self.user(actor),
                "performed_via_github_app": self.via(actor),
                "html_url": f"{issue['html_url']}#issuecomment-{self.comment_ids}",
            }
            issue["_comments"].append(comment)
            return json.dumps(comment)
        elif part == "labels" and method == "POST":
            for name in payload["labels"]:
                op, actor = self._begin(f"label:{name}")
                issue["labels"].append({"name": name})
                self._event(issue, op, actor, "labeled", label={"name": name})
        elif part == "labels":
            assert method == "DELETE" and tail
            name = urllib.parse.unquote(tail)
            op, actor = self._begin(f"unlabel:{name}")
            issue["labels"] = [label for label in issue["labels"] if label["name"] != name]
            self._event(issue, op, actor, "unlabeled", label={"name": name})
            return ""
        elif method == "POST":
            op, actor = self._begin("assign")
            issue["assignees"] = [{"login": login} for login in payload["assignees"]]
            # GitHub's events API names the assignee as actor and the writer as assigner.
            self._event(issue, op, {"login": payload["assignees"][0], "type": "User", "app": None}, "assigned", assigner=self.user(actor))
            issue["_events"][-1]["performed_via_github_app"] = self.via(actor)
        else:
            assert method == "DELETE"
            op, actor = self._begin("unassign")
            issue["assignees"] = []
            self._event(issue, op, {"login": payload["assignees"][0], "type": "User", "app": None}, "unassigned", assigner=self.user(actor))
            issue["_events"][-1]["performed_via_github_app"] = self.via(actor)
        return json.dumps(self.public(issue))

    def written(self):
        """The writes that reached GitHub and were accepted, as (method, path)."""
        return [(call[3], call[4]) for call in self.calls if call[2:3] == ["--method"]]


class Run:
    def __init__(self, code, stdout, output, summary):
        self.code, self.stdout, self.output, self.summary = code, stdout, output, summary

    def field(self, name):
        return dict(line.split("=", 1) for line in self.output.splitlines()).get(name)

    def row(self, step):
        found = re.search(rf"(?m)^\| {step} \| .* \| (.*) \|$", self.summary)
        return found.group(1) if found else None


def probe(github, **overrides):
    """Execute the embedded script once against the double."""
    with tempfile.TemporaryDirectory() as folder:
        out, summary = os.path.join(folder, "out"), os.path.join(folder, "summary")
        env = {**DEFAULT_ENV, "GITHUB_OUTPUT": out, "GITHUB_STEP_SUMMARY": summary, **overrides}
        env = {key: value for key, value in env.items() if value is not None}
        stdout, code = io.StringIO(), 0
        with mock.patch.dict(os.environ, env, clear=True), mock.patch("subprocess.run", github), mock.patch("time.sleep"), contextlib.redirect_stdout(stdout):
            try:
                exec(compile(embedded_script(), str(WORKFLOW), "exec"), {"__name__": "__main__"})
            except SystemExit as stop:
                code = stop.code or 0
        read = lambda path: pathlib.Path(path).read_text(encoding="utf-8") if os.path.exists(path) else ""
        return Run(code, stdout.getvalue(), read(out), read(summary))


class ProbeCase(unittest.TestCase):
    def failed(self, run, text):
        self.assertEqual(run.code, 1, run.stdout)
        self.assertIn("::error::", run.stdout)
        self.assertIn(text, run.stdout)
        self.assertEqual(run.output, "", "a failed run reports no result")
        self.assertIn("Claude App capability test: failed", run.summary)

    def refused(self, run, github, text):
        self.failed(run, text)
        self.assertEqual(github.written(), [], "a refusal must write nothing")

    def ended_clean(self, github):
        demo = github.demo()
        labels = [label["name"] for label in demo["labels"]]
        self.assertEqual((demo["state"], demo["state_reason"]), ("closed", "not_planned"))
        self.assertEqual(sorted(labels), ["P3", "kind:chore"])
        self.assertEqual(demo["assignees"], [])
        self.assertEqual(demo["_parent"], PARENT)


class Complete(ProbeCase):
    def test_a_full_run_makes_each_write_once_in_order(self):
        github = FakeGitHub()
        run = probe(github)
        self.assertEqual(run.code, 0, run.stdout)
        self.assertEqual(github.attempted, OPS)
        self.assertEqual(run.field("result"), "completed")
        self.assertEqual(run.field("demo-url"), github.demo()["html_url"])
        self.ended_clean(github)

    def test_the_demo_issue_says_it_is_a_demonstration_of_the_parent(self):
        github = FakeGitHub()
        probe(github)
        demo = github.demo()
        self.assertEqual(demo["title"], TITLE)
        for text in ("Demonstration only", "carries no work", f"#{PARENT}", "edited this body once"):
            self.assertIn(text, demo["body"])
        (comment,) = demo["_comments"]
        self.assertIn("edited it once", comment["body"])

    def test_a_second_run_writes_nothing_and_verifies_again(self):
        github = FakeGitHub()
        probe(github)
        before = len(github.written())
        second = probe(github)
        self.assertEqual(second.code, 0, second.stdout)
        self.assertEqual(second.field("result"), "verified-earlier")
        self.assertEqual(len(github.written()), before)
        self.assertIn("Writes in this run: 0", second.summary)
        self.assertEqual([second.row(step) for step in STEP_KEYS], ["passed"] * 9)

    def test_every_write_targets_the_demo_issue_its_comment_or_the_link(self):
        github = FakeGitHub()
        probe(github)
        number = github.demo()["number"]
        allowed = rf"repos/{REPO}/issues(/{number}(/.*)?|/comments/9001|/{PARENT}/sub_issues)?"
        for method, path in github.written():
            self.assertRegex(path, rf"^{allowed}$")
        self.assertEqual([path for _, path in github.written() if path.endswith(f"/{PARENT}/sub_issues")], [f"repos/{REPO}/issues/{PARENT}/sub_issues"])
        self.assertNotIn(f"repos/{REPO}/issues/{PARENT}", [path for _, path in github.written()])

    def test_a_same_title_issue_by_someone_else_is_not_the_demo_issue(self):
        github = FakeGitHub()
        other = github.add(github.issue(150, TITLE, OWNER_ACTOR))
        run = probe(github)
        self.assertEqual(run.code, 0, run.stdout)
        self.assertEqual(github.attempted, OPS)
        self.assertEqual(other["_events"], [])

    def test_events_without_an_app_marker_still_count(self):
        marker_free = {op: {**APP_ACTOR, "app": None} for op in OPS if op.split(":")[0].split("#")[0] in ("link", "label", "unlabel", "assign", "unassign", "close", "reopen")}
        run = probe(FakeGitHub(actors=marker_free))
        self.assertEqual(run.code, 0, run.stdout)

    def test_an_event_github_records_late_is_waited_for(self):
        github = FakeGitHub(lag={"label:question": 2, "close#2": 3})
        run = probe(github)
        self.assertEqual(run.code, 0, run.stdout)
        self.assertEqual(github.attempted, OPS)


class WrongCaller(ProbeCase):
    def test_another_event_is_refused(self):
        github = FakeGitHub()
        self.refused(probe(github, GITHUB_EVENT_NAME="schedule"), github, "only a manual dispatch")

    def test_another_repository_is_refused(self):
        github = FakeGitHub()
        self.refused(probe(github, GITHUB_REPOSITORY="someone/fork"), github, "only in its own repository")

    def test_another_ref_is_refused(self):
        github = FakeGitHub()
        self.refused(probe(github, GITHUB_REF="refs/heads/claude/branch"), github, "dispatch the workflow on main")

    def test_another_actor_is_refused(self):
        github = FakeGitHub()
        self.refused(probe(github, GITHUB_ACTOR="mallory"), github, "the caller is not the owner")

    def test_a_rerun_triggered_by_someone_else_is_refused(self):
        github = FakeGitHub()
        self.refused(probe(github, GITHUB_TRIGGERING_ACTOR="mallory"), github, "the caller is not the owner")

    def test_an_unset_owner_is_refused(self):
        github = FakeGitHub()
        self.refused(probe(github, OWNER_LOGIN=""), github, "the caller is not the owner")

    def test_another_app_slug_is_refused(self):
        github = FakeGitHub()
        self.refused(probe(github, APP_SLUG="codex-conductor"), github, "does not belong to the claude-conductor App")

    def test_a_missing_app_slug_is_refused(self):
        github = FakeGitHub()
        self.refused(probe(github, APP_SLUG=None), github, "does not belong to the claude-conductor App")

    def test_no_call_reaches_github_for_a_wrong_caller_or_app(self):
        for override in ({"GITHUB_ACTOR": "mallory"}, {"APP_SLUG": "codex-conductor"}):
            github = FakeGitHub()
            run = probe(github, **override)
            self.assertEqual(github.calls, [])
            self.assertIn("there is nothing to clean up", run.stdout)


class Preconditions(ProbeCase):
    def test_a_manual_or_unset_approval_mode_stops(self):
        for mode in ("manual", "", None):
            github = FakeGitHub()
            self.refused(probe(github, APPROVAL_MODE=mode), github, "not 'auto'")

    def test_each_missing_label_stops(self):
        for label in ("question", "P3", "kind:chore", "status:ready"):
            github = FakeGitHub(labels={"question", "P3", "kind:chore", "status:ready"} - {label})
            self.refused(probe(github), github, f"label {label!r} does not exist")

    def test_a_closed_parent_stops(self):
        github = FakeGitHub(parent={"state": "closed"})
        self.refused(probe(github), github, f"record #{PARENT} is not open")

    def test_a_parent_without_the_readiness_label_stops(self):
        github = FakeGitHub(parent={"labels": [{"name": "P2"}, {"name": "kind:security"}]})
        self.refused(probe(github), github, "does not carry 'status:ready'")

    def test_a_parent_that_is_a_pull_request_or_elsewhere_stops(self):
        for change in ({"pull_request": {}}, {"url": "https://api.github.com/repos/someone/else/issues/146"}):
            github = FakeGitHub(parent=change)
            self.refused(probe(github), github, "wrong target")

    def test_a_demo_priority_above_the_cap_or_an_unknown_cap_stops(self):
        github = FakeGitHub()
        self.refused(probe(github, PRIORITY_CAP="urgent"), github, "not within the assistant priority cap")

    def test_an_unset_cap_and_the_lowest_cap_pass(self):
        for cap in ("", "P3"):
            self.assertEqual(probe(FakeGitHub(), PRIORITY_CAP=cap).code, 0)

    def test_an_owner_only_demo_category_stops(self):
        github = FakeGitHub()
        self.refused(probe(github, OWNER_CATEGORIES="kind:security, kind:chore"), github, "owner-only category")

    def test_two_demo_issues_stop(self):
        github = FakeGitHub()
        github.add(github.issue(150, TITLE, APP_ACTOR))
        github.add(github.issue(151, TITLE, APP_ACTOR))
        self.refused(probe(github), github, "2 demo issues exist (#150, #151)")

    def test_a_parent_closed_between_the_start_and_the_ready_stops_before_the_label(self):
        github = FakeGitHub()

        class ClosesParent(dict):
            def get(inner, op, default=None):
                if op == "unassign":
                    github.issues[PARENT]["state"] = "closed"
                return default

        github.actors = ClosesParent()
        run = probe(github)
        self.failed(run, f"record #{PARENT} is not open")
        self.assertNotIn("label:status:ready", github.attempted)
        self.assertEqual(run.row("9"), "failed")


class WrongActor(ProbeCase):
    """One wrong-actor case per write: the run stops at that step and names it."""

    def test_each_write_attributed_to_the_owner_stops_its_step(self):
        for index, (op, step) in enumerate(WRITES):
            with self.subTest(op=op):
                github = FakeGitHub(actors={op: OWNER_ACTOR})
                if op == "create":
                    # An issue the owner opened is not the App's demo issue at all; the
                    # answer to the App's own POST naming another author is the mismatch.
                    github.actors = {op: {**APP_ACTOR, "type": "User"}}
                run = probe(github)
                self.failed(run, f"identity mismatch at step {step}")
                self.assertIn("stop and tell the owner", run.stdout)
                # The one write after a mismatch is the cleanup taking the readiness label off.
                cleanup = ["unlabel:status:ready"] if op == "label:status:ready" else []
                self.assertEqual(github.attempted, OPS[:index + 1] + cleanup, "nothing else is written after the mismatch")
                self.assertEqual(run.row(step), "failed")
                demo = github.demo()
                self.assertNotIn("status:ready", [label["name"] for label in (demo or {}).get("labels", [])])

    def test_the_bot_login_with_user_type_fails(self):
        self.failed(probe(FakeGitHub(actors={"label:question": {**APP_ACTOR, "type": "User"}})), "identity mismatch at step 6")

    def test_the_bot_login_through_another_app_fails(self):
        self.failed(probe(FakeGitHub(actors={"close": {**APP_ACTOR, "app": "grok-by-xai"}})), "identity mismatch at step 10")

    def test_another_bot_fails(self):
        other = {"login": "codex-conductor[bot]", "type": "Bot", "app": "codex-conductor"}
        self.failed(probe(FakeGitHub(actors={"assign": other})), "identity mismatch at step 8")

    def test_a_comment_without_the_app_marker_fails(self):
        self.failed(probe(FakeGitHub(actors={"comment": {**APP_ACTOR, "app": None}})), "identity mismatch at step 5")

    def test_an_issue_without_the_app_marker_is_the_apps_as_github_answers_it(self):
        github = FakeGitHub()
        run = probe(github)
        self.assertEqual(run.code, 0, run.stdout)
        self.assertIsNone(github.demo()["performed_via_github_app"])

    def test_an_issue_with_the_apps_marker_passes(self):
        run = probe(FakeGitHub(actors={"create": {**APP_ACTOR, "issue_marker": True}}))
        self.assertEqual(run.code, 0, run.stdout)

    def test_a_created_issue_with_another_apps_marker_fails(self):
        github = FakeGitHub(actors={"create": {**APP_ACTOR, "app": "grok-by-xai", "issue_marker": True}})
        self.failed(probe(github), "identity mismatch at step 2")
        self.assertEqual(github.attempted, ["create"])

    def test_a_found_issue_with_another_apps_marker_fails_and_nothing_is_written(self):
        github = FakeGitHub()
        github.add(github.issue(150, TITLE, {**APP_ACTOR, "app": "grok-by-xai", "issue_marker": True}))
        self.failed(probe(github), "identity mismatch at step 2")
        self.assertEqual(github.written(), [])

    def test_a_found_issue_without_a_marker_is_resumed_at_the_link(self):
        # The state the first live run left: the issue exists, nothing else does.
        github = FakeGitHub()
        github.add(github.issue(170, TITLE, APP_ACTOR, body="first"))
        run = probe(github)
        self.assertEqual(run.code, 0, run.stdout)
        self.assertEqual(github.attempted, OPS[1:])
        self.ended_clean(github)

    def test_an_existing_demo_issue_under_another_parent_stops(self):
        github = FakeGitHub()
        github.add(github.issue(150, TITLE, APP_ACTOR))["_parent"] = PARENT + 1
        github.add(github.issue(PARENT + 1, "another", OWNER_ACTOR))
        run = probe(github)
        self.failed(run, f"the demo issue's parent is {PARENT + 1}, not #{PARENT}")
        self.assertEqual(github.written(), [])


class Refused(ProbeCase):
    def test_each_refused_write_names_its_step_and_status_and_runs_nothing_after(self):
        for index, (op, step) in enumerate(WRITES):
            with self.subTest(op=op):
                github = FakeGitHub(refuse={op: 403})
                run = probe(github)
                self.failed(run, f"stopped at step {step}: GitHub refused")
                # The cleanup tries once more to take a refused readiness label off.
                cleanup = [op] if op == "unlabel:status:ready" else []
                self.assertEqual(github.attempted, OPS[:index + 1] + cleanup)
                self.assertEqual(run.row(step), "refused by GitHub (HTTP 403)")
                position = STEP_KEYS.index(step)
                self.assertEqual([run.row(key) for key in STEP_KEYS[:position]], ["passed"] * position)
                self.assertEqual([run.row(key) for key in STEP_KEYS[position + 1:]], ["not run"] * (8 - position))

    def test_an_event_github_never_records_stops_the_step(self):
        github = FakeGitHub(lag={"assign": 99})
        run = probe(github)
        self.failed(run, "stopped at step 8: GitHub recorded no 'assigned' event")
        self.assertEqual(run.row("8"), "failed")


class Resume(ProbeCase):
    def test_a_run_stopped_at_any_write_resumes_there_and_duplicates_nothing(self):
        for index, (op, step) in enumerate(WRITES):
            with self.subTest(op=op):
                github = FakeGitHub(refuse={op: 500}, once=True)
                first = probe(github)
                self.assertEqual(first.code, 1, first.stdout)
                second = probe(github)
                self.assertEqual(second.code, 0, second.stdout)
                self.assertEqual(second.field("result"), "completed")
                self.assertEqual(github.attempted, OPS[:index + 1] + OPS[index:])
                self.assertEqual(sorted(github.done), sorted(name.split("#")[0] for name in OPS))
                self.ended_clean(github)
                self.assertEqual(len(github.demo()["_comments"]), 1)
                third = probe(github)
                self.assertEqual(third.field("result"), "verified-earlier")

    def test_a_write_whose_event_arrived_too_late_is_not_repeated(self):
        github = FakeGitHub(lag={"label:P3": 99})
        self.assertEqual(probe(github).code, 1)
        github.demo()["_events"][-1]["_hidden"] = 0
        second = probe(github)
        self.assertEqual(second.code, 0, second.stdout)
        self.assertEqual(github.done.count("label:P3"), 1)
        self.ended_clean(github)


class Cleanup(ProbeCase):
    def test_a_failure_after_the_ready_removes_the_label_and_says_so(self):
        github = FakeGitHub(actors={"label:status:ready": OWNER_ACTOR})
        run = probe(github)
        self.failed(run, "identity mismatch at step 9")
        self.assertIn("`status:ready` was on the demo issue and has been removed", run.stdout)
        self.assertIn("has been removed", run.summary)
        self.assertNotIn("status:ready", [label["name"] for label in github.demo()["labels"]])

    def test_a_label_github_will_not_remove_is_reported_as_still_there(self):
        github = FakeGitHub(refuse={"unlabel:status:ready": 403})
        run = probe(github)
        self.failed(run, "stopped at step 9: GitHub refused")
        self.assertIn("STILL on the demo issue and could not be removed (HTTP 403); remove it by hand now", run.stdout)
        self.assertIn("STILL on the demo issue", run.summary)

    def test_a_failure_without_the_label_reports_it_absent(self):
        run = probe(FakeGitHub(refuse={"assign": 403}))
        self.assertIn("cleanup: `status:ready` is not on the demo issue", run.stdout)


class Summary(ProbeCase):
    def test_the_summary_lists_every_step_and_the_permissions(self):
        github = FakeGitHub()
        run = probe(github)
        self.assertIn("Claude App capability test: completed", run.summary)
        self.assertIn(f"- Demo issue: {github.demo()['html_url']}", run.summary)
        self.assertIn("- Writes in this run: 16", run.summary)
        self.assertIn("- Token requested with: `issues: write` only", run.summary)
        self.assertIn("- Permissions the installation grants: unknown", run.summary)
        self.assertEqual([run.row(step) for step in STEP_KEYS], ["passed"] * 9)
        self.assertNotIn("Stopped:", run.summary)

    def test_a_failed_summary_names_the_stop_and_the_cleanup(self):
        run = probe(FakeGitHub(refuse={"reopen": 422}))
        self.assertIn("- Stopped: stopped at step 10: GitHub refused PATCH", run.summary)
        self.assertIn("- Cleanup: `status:ready` is not on the demo issue", run.summary)
        self.assertEqual(run.row("10"), "refused by GitHub (HTTP 422)")


class WorkflowFile(unittest.TestCase):
    """The parts of the workflow the script cannot check from inside."""

    def setUp(self):
        self.text = workflow_text()

    def test_only_a_manual_dispatch_without_inputs_triggers_it(self):
        self.assertRegex(self.text, r"(?m)^on:\n  workflow_dispatch:\n\n")
        self.assertNotIn("inputs", self.text)

    def test_the_workflow_token_has_no_permissions(self):
        self.assertRegex(self.text, r"(?m)^permissions: \{\}$")

    def test_the_app_token_asks_for_issues_write_and_nothing_else(self):
        self.assertEqual(re.findall(r"(?m)^\s+(permission-[a-z-]+): (\S+)$", self.text), [("permission-issues", "write")])

    def test_the_token_action_is_pinned_to_the_commit_the_identity_test_uses(self):
        uses = re.findall(r"(?m)^\s+uses: (\S+)", self.text)
        self.assertEqual(len(uses), 1)
        self.assertRegex(uses[0], r"^actions/create-github-app-token@[0-9a-f]{40}$")
        identity = (WORKFLOW.parent / "claude-identity.yml").read_text(encoding="utf-8")
        self.assertIn(uses[0], identity)

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

    def test_the_parent_the_title_and_the_labels_are_fixed_in_the_file(self):
        script = embedded_script()
        self.assertIn(f"PARENT = {PARENT}\n", script)
        self.assertIn(f'TITLE = "{TITLE}"\n', script)
        self.assertIn('NEUTRAL, PRIORITY, KIND, READY = "question", "P3", "kind:chore", "status:ready"\n', script)

    def test_no_workflow_expression_sits_inside_the_script(self):
        self.assertNotIn("${{", embedded_script())


if __name__ == "__main__":
    unittest.main()
