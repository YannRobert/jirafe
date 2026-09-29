import http.client
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from .constants import (
    BASE_DETAIL_FIELDS,
    FULL_SYNC_INTERVAL_S,
    ISSUE_EXPAND,
    REPLACE_ATTEMPTS,
    REPLACE_RETRY_DELAY_S,
    SEARCH_PAGE_SIZE,
    SYNC_OVERLAP_MIN,
)
from .jira import JiraError


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

    def sync_board(self):
        """Full pass if the last one is more than a day old, incremental otherwise; returns the number of issues
        written. One pass at a time."""
        with self._lock:
            state = self._read_state()
            now = time.time()
            # Field list changed: existing copies lack the new fields, so the pass is a full one.
            full = now - state.get("fullSyncAt", 0) > FULL_SYNC_INTERVAL_S or state.get("fields") != self._signature
            sprints = self._jira.get_json(
                f"rest/agile/1.0/board/{self._board_id}/sprint?state=active",
                "sync"
            )["values"]
            if not sprints:
                return 0
            jql = f"sprint in ({','.join(str(s['id']) for s in sprints)})"
            if not full:
                minutes = int((now - state["syncAt"]) / 60) + SYNC_OVERLAP_MIN
                jql += f" AND updated >= -{minutes}m"
            written = 0
            for issue in self._search(jql):
                self._write(issue)
                written += 1
            state["syncAt"] = now
            if full:
                state["fullSyncAt"] = now
                state["fields"] = self._signature
            state["lastCount"] = written
            self._write_json(
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

    def _search(self, jql):
        start = 0
        while True:
            page = self._jira.get_json(
                f"rest/api/2/search?jql={quote(jql)}&fields={self._fields}&expand={ISSUE_EXPAND}"
                f"&startAt={start}&maxResults={SEARCH_PAGE_SIZE}",
                "sync"
            )
            yield from page["issues"]
            start += len(page["issues"])
            if not page["issues"] or start >= page["total"]:
                return

    def _write(self, issue):
        if "changelog" in issue:
            issue["changelog"] = {"histories": [slim_history(history) for history in issue["changelog"].get("histories", [])]}
        entry = {"key": issue["key"], "syncedAt": iso(time.time()), "data": issue}
        self._write_json(
            self._issues / f"{issue['key']}.json",
            entry
        )
        return entry

    def _read_state(self):
        try:
            return json.loads(self._state_file.read_bytes())
        except (FileNotFoundError, ValueError):
            return {}

    @staticmethod
    def _write_json(
            path,
            payload
    ):
        # One temporary file per thread: the background sync and an on-demand sync may write the same issue
        # at the same time.
        temporary = path.with_suffix(f".{threading.get_ident()}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8"
        )
        for attempt in range(1, REPLACE_ATTEMPTS + 1):
            try:
                os.replace(
                    temporary,
                    path
                )
                return
            except PermissionError:
                if attempt == REPLACE_ATTEMPTS:
                    temporary.unlink(missing_ok=True)
                    raise
                time.sleep(REPLACE_RETRY_DELAY_S)


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
    while True:
        started = time.monotonic()
        try:
            written = mirror.sync_board()
            if not quiet:
                print(f"[mirror] {written} issue(s) synced in {time.monotonic() - started:.1f} s", flush=True)
        except (OSError, http.client.HTTPException, JiraError, ValueError, KeyError) as error:
            print(f"[mirror] sync failed: {error}", flush=True)
        time.sleep(interval_s)
