import tempfile
import time
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from jirafe.constants import BASE_DETAIL_FIELDS, WATCH_TTL_S
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

    def test_transitions_teach_the_workflow_without_being_copied(self):
        self.jira.issues[0]["fields"].update({"status": {"id": "1"}, "issuetype": {"id": "10"}})
        self.jira.issues[0]["transitions"] = [{"id": "12", "name": "Start", "to": {"id": "2"}}]
        self.jira.issues[0]["changelog"]["histories"].append(
            {"items": [{"field": "status", "from": "2", "fromString": "S2", "to": "5", "toString": "S5"}]}
        )
        mirror = self.mirror()
        mirror.sync_board()
        self.assertNotIn("transitions", mirror.read("ABC-1")["data"])
        self.assertEqual(
            mirror.workflows.route(
                "ABC/10",
                "0",
                "5",
                [{"to": {"id": "1"}}]
            ),
            ["1", "2", "5"]
        )

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


class IncrementalPassTest(unittest.TestCase):

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.jira = FakeJira([
            {"key": "ABC-1", "fields": {"updated": "2026-01-02T10:00:00.000+0100"}},
            {"key": "ABC-2", "fields": {"updated": "2026-01-02T10:00:00.000+0100"}},
        ])
        self.mirror = IssueMirror(
            self.directory.name,
            self.jira,
            42,
            BASE_DETAIL_FIELDS
        )
        self.mirror.sync_board()
        self.jira.paths.clear()

    def tearDown(self):
        self.directory.cleanup()

    def queries(self):
        return [parse_qs(urlsplit(path).query) for path in self.jira.paths if path.startswith("rest/api/2/search")]

    def test_nothing_changed_costs_one_light_search(self):
        changed_at = self.mirror.changed_at
        self.assertEqual(self.mirror.sync_board(), 0)
        (light,) = self.queries()
        self.assertEqual(light["fields"], ["updated"])
        self.assertNotIn("expand", light)
        self.assertEqual(self.mirror.changed_at, changed_at)

    def test_only_changed_issues_are_fetched_whole(self):
        self.jira.issues[1] = {"key": "ABC-2", "fields": {"updated": "2026-01-02T11:00:00.000+0100", "summary": "New"}}
        # A minute later: still an incremental pass.
        later = time.time() + 60
        with mock.patch("jirafe.mirror.time.time", return_value=later):
            self.assertEqual(self.mirror.sync_board(), 1)
        light, whole = self.queries()
        self.assertEqual(whole["jql"], ["key in (ABC-2)"])
        self.assertIn("expand", whole)
        self.assertEqual(self.mirror.read("ABC-2")["data"]["fields"]["summary"], "New")
        self.assertEqual(self.mirror.changed_at, later)

    def test_recently_updated_issues(self):
        # 10:00 +0100 on 2026-01-02, then ABC-2 changes an hour later.
        ten = 1_767_344_400_000
        self.jira.issues[1] = {"key": "ABC-2", "fields": {"updated": "2026-01-02T11:00:00.000+0100"}}
        with mock.patch("jirafe.mirror.time.time", return_value=ten / 1000 + 60):
            self.assertEqual(self.mirror.recently_updated(15), {"ABC-1": ten, "ABC-2": ten})
        self.mirror.sync_board()
        with mock.patch("jirafe.mirror.time.time", return_value=ten / 1000 + 3600 + 60):
            self.assertEqual(self.mirror.recently_updated(15), {"ABC-2": ten + 3_600_000})

    def test_recently_updated_read_from_the_files_after_a_restart(self):
        ten = 1_767_344_400_000
        restarted = IssueMirror(
            self.directory.name,
            self.jira,
            42,
            BASE_DETAIL_FIELDS
        )
        with mock.patch("jirafe.mirror.time.time", return_value=ten / 1000 + 90):
            self.assertEqual(restarted.recently_updated(2), {"ABC-1": ten, "ABC-2": ten})
            self.assertEqual(restarted.recently_updated(1), {})
        self.assertEqual(self.jira.paths, [])

    def test_frequent_pass_reuses_the_active_sprints(self):
        self.mirror.sync_board(refresh_sprints=False)
        self.assertFalse([path for path in self.jira.paths if "/sprint?" in path])
        self.mirror.sync_board()
        self.assertTrue([path for path in self.jira.paths if "/sprint?" in path])

    def test_watched_until_the_page_stops_asking(self):
        self.assertFalse(self.mirror.watched())
        with mock.patch("jirafe.mirror.time.monotonic", return_value=1000):
            self.mirror.watch()
            self.assertTrue(self.mirror.watched())
        with mock.patch("jirafe.mirror.time.monotonic", return_value=1000 + WATCH_TTL_S):
            self.assertFalse(self.mirror.watched())
