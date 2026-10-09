"""Jirafe constants, gathered in one place rather than hard-coded in each module."""
import re
from pathlib import Path

APP_NAME = "jirafe"
CONFIG_FILE_NAME = "config.json"
DEFAULT_PORT = 8766
# Content-Encoding: gzip responses are relayed as is, the browser decompresses them.
FORWARDED_RESPONSE_HEADERS = ("Content-Encoding", "ETag", "Last-Modified")
# The only relayed paths: what the page reads, nothing else — the PAT must not be usable for anything more.
RELAYED_PREFIXES = (
    "rest/greenhopper/1.0/xboard/work/allData.json",
    "rest/greenhopper/1.0/rapidviewconfig/editmodel.json",
    "rest/api/2/myself",
    "rest/api/2/user/assignable/search",
    "rest/agile/1.0/board/",
    "secure/viewavatar",
    "secure/useravatar",
    "secure/attachment/",
    "secure/thumbnail/",
    "images/",
)
# Type and priority icons, avatars, attachments: Jira gives a new URL when the image changes (avatarId,
# attachment id), so the browser keeps them for a week, without revalidating them on reload (immutable),
# instead of asking Jira again every day. The browser's cache is enough: the server runs on the same
# machine, a cache of its own would only duplicate it.
IMAGE_MAX_AGE_S = 7 * 24 * 3600
UPSTREAM_TIMEOUT_S = 30
# A connection idle for longer is closed rather than reused: the proxy or the server has probably already
# dropped it, and trying it would cost a round trip for nothing.
UPSTREAM_IDLE_S = 30
UPSTREAM_MAX_IDLE_PER_HOST = 12
STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_SYNC_INTERVAL_S = 5 * 60
FULL_SYNC_INTERVAL_S = 24 * 3600
# Overlap between two incremental passes: covers the clock skew with Jira and the duration of the pass.
SYNC_OVERLAP_MIN = 3
SEARCH_PAGE_SIZE = 50
# While a page is watching (it asks for GET /changes every 15 s), the incremental pass runs this often
# instead of every --sync-interval; without news from the page for WATCH_TTL_S, it slows down again.
WATCH_INTERVAL_S = 30
WATCH_TTL_S = 45
# The page highlights the cards of issues changed in Jira for less than this (recentMinutes in the
# configuration): within the same working session, what colleagues changed catches the eye.
DEFAULT_RECENT_MINUTES = 120
# A week: beyond it, "recent" no longer means anything on a sprint board.
MAX_RECENT_MINUTES = 7 * 24 * 60
# GET /activity: what the page lists since the last visit, or since yesterday for the stand-up — the moves
# between columns, the assignments and the comments. Read from the local copy only.
ACTIVITY_FIELDS = ("status", "assignee")
ACTIVITY_COMMENT_LENGTH = 300
# The mirror only follows the issues of the open sprints: further back, the list would be both long and
# incomplete.
MAX_ACTIVITY_DAYS = 31
# On Windows, replacing a file another thread is reading fails (PermissionError): the read lasts a few
# milliseconds, a few spaced attempts are enough.
REPLACE_ATTEMPTS = 5
REPLACE_RETRY_DELAY_S = 0.05
# Patterns end with \Z rather than $: $ also matches before a final line break, which would then reach the
# URL of a Jira request.
ISSUE_KEY = re.compile(r"^[A-Z][A-Z0-9_]+-[0-9]+\Z")
EPOCH_MS = re.compile(r"^[0-9]{1,15}\Z")
# Standard fields shown by the detail panel; custom fields are added to them according to the configuration.
BASE_DETAIL_FIELDS = (
    "summary,status,issuetype,priority,assignee,reporter,created,updated,labels,description,comment,"
    "fixVersions,components,issuelinks,subtasks,attachment,resolution,resolutiondate,duedate"
)
# Custom field roles the page can display. Their id (customfield_…) differs from one Jira instance to
# another: each instance declares its own in the configuration, the others are ignored.
FIELD_ROLES = (
    "storyPoints",
    "sprints",
    "criticality",
    "developer",
    "tester",
    "environments",
    "deliveredAt",
    "installedAt",
    "acceptedAt",
)
# Maximum number of board views: with the whole-board view, they fit on keys 1 to 9.
MAX_VIEWS = 8
# The history (changelog) comes in the same request as the issue: no extra call. So do the transitions out
# of its status, which teach the workflows' graph (workflow.py) without asking Jira for it.
ISSUE_EXPAND = "renderedFields,changelog,transitions"
CONFIG_PLACEHOLDER = b"__CONFIG__"
# Second line of defence behind the sanitising of the HTML rendered by Jira: a script slipped into a
# description or a comment would not run (only the page's own scripts carry the nonce, new at every load),
# nor could it send anything elsewhere. Images stay open to https: avatars may come from another host.
PAGE_CSP = (
    "default-src 'none'; script-src 'nonce-{nonce}'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; connect-src 'self'; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'none'"
)
PAGE_NONCE_BYTES = 16
# A relayed path is decoded this many times at most to look for a "..": a proxy then Jira may each decode
# it once (%252e → %2e → .). Beyond, the path is refused.
RELAY_DECODE_ROUNDS = 3
# Below this age, the local copy of an issue (synced when the detail was opened or by the background sync)
# is returned as is: reopening an issue or switching tabs costs no request to Jira.
ISSUE_FRESH_S = 30
RANK_PATH = "rest/agile/1.0/issue/rank"
ASSIGNEE_PATH = "rest/api/2/issue/{key}/assignee"
TRANSITIONS_PATH = "rest/api/2/issue/{key}/transitions"
# The status of an issue and the transitions out of it, in one read: a move plans its path from both.
LIVE_TRANSITIONS_PATH = "rest/api/2/issue/{key}?fields=status,issuetype&expand=transitions"
STATUS_ID = re.compile(r"^[0-9]{1,10}\Z")
# A move to a status the workflow does not lead to directly goes through the statuses in between, one
# transition each, going round the workflow if need be (from C back to B through D and A): the bound only
# stops a walk that would never end.
MAX_TRANSITION_STEPS = 20
# Jira Server / Data Center login: letters (accented included), digits and the usual separators. Kept
# narrow on purpose: whatever the page sends, only something shaped like a login reaches a Jira write.
USER_LOGIN = re.compile(r"^[\w.@+'-]{1,255}\Z")
MAX_WRITE_BODY_BYTES = 4096
# Windows of the counter of requests to Jira, like the load average: 1, 5 and 15 minutes.
METER_WINDOWS_S = (60, 5 * 60, 15 * 60)
# Relayed prefixes that are only images (icons, avatars, thumbnails): counted apart from data.
IMAGE_PREFIXES = ("secure/viewavatar", "secure/useravatar", "secure/thumbnail/", "secure/attachment/", "images/")
