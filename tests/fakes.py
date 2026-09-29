"""Jira test doubles: the tests make no network request."""
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
        return self.response
