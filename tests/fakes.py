"""Jira test doubles: the tests make no network request."""
import json
from urllib.parse import parse_qs, urlsplit


class FakeJira:
    """Answers IssueMirror's reads from in-memory issues, and records the requested paths."""

    def __init__(
            self,
            issues,
            sprints=({"id": 7},)
    ):
        self.issues = issues
        self.sprints = list(sprints)
        self.paths = []

    def get_json(
            self,
            path,
            origin
    ):
        self.paths.append(path)
        if "/sprint?" in path:
            return {"values": self.sprints}
        if path.startswith("rest/api/2/search"):
            jql = parse_qs(urlsplit(path).query)["jql"][0]
            # "key in (…)": the issues named; any other query: all of them.
            keys = jql[len("key in ("):-1].split(",") if jql.startswith("key in (") else None
            found = [dict(issue) for issue in self.issues if keys is None or issue["key"] in keys]
            return {"issues": found, "total": len(found)}
        key = path.split("?")[0].rsplit("/", 1)[1]
        return dict(next(issue for issue in self.issues if issue["key"] == key))


class FakeUpstream:
    """Stands in for UpstreamPool: returns a fixed response and records every request received."""

    def __init__(
            self,
            status=200,
            body=b"{}",
            headers=None
    ):
        self.response = (status, body, headers or {"Content-Type": "application/json"})
        # When set, answers each request instead of the fixed response.
        self.responder = None
        self.requests = []

    def get(
            self,
            url,
            headers,
            origin
    ):
        return self.request(
            "GET",
            url,
            headers,
            origin
        )

    def request(
            self,
            method,
            url,
            headers,
            origin,
            body=None
    ):
        self.requests.append({"method": method, "url": url, "headers": headers, "body": body})
        if self.responder:
            return self.responder(
                method,
                url,
                body
            )
        return self.response


class FakeWorkflow:
    """A Jira issue ABC-1 moving through a workflow: {status: {next status: transition id}}. Serves the
    live transitions read and applies the transitions posted, refusing those listed in refused."""

    def __init__(
            self,
            edges,
            status
    ):
        self.edges = edges
        self.status = status
        self.refused = set()

    def __call__(
            self,
            method,
            url,
            body
    ):
        if method == "POST":
            transition = json.loads(body)["transition"]["id"]
            if transition in self.refused:
                return 400, b'{"errorMessages": [], "errors": {"resolution": "Resolution is required"}}', {}
            self.status = next(to for to, id_ in self.edges[self.status].items() if id_ == transition)
            return 204, b"", {}
        issue = {
            "key": "ABC-1",
            "fields": {"status": {"id": self.status, "name": f"S{self.status}"}, "issuetype": {"id": "10"}},
            "transitions": [
                {"id": id_, "name": f"to S{to}", "to": {"id": to, "name": f"S{to}"}}
                for to, id_ in self.edges[self.status].items()
            ],
        }
        return 200, json.dumps(issue).encode(), {"Content-Type": "application/json"}
