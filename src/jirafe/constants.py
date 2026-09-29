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
# Type and priority icons and avatars: identical from one reload to the next, the browser keeps them for
# a day instead of requesting them again at every render.
IMAGE_MAX_AGE_S = 24 * 3600
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
# On Windows, replacing a file another thread is reading fails (PermissionError): the read lasts a few
# milliseconds, a few spaced attempts are enough.
REPLACE_ATTEMPTS = 5
REPLACE_RETRY_DELAY_S = 0.05
ISSUE_KEY = re.compile(r"^[A-Z][A-Z0-9_]+-[0-9]+$")
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
# The history (changelog) comes in the same request as the issue: no extra call.
ISSUE_EXPAND = "renderedFields,changelog"
CONFIG_PLACEHOLDER = b"__CONFIG__"
# Below this age, the local copy of an issue (synced when the detail was opened or by the background sync)
# is returned as is: reopening an issue or switching tabs costs no request to Jira.
ISSUE_FRESH_S = 30
RANK_PATH = "rest/agile/1.0/issue/rank"
ASSIGNEE_PATH = "rest/api/2/issue/{key}/assignee"
TRANSITIONS_PATH = "rest/api/2/issue/{key}/transitions"
TRANSITION_ID = re.compile(r"^[0-9]{1,10}$")
# Jira Server / Data Center login: letters (accented included), digits and the usual separators. Kept
# narrow on purpose: whatever the page sends, only something shaped like a login reaches a Jira write.
USER_LOGIN = re.compile(r"^[\w.@+'-]{1,255}$")
MAX_WRITE_BODY_BYTES = 4096
# Windows of the counter of requests to Jira, like the load average: 1, 5 and 15 minutes.
METER_WINDOWS_S = (60, 5 * 60, 15 * 60)
# Relayed prefixes that are only images (icons, avatars, thumbnails): counted apart from data.
IMAGE_PREFIXES = ("secure/viewavatar", "secure/useravatar", "secure/thumbnail/", "secure/attachment/", "images/")
