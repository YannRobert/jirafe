"""The server's security checks, verified against a real local HTTP server and a fake Jira."""
import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

from jirafe.constants import BASE_DETAIL_FIELDS
from jirafe.handler import make_handler
from jirafe.meter import RequestMeter
from jirafe.mirror import IssueMirror
from tests.fakes import FakeJira, FakeUpstream

TOKEN = "secret-token"
JIRA = "https://jira.example.com"


class HandlerTest(unittest.TestCase):

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.upstream = FakeUpstream()
        settings = {
            "jira_host": JIRA,
            "jira_token": TOKEN,
            "quiet": True,
            "public": {"jiraWeb": JIRA, "boardId": 42, "fields": {"developer": "customfield_1"}, "views": []},
        }
        self.mirror = mirror = IssueMirror(
            self.directory.name,
            FakeJira([{"key": "ABC-1", "fields": {"assignee": {"name": "alice"}}}]),
            42,
            BASE_DETAIL_FIELDS
        )
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            make_handler(
                settings,
                self.upstream,
                mirror,
                RequestMeter()
            )
        )
        self.port = self.server.server_address[1]
        threading.Thread(
            target=self.server.serve_forever,
            daemon=True
        ).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.directory.cleanup()

    def call(
            self,
            method,
            path,
            body=None,
            headers=None
    ):
        connection = http.client.HTTPConnection(
            "127.0.0.1",
            self.port,
            timeout=5
        )
        try:
            connection.request(
                method,
                path,
                body=body,
                headers=headers or {}
            )
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def put(
            self,
            path,
            payload,
            origin=None
    ):
        return self.call(
            "PUT",
            path,
            json.dumps(payload).encode(),
            {"Origin": origin or f"http://127.0.0.1:{self.port}", "Content-Type": "application/json"}
        )

    def rank(
            self,
            payload,
            origin=None
    ):
        return self.put(
            "/rank",
            payload,
            origin
        )

    def assign(
            self,
            payload,
            origin=None
    ):
        return self.put(
            "/assignee",
            payload,
            origin
        )

    def test_page_has_injected_configuration_without_pat(self):
        status, body = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b'"boardId": 42', body)
        self.assertIn(b'"customfield_1"', body)
        self.assertNotIn(TOKEN.encode(), body)

    def test_foreign_host_refused(self):
        # DNS rebinding: a third-party domain pointing to 127.0.0.1.
        status, _ = self.call(
            "GET",
            "/stats",
            headers={"Host": "attacker.example"}
        )
        self.assertEqual(status, 403)

    def test_relay_restricted_to_allow_list(self):
        for path in ("/jira/rest/api/2/issue/ABC-1", "/jira/rest/agile/1.0/board/../../api/2/myself"):
            with self.subTest(path):
                status, _ = self.call("GET", path)
                self.assertEqual(status, 403)
        self.assertEqual(self.upstream.requests, [])

    def test_allowed_relay_adds_pat_server_side(self):
        status, _ = self.call("GET", "/jira/rest/api/2/myself")
        self.assertEqual(status, 200)
        request, = self.upstream.requests
        self.assertEqual(
            request["url"],
            f"{JIRA}/rest/api/2/myself"
        )
        self.assertEqual(
            request["headers"]["Authorization"],
            f"Bearer {TOKEN}"
        )

    def test_rank_refuses_other_origin(self):
        status, _ = self.rank(
            {"issue": "ABC-1", "before": "ABC-2"},
            origin="https://attacker.example"
        )
        self.assertEqual(status, 403)
        self.assertEqual(self.upstream.requests, [])

    def test_rank_refuses_invalid_body(self):
        invalid = (
            {"issue": "ABC-1"},
            {"issue": "ABC-1", "before": "ABC-2", "after": "ABC-3"},
            {"issue": "abc-1", "before": "ABC-2"},
            {"issue": "ABC-1", "before": "ABC-2&x=1"},
        )
        for payload in invalid:
            with self.subTest(payload):
                status, _ = self.rank(payload)
                self.assertEqual(status, 400)
        self.assertEqual(self.upstream.requests, [])

    def test_rank_builds_body_sent_to_jira(self):
        self.upstream.response = (204, b"", {})
        status, body = self.rank({"issue": "ABC-1", "after": "ABC-2", "extra": "ignored"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"ranked": "ABC-1"})
        request, = self.upstream.requests
        self.assertEqual(request["method"], "PUT")
        self.assertEqual(
            json.loads(request["body"]),
            {"issues": ["ABC-1"], "rankAfterIssue": "ABC-2"}
        )

    def test_rank_reports_jira_refusal(self):
        self.upstream.response = (400, b'{"errorMessages": ["Issue not on the board"]}', {})
        status, body = self.rank({"issue": "ABC-1", "before": "ABC-2"})
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body)["message"], "Issue not on the board")

    def test_unknown_write_route(self):
        self.assertEqual(self.put("/status", {"issue": "ABC-1"})[0], 404)
        self.assertEqual(self.upstream.requests, [])

    def test_assignee_refuses_other_origin(self):
        status, _ = self.assign(
            {"issue": "ABC-1", "assignee": "alice"},
            origin="https://attacker.example"
        )
        self.assertEqual(status, 403)
        self.assertEqual(self.upstream.requests, [])

    def test_assignee_refuses_invalid_body(self):
        invalid = (
            {"issue": "ABC-1"},
            {"issue": "abc-1", "assignee": "alice"},
            {"issue": "ABC-1/../2", "assignee": "alice"},
            {"issue": "ABC-1", "assignee": ""},
            {"issue": "ABC-1", "assignee": "alice\"bob"},
            {"issue": "ABC-1", "assignee": "alice bob"},
            {"issue": "ABC-1", "assignee": {"name": "alice"}},
            {"issue": "ABC-1", "assignee": "x" * 256},
            ["ABC-1", "alice"],
        )
        for payload in invalid:
            with self.subTest(payload):
                status, _ = self.assign(payload)
                self.assertEqual(status, 400)
        self.assertEqual(self.upstream.requests, [])

    def test_assignee_builds_body_sent_to_jira(self):
        self.upstream.response = (204, b"", {})
        for login in ("jean.dupont", "élodie.martin", None):
            with self.subTest(login):
                self.upstream.requests.clear()
                status, body = self.assign({"issue": "ABC-1", "assignee": login, "extra": "ignored"})
                self.assertEqual(status, 200)
                answer = json.loads(body)
                self.assertEqual(answer["assigned"], "ABC-1")
                # The local copy, resynced after the write, comes back with the answer.
                self.assertEqual(answer["issue"]["key"], "ABC-1")
                request, = self.upstream.requests
                self.assertEqual(request["method"], "PUT")
                self.assertEqual(
                    request["url"],
                    f"{JIRA}/rest/api/2/issue/ABC-1/assignee"
                )
                self.assertEqual(
                    json.loads(request["body"]),
                    {"name": login}
                )

    def test_assignee_reports_jira_refusal(self):
        self.upstream.response = (400, b'{"errorMessages": [], "errors": {"assignee": "User cannot be assigned"}}', {})
        status, body = self.assign({"issue": "ABC-1", "assignee": "alice"})
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body)["message"], "User cannot be assigned")

    def test_transitions_read_for_one_valid_key(self):
        for path in ("/transitions/abc-1", "/transitions/ABC-1/../../myself", "/transitions/ABC-1?x=1"):
            with self.subTest(path):
                self.assertEqual(self.call("GET", path)[0], 400)
        self.assertEqual(self.upstream.requests, [])
        status, _ = self.call("GET", "/transitions/ABC-1")
        self.assertEqual(status, 200)
        request, = self.upstream.requests
        self.assertEqual(
            request["url"],
            f"{JIRA}/rest/api/2/issue/ABC-1/transitions"
        )

    def test_transition_refuses_other_origin(self):
        status, _ = self.put(
            "/transition",
            {"issue": "ABC-1", "transition": "31"},
            origin="https://attacker.example"
        )
        self.assertEqual(status, 403)
        self.assertEqual(self.upstream.requests, [])

    def test_transition_refuses_invalid_body(self):
        invalid = (
            {"issue": "ABC-1"},
            {"issue": "abc-1", "transition": "31"},
            {"issue": "ABC-1", "transition": 31},
            {"issue": "ABC-1", "transition": "31&x=1"},
            {"issue": "ABC-1", "transition": {"id": "31"}},
            {"issue": "ABC-1", "transition": "1" * 11},
        )
        for payload in invalid:
            with self.subTest(payload):
                self.assertEqual(self.put("/transition", payload)[0], 400)
        self.assertEqual(self.upstream.requests, [])

    def test_transition_builds_body_sent_to_jira(self):
        self.upstream.response = (204, b"", {})
        status, body = self.put(
            "/transition",
            {"issue": "ABC-1", "transition": "31", "fields": {"resolution": "Done"}}
        )
        self.assertEqual(status, 200)
        answer = json.loads(body)
        self.assertEqual(answer["transitioned"], "ABC-1")
        self.assertEqual(answer["issue"]["key"], "ABC-1")
        request, = self.upstream.requests
        self.assertEqual(request["method"], "POST")
        self.assertEqual(
            request["url"],
            f"{JIRA}/rest/api/2/issue/ABC-1/transitions"
        )
        # Nothing but the transition id reaches Jira: fields sent by the page are ignored.
        self.assertEqual(
            json.loads(request["body"]),
            {"transition": {"id": "31"}}
        )

    def test_transition_reports_jira_refusal(self):
        self.upstream.response = (400, b'{"errorMessages": ["Transition 31 is not valid"], "errors": {}}', {})
        status, body = self.put("/transition", {"issue": "ABC-1", "transition": "31"})
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body)["message"], "Transition 31 is not valid")

    def test_issue(self):
        self.assertEqual(self.call("GET", "/issue/not-a-key")[0], 400)
        self.assertEqual(self.call("GET", "/issue/ABC-404")[0], 404)

    def test_stats_without_calling_jira(self):
        status, body = self.call("GET", "/stats")
        self.assertEqual(status, 200)
        self.assertIn("windows", json.loads(body))
        self.assertEqual(self.upstream.requests, [])

    def test_changes_marks_the_mirror_watched(self):
        self.assertFalse(self.mirror.watched())
        status, body = self.call("GET", "/changes")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"changedAt": None})
        self.assertTrue(self.mirror.watched())
        self.mirror.changed_at = 1_700_000_000.5
        status, body = self.call("GET", "/changes")
        self.assertEqual(json.loads(body), {"changedAt": 1_700_000_000_500})
