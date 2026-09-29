import tempfile
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from jirafe.constants import BASE_DETAIL_FIELDS
from jirafe.mirror import IssueMirror, detail_fields, slim_history
from tests.fakes import FakeJira

HISTORY = {
    "author": {
        "name": "alice",
        "displayName": "Alice",
        "emailAddress": "alice@example.com",
        "avatarUrls": {"16x16": "a16", "48x48": "a48"},
    },
    "created": "2026-01-02T10:00:00.000+0100",
    "items": [{"field": "status", "fromString": "À faire", "toString": "In Progress", "from": "1", "to": "3"}],
}


class SlimHistoryTest(unittest.TestCase):

    def test_keeps_only_what_the_detail_shows(self):
        self.assertEqual(
            slim_history(HISTORY),
            {
                "author": {"name": "alice", "displayName": "Alice", "avatarUrls": {"48x48": "a48"}},
                "created": "2026-01-02T10:00:00.000+0100",
                "items": [{"field": "status", "from": "À faire", "to": "In Progress"}],
            }
        )

    def test_missing_author(self):
        self.assertIsNone(slim_history({"items": []})["author"]["name"])


class DetailFieldsTest(unittest.TestCase):

    def test_without_custom_field(self):
        self.assertEqual(
            detail_fields({}),
            BASE_DETAIL_FIELDS
        )

    def test_custom_fields_deduplicated_and_sorted(self):
        self.assertEqual(
            detail_fields({"deliveredAt": "customfield_2", "developer": "customfield_1", "tester": "customfield_1"}),
            BASE_DETAIL_FIELDS + ",customfield_1,customfield_2"
        )


class IssueMirrorTest(unittest.TestCase):

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.jira = FakeJira([{"key": "ABC-1", "fields": {"summary": "An issue"}, "changelog": {"histories": [HISTORY]}}])

    def tearDown(self):
        self.directory.cleanup()

    def mirror(self, fields=BASE_DETAIL_FIELDS):
        return IssueMirror(
            self.directory.name,
            self.jira,
            42,
            fields
        )

    def searches(self):
        return [path for path in self.jira.paths if path.startswith("rest/api/2/search")]

    def jqls(self):
        return [parse_qs(urlsplit(path).query)["jql"][0] for path in self.searches()]

    def test_sync_writes_slimmed_copy(self):
        mirror = self.mirror()
        self.assertEqual(mirror.sync_board(), 1)
        entry = mirror.read("ABC-1")
        self.assertEqual(
            entry["data"]["fields"]["summary"],
            "An issue"
        )
        self.assertNotIn(
            "emailAddress",
            entry["data"]["changelog"]["histories"][0]["author"]
        )
        self.assertEqual(mirror.status()["issues"], 1)

    def test_missing_issue(self):
        self.assertIsNone(self.mirror().read("ABC-404"))

    def test_first_pass_full_then_incremental(self):
        mirror = self.mirror()
        mirror.sync_board()
        mirror.sync_board()
        first, second = self.jqls()
        self.assertNotIn("updated", first)
        self.assertIn("updated", second)

    def test_full_pass_once_a_day(self):
        mirror = self.mirror()
        with mock.patch("jirafe.mirror.time.time", return_value=1_000_000):
            mirror.sync_board()
        with mock.patch("jirafe.mirror.time.time", return_value=1_000_000 + 25 * 3600):
            mirror.sync_board()
        self.assertNotIn("updated", self.jqls()[1])

    def test_changing_fields_forces_full_pass(self):
        self.mirror().sync_board()
        self.mirror(BASE_DETAIL_FIELDS + ",customfield_1").sync_board()
        self.assertNotIn("updated", self.jqls()[1])
        self.assertIn("customfield_1", self.searches()[1])

    def test_no_active_sprint(self):
        self.jira.sprints = []
        self.assertEqual(self.mirror().sync_board(), 0)
        self.assertEqual(self.searches(), [])

    def test_issue_sync(self):
        mirror = self.mirror(BASE_DETAIL_FIELDS + ",customfield_1")
        self.assertEqual(
            mirror.sync_issue("ABC-1")["key"],
            "ABC-1"
        )
        self.assertIn("customfield_1", self.jira.paths[-1])
