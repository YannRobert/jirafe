import gzip
import json


class JiraClient:
    """JSON reads from Jira, through the relay's connection pool."""

    def __init__(
            self,
            host,
            token,
            upstream
    ):
        self._host = host
        self._token = token
        self._upstream = upstream

    def get_json(
            self,
            path,
            origin
    ):
        status, body, headers = self._upstream.get(
            f"{self._host}/{path}",
            {"Authorization": "Bearer " + self._token, "Accept-Encoding": "gzip", "Accept": "application/json"},
            origin
        )
        if headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
        if status != 200:
            raise JiraError(f"Jira {status} on {path.split('?')[0]}")
        return json.loads(body)


class JiraError(Exception):
    pass
