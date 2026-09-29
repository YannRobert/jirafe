import tempfile
import unittest
from pathlib import Path

from jirafe.config import ConfigError, load_config


class LoadConfigTest(unittest.TestCase):

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "jirafe.json"

    def tearDown(self):
        self.directory.cleanup()

    def write(self, content):
        self.path.write_text(
            content,
            encoding="utf-8"
        )

    def test_missing_default_file_gives_empty_configuration(self):
        self.assertEqual(
            load_config(
                self.path,
                required=False
            ),
            {}
        )

    def test_missing_explicit_file_is_an_error(self):
        with self.assertRaises(ConfigError):
            load_config(
                self.path,
                required=True
            )

    def test_valid_configuration(self):
        self.write('{"jiraHost": "https://jira.example.com", "boardId": 42, "fields": {"developer": "customfield_1"}}')
        config = load_config(
            self.path,
            required=True
        )
        self.assertEqual(
            config["fields"],
            {"developer": "customfield_1"}
        )

    def test_views(self):
        self.write('{"views": [{"label": "Dev", "from": "À faire"}, {"label": "QA", "from": "Ready for QA"}]}')
        config = load_config(
            self.path,
            required=True
        )
        self.assertEqual(
            [view["label"] for view in config["views"]],
            ["Dev", "QA"]
        )

    def test_rejections(self):
        invalid = {
            "broken JSON": "{",
            "unknown key": '{"jiraHot": "https://jira.example.com"}',
            "host without scheme": '{"jiraHost": "jira.example.com"}',
            "non-integer board": '{"boardId": "42"}',
            "boolean board": '{"boardId": true}',
            "unknown role": '{"fields": {"author": "customfield_1"}}',
            # The field name ends up in the URL of Jira requests.
            "field injecting a parameter": '{"fields": {"developer": "customfield_1&expand=x"}}',
            "views not a list": '{"views": {"label": "Dev", "from": "À faire"}}',
            "view without column": '{"views": [{"label": "Dev"}]}',
            "view with blank label": '{"views": [{"label": " ", "from": "À faire"}]}',
            "view with unknown key": '{"views": [{"label": "Dev", "from": "À faire", "to": "Done"}]}',
            "two views on the same column": '{"views": [{"label": "A", "from": "In Progress"}, {"label": "B", "from": "in progress"}]}',
            "too many views": '{"views": [%s]}' % ", ".join('{"label": "V", "from": "C%d"}' % i for i in range(9)),
        }
        for case, content in invalid.items():
            with self.subTest(case):
                self.write(content)
                with self.assertRaises(ConfigError):
                    load_config(
                        self.path,
                        required=True
                    )
