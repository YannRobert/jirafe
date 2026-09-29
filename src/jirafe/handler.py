import gzip
import http.client
import json
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlsplit

from .constants import (
    ASSIGNEE_PATH,
    CONFIG_PLACEHOLDER,
    FORWARDED_RESPONSE_HEADERS,
    IMAGE_MAX_AGE_S,
    IMAGE_PREFIXES,
    ISSUE_FRESH_S,
    ISSUE_KEY,
    LIVE_TRANSITIONS_PATH,
    MAX_TRANSITION_STEPS,
    MAX_WRITE_BODY_BYTES,
    RANK_PATH,
    RELAYED_PREFIXES,
    STATIC_DIR,
    STATUS_ID,
    TRANSITIONS_PATH,
    USER_LOGIN,
)
from .jira import JiraClient, JiraError
from .workflow import workflow_of


def make_handler(
        settings,
        upstream,
        mirror,
        meter
):
    config = json.dumps(settings["public"]).replace("</", "<\\/").encode()
    jira = JiraClient(
        settings["jira_host"],
        settings["jira_token"],
        upstream
    )

    def live_transitions(key):
        """The issue's status and the transitions Jira offers out of it right now, which also teach the
        workflow's graph."""
        issue = jira.get_json(
            LIVE_TRANSITIONS_PATH.format(key=key),
            "page"
        )
        status, transitions = issue["fields"]["status"], issue.get("transitions", [])
        mirror.workflows.learn(
            workflow_of(issue),
            status,
            transitions
        )
        return workflow_of(issue), status, transitions

    # The configuration is injected into the page: it can show its saved data without waiting for a first
    # round trip to this server. The page is read again on every request, so a change to index.html
    # applies at the next F5, without restarting the server.
    def page():
        return (STATIC_DIR / "index.html").read_bytes().replace(
            CONFIG_PLACEHOLDER,
            config
        )

    class Handler(BaseHTTPRequestHandler):

        # Connection kept between two browser requests; every response carries its Content-Length.
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            if not self.host_allowed():
                return
            if self.path in ("/", "/index.html") or self.path.startswith("/?"):
                self.send_body(
                    200,
                    page(),
                    {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-cache"}
                )
            elif self.path.startswith("/jira/"):
                relayed = self.path[len("/jira/"):]
                if not relayed.startswith(RELAYED_PREFIXES) or ".." in relayed:
                    self.send_json(403, {"message": "path not relayed"})
                    return
                self.relay(
                    settings["jira_host"] + "/" + relayed,
                    "images" if relayed.startswith(IMAGE_PREFIXES) else "page"
                )
            elif self.path == "/mirror/status":
                self.send_json(200, mirror.status())
            elif self.path == "/changes":
                # Asked by the page while it is visible: it is also what tells the mirror someone is watching.
                mirror.watch()
                self.send_json(200, {"changedAt": mirror.changed_at and int(mirror.changed_at * 1000)})
            elif self.path == "/stats":
                self.send_json(200, meter.snapshot())
            elif self.path.startswith("/issue/"):
                self.send_issue()
            elif self.path.startswith("/transitions/"):
                self.send_transitions()
            else:
                self.send_json(404, {"message": "not found"})

        def do_PUT(self):
            if not self.host_allowed() or not self.same_origin():
                return
            route = {"/rank": self.put_rank, "/assignee": self.put_assignee, "/transition": self.put_transition}.get(self.path)
            if route is None:
                self.send_json(404, {"message": "not found"})
                return
            request = self.read_json_body()
            if request is not None:
                route(request)

        def read_json_body(self):
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 < length <= MAX_WRITE_BODY_BYTES:
                self.close_connection = True
                self.send_json(400, {"message": "missing or oversized body"})
                return None
            try:
                request = json.loads(self.rfile.read(length))
            except ValueError:
                request = None
            if not isinstance(request, dict):
                self.send_json(400, {"message": "expected a JSON object"})
                return None
            return request

        def put_rank(self, request):
            key, before, after = request.get("issue"), request.get("before"), request.get("after")
            neighbour = before or after
            if (before is None) == (after is None) or not all(isinstance(k, str) and ISSUE_KEY.match(k) for k in (key, neighbour)):
                self.send_json(400, {"message": "one issue key, and exactly one neighbour (before or after)"})
                return
            position = "rankBeforeIssue" if before else "rankAfterIssue"
            response = self.write_jira(
                "PUT",
                RANK_PATH,
                {"issues": [key], position: neighbour}
            )
            if response is None:
                return
            status, body = response
            # 204: ranked. 207: one response per issue, ours included, which may carry a refusal.
            if status == 207:
                entries = json.loads(body or b"{}").get("entries", [])
                errors = [message for entry in entries if entry.get("status", 200) >= 400 for message in entry.get("errors", ["refused"])]
            else:
                errors = jira_errors(
                    status,
                    body
                )
            if errors:
                self.send_json(409 if status < 500 else 502, {"message": ", ".join(errors)})
            else:
                self.send_json(200, {"ranked": key})

        def put_assignee(self, request):
            # null unassigns; a missing "assignee" is an error rather than a silent unassignment.
            key, login = request.get("issue"), request.get("assignee", "")
            valid_login = login is None or (isinstance(login, str) and USER_LOGIN.match(login))
            if not (isinstance(key, str) and ISSUE_KEY.match(key)) or not valid_login:
                self.send_json(400, {"message": "one issue key, and an assignee login (null to unassign)"})
                return
            response = self.write_jira(
                "PUT",
                ASSIGNEE_PATH.format(key=key),
                {"name": login}
            )
            self.answer_issue_write(
                key,
                response,
                "assigned"
            )

        def put_transition(self, request):
            # A status rather than a transition: the workflow may only lead there through other statuses,
            # which this server goes through itself, one transition at a time.
            key, target = request.get("issue"), request.get("status")
            if not (isinstance(key, str) and ISSUE_KEY.match(key)) or not (isinstance(target, str) and STATUS_ID.match(target)):
                self.send_json(400, {"message": "one issue key, and a status id"})
                return
            try:
                start, passed, error = self.walk(
                    key,
                    target
                )
                if error and passed:
                    # Stopped halfway: the issue goes back to where it was rather than stay in a status
                    # nobody asked for — when the workflow allows it.
                    _, _, back_error = self.walk(
                        key,
                        str(start["id"])
                    )
                    where = f"left in {passed[-1]}, it could not go back to {start['name']}: {back_error}" if back_error else f"back to {start['name']}"
                    error = f"{error} ({where})"
            except (OSError, http.client.HTTPException, JiraError, ValueError, KeyError) as failure:
                passed, error = [], f"Jira unreachable: {failure}"
            try:
                entry = mirror.sync_issue(key)
            except (OSError, http.client.HTTPException, JiraError, ValueError):
                entry = None
            if error:
                self.send_json(409, {"message": error, "issue": entry})
            else:
                self.send_json(200, {"transitioned": key, "through": passed, "issue": entry})

        def walk(
                self,
                key,
                target
        ):
            """Transitions from status to status up to target, the path planned again at each step from what
            Jira offers: (start status, names of the statuses reached, error or None)."""
            start, passed = None, []
            for _ in range(MAX_TRANSITION_STEPS + 1):
                workflow, status, transitions = live_transitions(key)
                start = start or status
                if str(status["id"]) == target:
                    return start, passed, None
                path = mirror.workflows.route(
                    workflow,
                    status["id"],
                    target,
                    transitions
                )
                if not path:
                    return start, passed, f"no known path from {status['name']}"
                transition = next(t for t in transitions if str(t["to"]["id"]) == path[0])
                # Jira checks that the transition is available from the issue's current status.
                status_code, body = self.send_to_jira(
                    "POST",
                    TRANSITIONS_PATH.format(key=key),
                    {"transition": {"id": str(transition["id"])}}
                )
                errors = jira_errors(
                    status_code,
                    body
                )
                if errors:
                    return start, passed, f"{transition['name']} refused: {', '.join(errors)}"
                passed.append(transition["to"]["name"])
            return start, passed, "too many transitions"

        def answer_issue_write(
                self,
                key,
                response,
                done
        ):
            if response is None:
                return
            status, body = response
            errors = jira_errors(
                status,
                body
            )
            if errors:
                self.send_json(409 if status < 500 else 502, {"message": ", ".join(errors)})
                return
            # The local copy is resynced right away and returned: the page shows the change without a
            # second round trip, and the next background pass has nothing left to catch up on.
            try:
                entry = mirror.sync_issue(key)
            except (OSError, http.client.HTTPException, JiraError, ValueError):
                entry = None
            self.send_json(200, {done: key, "issue": entry})

        def write_jira(
                self,
                method,
                path,
                payload
        ):
            """Write to Jira with a body built here, never one relayed from the page; None once a 502 is sent."""
            try:
                return self.send_to_jira(
                    method,
                    path,
                    payload
                )
            except (OSError, http.client.HTTPException) as error:
                self.send_json(502, {"message": f"Jira unreachable: {error}"})
                return None

        def send_to_jira(
                self,
                method,
                path,
                payload
        ):
            status, body, headers = upstream.request(
                method,
                f"{settings['jira_host']}/{path}",
                {
                    "Authorization": "Bearer " + settings["jira_token"],
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                "write",
                json.dumps(payload).encode()
            )
            if headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
            return status, body

        def same_origin(self):
            # A third-party page open in the browser can target localhost: without this check, it would reorder
            # the board with the machine's PAT. The JSON Content-Type also forces a CORS preflight, which this
            # server does not answer.
            origin = self.headers.get("Origin", "")
            host = self.headers.get("Host", "")
            if origin == f"http://{host}" and self.headers.get("Content-Type", "").startswith("application/json"):
                return True
            self.close_connection = True
            self.send_json(403, {"message": "origin refused"})
            return False

        def send_issue(self):
            target = urlsplit(self.path)
            key = target.path[len("/issue/"):]
            if not ISSUE_KEY.match(key):
                self.send_json(400, {"message": "invalid issue key"})
                return
            cached = mirror.read(key)
            query = parse_qs(target.query)
            # A copy made before history was mirrored is never fresh: it has nothing to show it with.
            fresh = (
                cached
                and "changelog" in cached["data"]
                and time.time() - datetime.fromisoformat(cached["syncedAt"]).timestamp() < ISSUE_FRESH_S
            )
            if query.get("sync") != ["1"] or (fresh and query.get("force") != ["1"]):
                if cached:
                    self.send_json(200, cached)
                else:
                    self.send_json(404, {"message": "not in the local copy"})
                return
            try:
                self.send_json(200, mirror.sync_issue(key))
            except (OSError, http.client.HTTPException, JiraError, ValueError) as error:
                # Jira unreachable: the local copy is still useful, flagged as not refreshed.
                if cached:
                    self.send_json(200, {**cached, "syncError": str(error)})
                else:
                    self.send_json(502, {"message": f"sync failed: {error}"})

        def send_transitions(self):
            # Read only when a dragged card reaches another column: which columns it may go to, directly or
            # through other statuses. Fields a transition requires are not checked here: Jira lists some that
            # are always filled (summary), its refusal says better what is missing.
            key = self.path[len("/transitions/"):]
            if not ISSUE_KEY.match(key):
                self.send_json(400, {"message": "invalid issue key"})
                return
            try:
                workflow, status, transitions = live_transitions(key)
            except (OSError, http.client.HTTPException, JiraError, ValueError, KeyError) as error:
                self.send_json(502, {"message": f"transitions unavailable: {error}"})
                return
            self.send_json(
                200,
                {
                    "status": str(status["id"]),
                    "transitions": transitions,
                    "paths": {
                        target: [{"id": step, "name": mirror.workflows.name(step)} for step in path]
                        for target, path in mirror.workflows.routes(
                            workflow,
                            status["id"],
                            transitions
                        ).items()
                    },
                }
            )

        def host_allowed(self):
            # Refuses any other host name: otherwise a third-party page pointing its domain to 127.0.0.1
            # (DNS rebinding) would read Jira with the machine's PAT.
            if self.headers.get("Host", "").split(":")[0] in ("localhost", "127.0.0.1"):
                return True
            self.close_connection = True
            self.send_json(403, {"message": "host refused"})
            return False

        def relay(
                self,
                url,
                origin
        ):
            try:
                status, body, upstream_headers = upstream.get(
                    url,
                    {
                        "Authorization": "Bearer " + settings["jira_token"],
                        "Accept-Encoding": "gzip",
                        "Accept": "application/json, image/*;q=0.9, */*;q=0.5",
                    },
                    origin
                )
            except (OSError, http.client.HTTPException) as error:
                self.send_json(
                    502,
                    {"message": f"relay failed: {error}"}
                )
                return
            headers = {name: upstream_headers[name] for name in FORWARDED_RESPONSE_HEADERS if upstream_headers.get(name)}
            content_type = upstream_headers.get("Content-Type", "application/json")
            headers["Content-Type"] = content_type
            if status == 200 and content_type.startswith("image/"):
                headers["Cache-Control"] = f"private, max-age={IMAGE_MAX_AGE_S}"
            else:
                headers["Cache-Control"] = "no-store"
            self.send_body(
                status,
                body,
                headers
            )

        def send_body(
                self,
                status,
                body,
                headers
        ):
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def send_json(
                self,
                status,
                payload
        ):
            self.send_body(
                status,
                json.dumps(payload).encode(),
                {"Content-Type": "application/json", "Cache-Control": "no-store"}
            )

        def log_message(
                self,
                fmt,
                *args
        ):
            if not settings["quiet"]:
                super().log_message(fmt, *args)

    return Handler


def jira_errors(
        status,
        body
):
    """Messages of a refused Jira write: general ones, then those attached to a field."""
    if status < 300:
        return []
    try:
        payload = json.loads(body)
        messages = payload.get("errorMessages", []) + list(payload.get("errors", {}).values())
    except (ValueError, AttributeError, TypeError):
        messages = []
    return messages or [f"Jira {status}"]
