import tempfile
import unittest
from pathlib import Path

from jirafe.constants import MAX_TRANSITION_STEPS
from jirafe.workflow import Workflows, workflow_of


def transitions(*statuses):
    return [{"id": f"t{status}", "name": f"to {status}", "to": {"id": status, "name": f"S{status}"}} for status in statuses]


class WorkflowsTest(unittest.TestCase):

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "workflows.json"
        self.workflows = Workflows(self.path)

    def tearDown(self):
        self.directory.cleanup()

    def learn(
            self,
            status,
            *following
    ):
        self.workflows.learn(
            "ABC/10",
            {"id": status},
            transitions(*following)
        )

    def test_shortest_path_through_learned_statuses(self):
        self.learn("2", "3", "1")
        self.learn("3", "4")
        self.assertEqual(
            self.workflows.route(
                "ABC/10",
                "1",
                "4",
                transitions("2", "4")
            ),
            ["4"]
        )
        self.assertEqual(
            self.workflows.route(
                "ABC/10",
                1,
                4,
                transitions("2")
            ),
            ["2", "3", "4"]
        )

    def test_out_of_the_start_only_what_jira_offers_counts(self):
        # Learned from another issue: 1 → 3. This one, now, only goes to 2.
        self.learn("1", "3")
        self.learn("2", "5")
        self.assertIsNone(self.workflows.route(
            "ABC/10",
            "1",
            "3",
            transitions("2")
        ))
        self.assertEqual(
            self.workflows.routes(
                "ABC/10",
                "1",
                transitions("2")
            ),
            {"2": ["2"], "5": ["2", "5"]}
        )

    def test_transitions_seen_are_added_not_replaced(self):
        self.learn("1", "2")
        self.learn("1", "3")
        self.assertEqual(
            set(self.workflows.routes(
                "ABC/10",
                "0",
                transitions("1")
            )),
            {"1", "2", "3"}
        )

    def test_projects_are_kept_apart(self):
        self.learn("2", "3")
        self.assertIsNone(self.workflows.route(
            "XYZ/10",
            "1",
            "3",
            transitions("2")
        ))

    def test_path_goes_round_the_workflow(self):
        # A → B → C → D → A: from C, B is only reached through D then A.
        for status, following in (("A", "B"), ("B", "C"), ("C", "D"), ("D", "A")):
            self.learn(status, following)
        self.assertEqual(
            self.workflows.route(
                "ABC/10",
                "C",
                "B",
                transitions("D")
            ),
            ["D", "A", "B"]
        )

    def test_status_changes_of_the_history_are_learned(self):
        self.workflows.learn_history(
            "ABC/10",
            [
                {"items": [{"field": "status", "from": "2", "fromString": "S2", "to": "3", "toString": "S3"}]},
                {"items": [{"field": "assignee", "from": "alice", "to": "bob"}]},
                {"items": [{"field": "status", "from": "3", "fromString": "S3", "to": "3", "toString": "S3"}]},
            ]
        )
        self.assertEqual(
            self.workflows.route(
                "ABC/10",
                "1",
                "3",
                transitions("2")
            ),
            ["2", "3"]
        )
        self.assertEqual(self.workflows.name("2"), "S2")
        self.assertIsNone(self.workflows.route(
            "ABC/10",
            "1",
            "alice",
            transitions("2")
        ))

    def test_other_issue_types_of_the_project_fill_the_gaps(self):
        self.learn("2", "3")
        self.learn("3", "4")
        self.workflows.learn(
            "ABC/11",
            {"id": "2"},
            transitions("5")
        )
        # Status 2 seen with type 11 itself: its own transitions win; status 3 was only seen with type 10.
        self.assertEqual(
            self.workflows.routes(
                "ABC/11",
                "1",
                transitions("2", "3")
            ),
            {"2": ["2"], "3": ["3"], "5": ["2", "5"], "4": ["3", "4"]}
        )

    def test_paths_have_a_maximum_length(self):
        for status in range(1, MAX_TRANSITION_STEPS + 2):
            self.learn(str(status), str(status + 1))
        paths = self.workflows.routes(
            "ABC/10",
            "0",
            transitions("1")
        )
        self.assertEqual(max(len(path) for path in paths.values()), MAX_TRANSITION_STEPS)

    def test_graph_survives_a_restart(self):
        self.learn("2", "3")
        self.assertEqual(
            Workflows(self.path).route(
                "ABC/10",
                "1",
                "3",
                transitions("2")
            ),
            ["2", "3"]
        )

    def test_status_names_are_remembered(self):
        self.learn("2", "3")
        self.assertEqual(Workflows(self.path).name("3"), "S3")
        self.assertEqual(self.workflows.name(9), "9")
        self.workflows.learn(
            "ABC/10",
            {"id": "7", "name": "Start"},
            []
        )
        self.assertEqual(self.workflows.name("7"), "Start")

    def test_unreadable_file_starts_empty(self):
        self.path.write_text("{", encoding="utf-8")
        self.assertEqual(
            Workflows(self.path).routes(
                "ABC/10",
                "1",
                []
            ),
            {}
        )

    def test_one_workflow_per_project_and_issue_type(self):
        self.assertEqual(
            workflow_of({"key": "AB_C2-12", "fields": {"issuetype": {"id": "10"}}}),
            "AB_C2/10"
        )
