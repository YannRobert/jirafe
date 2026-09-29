"""Jirafe: the Jira board of the current sprint, served from a local copy.

The page (jirafe/static/index.html) only talks to this server:
    /jira/<path>          →  <jira>/<path>   (relay, JIRA_PAT as a Bearer header)
    /issue/<key>          →  local copy of the issue (mirror), without calling Jira
    /issue/<key>?sync=1   →  resyncs the issue from Jira, then returns it — unless the local copy is less
                             than ISSUE_FRESH_S seconds old (&force=1 overrides)
    /transitions/<key>    →  <jira>/rest/api/2/issue/<key>/transitions   (read)
    PUT /rank             →  <jira>/rest/agile/1.0/issue/rank   (reorders an issue on the board)
    PUT /assignee         →  <jira>/rest/api/2/issue/<key>/assignee
    PUT /transition       →  <jira>/rest/api/2/issue/<key>/transitions   (changes an issue's status)
    /changes              →  when the background sync last found a changed issue; marks the page as watching
    /stats                →  requests made to Jira over 1, 5 and 15 minutes, by origin, without calling Jira

The relay keeps the PAT out of the browser and lets the page show Jira icons and avatars, which require
authentication. Only GET is relayed, to an allow-list of paths, and the server only listens on 127.0.0.1.
The only writes are the three PUT above, which only accept a body built here from validated values (issue
keys, a login, a transition id) — the PAT cannot write anything else.

The whole board (columns, sprints, issues, epics) fits in one call: allData.json, the one Jira's own board
page uses — ~5 KB compressed, against ~250 KB for the agile API without a field filter.

Local mirror: one JSON file per issue under --mirror-dir (outside the repository), with its sync date. A
thread keeps it up to date: full sweep of the active sprints at startup then once a day, and in between,
every --sync-interval seconds (every WATCH_INTERVAL_S while a page is watching), only the issues modified
since the previous pass.

Usage:
    ./jirafe.sh                                     # Linux / macOS: starts the server and opens the browser
    jirafe.cmd                                      # Windows: same
    cd src && python3 -m jirafe --board 42 --port 9101

Portable across Windows / Linux / macOS, standard library only. Every file is read and written as explicit
UTF-8: on Windows, the default encoding is cp1252.

Requirement: JIRA_PAT (Jira personal access token) in the environment.
"""
import argparse
import os
import sys
import threading
import webbrowser
from http.server import ThreadingHTTPServer
from pathlib import Path

from .config import ConfigError, load_config
from .constants import DEFAULT_PORT, DEFAULT_SYNC_INTERVAL_S
from .handler import make_handler
from .jira import JiraClient
from .meter import RequestMeter
from .mirror import IssueMirror, detail_fields, run_background_sync
from .paths import cache_dir, default_config_file
from .upstream import UpstreamPool


class JirafeServer(ThreadingHTTPServer):
    # On Windows, SO_REUSEADDR lets a second process listen on a port already taken, without error: two
    # servers would then share the requests. Elsewhere, it only avoids waiting after a shutdown.
    allow_reuse_address = os.name != "nt"


def main():
    # Redirected Windows console (file, pipe): cp1252 cannot write "→"; an unencodable character is replaced
    # rather than crashing the server.
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(
            encoding="utf-8",
            errors="replace"
        )
    parser = argparse.ArgumentParser(prog="jirafe", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="local listening port (default: %(default)s)")
    parser.add_argument("--config", type=Path, help=f"JSON configuration file (default: {default_config_file()})")
    parser.add_argument("--jira-host", help="URL of the Jira instance (overrides jiraHost from the configuration)")
    parser.add_argument("--board", type=int, help="Jira board id, or rapidView (overrides boardId from the configuration)")
    parser.add_argument("--mirror-dir", type=Path, default=cache_dir(), help="directory of the local copy of issues (default: %(default)s)")
    parser.add_argument("--sync-interval", type=int, default=DEFAULT_SYNC_INTERVAL_S, help="seconds between two background syncs (default: %(default)s)")
    parser.add_argument("--quiet", action="store_true", help="do not log every request")
    parser.add_argument("--open", action="store_true", help="open the board in the browser once the server is ready")
    args = parser.parse_args()

    try:
        config = load_config(
            args.config or default_config_file(),
            required=args.config is not None
        )
    except ConfigError as error:
        sys.exit(f"Invalid configuration: {error}")
    jira_host = (args.jira_host or config.get("jiraHost") or "").rstrip("/")
    board_id = args.board or config.get("boardId")
    if not jira_host or not board_id:
        sys.exit(
            f"Jira instance and board to specify: in {args.config or default_config_file()} "
            "(template: jirafe.example.json) or with --jira-host and --board."
        )
    jira_token = os.environ.get("JIRA_PAT")
    if not jira_token:
        sys.exit("JIRA_PAT is not set in the environment: cannot query Jira.")
    custom_fields = config.get("fields", {})
    settings = {
        "jira_host": jira_host,
        "jira_token": jira_token,
        "quiet": args.quiet,
        "public": {
            "jiraWeb": jira_host,
            "boardId": board_id,
            "fields": custom_fields,
            "views": config.get("views", []),
        },
    }
    meter = RequestMeter()
    upstream = UpstreamPool(meter)
    mirror = IssueMirror(
        args.mirror_dir,
        JiraClient(
            settings["jira_host"],
            jira_token,
            upstream
        ),
        board_id,
        detail_fields(custom_fields)
    )
    try:
        server = JirafeServer(
            ("127.0.0.1", args.port),
            make_handler(
                settings,
                upstream,
                mirror,
                meter
            )
        )
    except OSError as error:
        # Port taken: most often, Jirafe is already running (second double-click on the launcher).
        print(f"Port {args.port} unavailable ({error.strerror}): Jirafe is probably already running.")
        if args.open:
            webbrowser.open(f"http://localhost:{args.port}")
            return
        sys.exit(1)
    threading.Thread(
        target=run_background_sync,
        args=(mirror, args.sync_interval, args.quiet),
        daemon=True
    ).start()
    print(f"Jirafe, the sprint board: http://localhost:{args.port}")
    print(f"Local copy of issues: {mirror.status()['directory']}")
    # The server is already listening (the constructor opened the port): the page never hits a refused connection.
    if args.open:
        webbrowser.open(f"http://localhost:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass

