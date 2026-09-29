"""Configuration specific to a Jira instance: host, board, custom fields and board views.

These values differ from one instance to another and do not belong in the repository: they are read from a
JSON file in the user's configuration directory (see paths.py), which command-line options override.
"""
import json
import re

from .constants import FIELD_ROLES, MAX_VIEWS

CUSTOM_FIELD = re.compile(r"^customfield_[0-9]+$")


class ConfigError(Exception):
    pass


def load_config(
        path,
        required
):
    """Returns the validated content of the file, or {} if it is missing and optional (default path)."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        if required:
            raise ConfigError(f"configuration file not found: {path}")
        return {}
    try:
        config = json.loads(raw)
    except ValueError as error:
        raise ConfigError(f"{path}: invalid JSON ({error})")
    if not isinstance(config, dict):
        raise ConfigError(f"{path}: a JSON object is expected")
    return validate(
        config,
        str(path)
    )


def validate(
        config,
        source
):
    unknown = set(config) - {"jiraHost", "boardId", "fields", "views"}
    if unknown:
        raise ConfigError(f"{source}: unknown key(s): {', '.join(sorted(unknown))}")
    host = config.get("jiraHost")
    if host is not None and not (isinstance(host, str) and re.match(r"^https?://[^/?#]+", host)):
        raise ConfigError(f"{source}: jiraHost must be an http(s)://… URL")
    board = config.get("boardId")
    if board is not None and not (isinstance(board, int) and not isinstance(board, bool) and board > 0):
        raise ConfigError(f"{source}: boardId must be a positive integer")
    fields = config.get("fields", {})
    if not isinstance(fields, dict):
        raise ConfigError(f"{source}: fields must be an object {{role: \"customfield_…\"}}")
    for role, field in fields.items():
        if role not in FIELD_ROLES:
            raise ConfigError(f"{source}: unknown field role \"{role}\" (known: {', '.join(FIELD_ROLES)})")
        # The field name ends up in the URL of Jira requests: nothing but a field id.
        if not (isinstance(field, str) and CUSTOM_FIELD.match(field)):
            raise ConfigError(f"{source}: fields.{role} must look like customfield_12345")
    validate_views(
        config.get("views", []),
        source
    )
    return config


def validate_views(
        views,
        source
):
    expected = f"{source}: views must be a list of {{\"label\": …, \"from\": \"column name\"}}"
    if not isinstance(views, list) or len(views) > MAX_VIEWS:
        raise ConfigError(f"{expected}, {MAX_VIEWS} at most")
    starts = set()
    for view in views:
        if not (
            isinstance(view, dict)
            and set(view) == {"label", "from"}
            and all(isinstance(view[k], str) and view[k].strip() for k in ("label", "from"))
        ):
            raise ConfigError(expected)
        # The page compares column names case-insensitively: two views cannot start at the same column.
        start = view["from"].lower()
        if start in starts:
            raise ConfigError(f"{source}: two views start at column \"{view['from']}\"")
        starts.add(start)
