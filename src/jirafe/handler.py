import gzip
import http.client
import json
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlsplit

from .constants import (
    CONFIG_PLACEHOLDER,
    FORWARDED_RESPONSE_HEADERS,
    IMAGE_MAX_AGE_S,
    IMAGE_PREFIXES,
    ISSUE_FRESH_S,
    ISSUE_KEY,
    MAX_WRITE_BODY_BYTES,
    RANK_PATH,
    RELAYED_PREFIXES,
    STATIC_DIR,
)
from .jira import JiraError


def make_handler(
        settings,
        upstream,
        mirror,
        meter
):
    config = json.dumps(settings["public"]).replace("</", "<\\/").encode()

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
            elif self.path == "/stats":
                self.send_json(200, meter.snapshot())
            elif self.path.startswith("/issue/"):
                self.send_issue()
            else:
                self.send_json(404, {"message": "not found"})

        def do_PUT(self):
            if not self.host_allowed() or not self.same_origin():
                return
            if self.path != "/rank":
                self.send_json(404, {"message": "not found"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 < length <= MAX_WRITE_BODY_BYTES:
                self.close_connection = True
                self.send_json(400, {"message": "missing or oversized body"})
                return
            try:
                request = json.loads(self.rfile.read(length))
                key, before, after = request["issue"], request.get("before"), request.get("after")
            except (ValueError, KeyError, TypeError):
                self.send_json(400, {"message": "expected JSON body: {issue, before | after}"})
                return
            neighbour = before or after
            if (before is None) == (after is None) or not all(isinstance(k, str) and ISSUE_KEY.match(k) for k in (key, neighbour)):
                self.send_json(400, {"message": "one issue key, and exactly one neighbour (before or after)"})
                return
            self.rank(
                key,
                "rankBeforeIssue" if before else "rankAfterIssue",
                neighbour
            )

        def rank(
                self,
                key,
                position,
                neighbour
        ):
            try:
                status, body, headers = upstream.request(
                    "PUT",
                    f"{settings['jira_host']}/{RANK_PATH}",
                    {
                        "Authorization": "Bearer " + settings["jira_token"],
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    "write",
                    json.dumps({"issues": [key], position: neighbour}).encode()
                )
            except (OSError, http.client.HTTPException) as error:
                self.send_json(502, {"message": f"Jira unreachable: {error}"})
                return
            if headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
            # 204: ranked. 207: one response per issue, ours included, which may carry a refusal.
            errors = []
            if status == 207:
                entries = json.loads(body or b"{}").get("entries", [])
                errors = [message for entry in entries if entry.get("status", 200) >= 400 for message in entry.get("errors", ["refused"])]
            elif status >= 300:
                try:
                    errors = json.loads(body).get("errorMessages") or [f"Jira {status}"]
                except ValueError:
                    errors = [f"Jira {status}"]
            if errors:
                self.send_json(409 if status < 500 else 502, {"message": ", ".join(errors)})
            else:
                self.send_json(200, {"ranked": key})

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
