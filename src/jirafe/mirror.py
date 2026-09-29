import http.client
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from .constants import (
    BASE_DETAIL_FIELDS,
    FULL_SYNC_INTERVAL_S,
    ISSUE_EXPAND,
    SEARCH_PAGE_SIZE,
    SYNC_OVERLAP_MIN,
    WATCH_INTERVAL_S,
    WATCH_TTL_S,
)
from .files import write_json
from .jira import JiraError
from .workflow import Workflows, workflow_of


class IssueMirror:
    """Local copy of the board's issues: one JSON file per issue, written atomically."""

    def __init__(
            self,
            directory,
            jira,
            board_id,
            fields
    ):
        self._issues = Path(directory) / str(board_id) / "issues"
        self._state_file = Path(directory) / str(board_id) / "sync-state.json"
        self._issues.mkdir(parents=True, exist_ok=True)
        self._jira = jira
        self._board_id = board_id
        self._fields = fields
        # What determines the content of a local copy: if it changes, the next pass is a full one.
        self._signature = f"{fields}&expand={ISSUE_EXPAND}"
        self._lock = threading.Lock()
        self._watched_at = None
        self.workflows = Workflows(Path(directory) / str(board_id) / "workflows.json")
        # Last time a pass found an issue that differs from its local copy (epoch seconds): the page reloads
        # its board when it is older.
        self.changed_at = None

    def read(self, key):
        try:
            return json.loads((self._issues / f"{key}.json").read_bytes())
        except (FileNotFoundError, ValueError):
            return None

    def sync_issue(self, key):
        issue = self._jira.get_json(
            f"rest/api/2/issue/{key}?fields={self._fields}&expand={ISSUE_EXPAND}",
            "detail"
        )
        return self._write(issue)

    def watch(self):
        """A page is showing the board: until WATCH_TTL_S without news from it, passes run every
        WATCH_INTERVAL_S."""
        self._watched_at = time.monotonic()

    def watched(self):
        return self._watched_at is not None and time.monotonic() - self._watched_at < WATCH_TTL_S

    def sync_board(self, refresh_sprints=True):
        """Full pass if the last one is more than a day old, incremental otherwise; returns the number of issues
        written. One pass at a time.
        An incremental pass first asks only for the modification date of recently updated issues, then the
        whole of those that differ from their local copy: frequent passes stay light, and an issue already
        resynced after a write from the page is not fetched again."""
        with self._lock:
            state = self._read_state()
            now = time.time()
            # Field list changed: existing copies lack the new fields, so the pass is a full one.
            full = now - state.get("fullSyncAt", 0) > FULL_SYNC_INTERVAL_S or state.get("fields") != self._signature
            # Active sprints rarely change: the frequent passes reuse those of the last regular one.
            if refresh_sprints or full or "sprints" not in state:
                state["sprints"] = [sprint["id"] for sprint in self._jira.get_json(
                    f"rest/agile/1.0/board/{self._board_id}/sprint?state=active",
                    "sync"
                )["values"]]
            if not state["sprints"]:
                return 0
            jql = f"sprint in ({','.join(str(sprint) for sprint in state['sprints'])})"
            if full:
                issues = self._search(jql)
            else:
                minutes = int((now - state["syncAt"]) / 60) + SYNC_OVERLAP_MIN
                issues = self._search_changed(f"{jql} AND updated >= -{minutes}m")
            written = 0
            for issue in issues:
                previous = self.read(issue["key"])
                if not previous or previous["data"]["fields"].get("updated") != issue["fields"].get("updated"):
                    self.changed_at = time.time()
                self._write(issue)
                written += 1
            state["syncAt"] = now
            if full:
                state["fullSyncAt"] = now
                state["fields"] = self._signature
            state["lastCount"] = written
            write_json(
                self._state_file,
                state
            )
            return written

    def status(self):
        state = self._read_state()
        return {
            "syncedAt": iso(state["syncAt"]) if "syncAt" in state else None,
            "fullSyncedAt": iso(state["fullSyncAt"]) if "fullSyncAt" in state else None,
            "issues": sum(1 for _ in self._issues.glob("*.json")),
            "directory": str(self._issues),
        }

    def _search_changed(self, jql):
        stale = [
            issue["key"] for issue in self._search(
                jql,
                "updated",
                light=True
            )
            if (self.read(issue["key"]) or {}).get("data", {}).get("fields", {}).get("updated") != issue["fields"].get("updated")
        ]
        for start in range(0, len(stale), SEARCH_PAGE_SIZE):
            yield from self._search(f"key in ({','.join(stale[start:start + SEARCH_PAGE_SIZE])})")

    def _search(
            self,
            jql,
            fields=None,
            light=False
    ):
        expand = "" if light else f"&expand={ISSUE_EXPAND}"
        start = 0
        while True:
            page = self._jira.get_json(
                f"rest/api/2/search?jql={quote(jql)}&fields={fields or self._fields}{expand}"
                f"&startAt={start}&maxResults={SEARCH_PAGE_SIZE}",
                "sync"
            )
            yield from page["issues"]
            start += len(page["issues"])
            if not page["issues"] or start >= page["total"]:
                return

    def _write(self, issue):
        # Only the workflow's graph needs them: the transitions of the moment are read again before a move.
        transitions = issue.pop("transitions", None)
        if transitions is not None:
            self.workflows.learn(
                workflow_of(issue),
                issue["fields"]["status"],
                transitions
            )
        if "changelog" in issue:
            # Before slimming: the history's status changes carry the status ids the workflow's graph needs.
            if "issuetype" in issue["fields"]:
                self.workflows.learn_history(
                    workflow_of(issue),
                    issue["changelog"].get("histories", [])
                )
            issue["changelog"] = {"histories": [slim_history(history) for history in issue["changelog"].get("histories", [])]}
        entry = {"key": issue["key"], "syncedAt": iso(time.time()), "data": issue}
        write_json(
            self._issues / f"{issue['key']}.json",
            entry
        )
        return entry

    def _read_state(self):
        try:
            return json.loads(self._state_file.read_bytes())
        except (FileNotFoundError, ValueError):
            return {}


def detail_fields(custom_fields):
    """Fields requested from Jira: the standard fields, plus the configured custom fields."""
    return ",".join([BASE_DETAIL_FIELDS, *sorted(set(custom_fields.values()))])


def slim_history(history):
    """A history entry reduced to what the detail panel shows: Jira repeats the whole author (e-mail, four
    avatar sizes…) on every change, which doubles the weight of the issue."""
    author = history.get("author") or {}
    return {
        "author": {
            "name": author.get("name"),
            "displayName": author.get("displayName"),
            "avatarUrls": {"48x48": (author.get("avatarUrls") or {}).get("48x48")},
        },
        "created": history.get("created"),
        "items": [
            {"field": item.get("field"), "from": item.get("fromString"), "to": item.get("toString")}
            for item in history.get("items", [])
        ],
    }


def iso(epoch_seconds):
    return datetime.fromtimestamp(epoch_seconds, timezone.utc).isoformat(timespec="seconds")


def run_background_sync(
        mirror,
        interval_s,
        quiet
):
    """A pass every interval_s; every WATCH_INTERVAL_S while a page is watching, so that a change made in
    Jira shows in it within a minute rather than five."""
    last_regular = None
    while True:
        started = time.monotonic()
        regular = last_regular is None or started - last_regular >= interval_s
        if regular or mirror.watched():
            if regular:
                last_regular = started
            try:
                written = mirror.sync_board(refresh_sprints=regular)
                # The frequent passes mostly find nothing: only the regular ones are always logged.
                if not quiet and (regular or written):
                    print(f"[mirror] {written} issue(s) synced in {time.monotonic() - started:.1f} s", flush=True)
            except (OSError, http.client.HTTPException, JiraError, ValueError, KeyError) as error:
                print(f"[mirror] sync failed: {error}", flush=True)
        time.sleep(min(interval_s, WATCH_INTERVAL_S))
