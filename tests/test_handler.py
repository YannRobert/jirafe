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
        mirror = IssueMirror(
            self.directory.name,
            FakeJira([]),
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

    def rank(
            self,
            payload,
            origin=None
    ):
        return self.call(
            "PUT",
            "/rank",
            json.dumps(payload).encode(),
            {"Origin": origin or f"http://127.0.0.1:{self.port}", "Content-Type": "application/json"}
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

    def test_issue(self):
        self.assertEqual(self.call("GET", "/issue/not-a-key")[0], 400)
        self.assertEqual(self.call("GET", "/issue/ABC-404")[0], 404)

    def test_stats_without_calling_jira(self):
        status, body = self.call("GET", "/stats")
        self.assertEqual(status, 200)
        self.assertIn("windows", json.loads(body))
        self.assertEqual(self.upstream.requests, [])
