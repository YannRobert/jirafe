import json
import threading
from collections import deque

from .constants import MAX_TRANSITION_STEPS
from .files import write_json


class Workflows:
    """Which status leads to which, per workflow, learned from the transitions Jira lists for each issue.

    Jira only shows a workflow's graph to administrators: everyone else sees, for one issue at a time, the
    transitions out of its current status. Gathered over the board's issues, they draw most of the graph,
    which is kept in a file so that it survives a restart."""

    def __init__(self, path):
        self._path = path
        self._lock = threading.Lock()
        try:
            saved = json.loads(path.read_bytes())
            self._graphs, self._names = saved["graphs"], saved["names"]
        except (FileNotFoundError, ValueError, KeyError, TypeError):
            self._graphs, self._names = {}, {}

    def learn(
            self,
            workflow,
            status,
            transitions
    ):
        """Adds the transitions seen out of a status ({"id", "name"}, as in an issue). They are only ever added: one issue may lack some
        another has (a condition on the assignee, for instance), and a path is checked step by step against
        what Jira offers anyway."""
        with self._lock:
            edges = self._graphs.setdefault(workflow, {}).setdefault(str(status["id"]), {})
            before = dict(edges), dict(self._names)
            if status.get("name"):
                self._names[str(status["id"])] = status["name"]
            for transition in transitions:
                # A transition Jira offers names the edge better than a status change seen in the history.
                edges.setdefault(str(transition["to"]["id"]), transition["name"])
                if "id" in transition:
                    edges[str(transition["to"]["id"])] = transition["name"]
                # Statuses a path goes through are not all on the board: their name comes from here.
                if transition["to"].get("name"):
                    self._names[str(transition["to"]["id"])] = transition["to"]["name"]
            if (edges, self._names) != before:
                write_json(
                    self._path,
                    {"graphs": self._graphs, "names": self._names}
                )

    def learn_history(
            self,
            workflow,
            histories
    ):
        """Adds the status changes an issue's history (changelog) records: the transitions of statuses no
        issue of the board is in right now, those a path often has to go through."""
        moves = {}
        for history in histories:
            for item in history.get("items", []):
                if item.get("field") == "status" and item.get("from") and item.get("to") and item["from"] != item["to"]:
                    moves.setdefault((item["from"], item.get("fromString")), []).append(
                        {"name": item.get("toString") or item["to"], "to": {"id": item["to"], "name": item.get("toString")}}
                    )
        for (status, name), transitions in moves.items():
            self.learn(
                workflow,
                {"id": status, "name": name},
                transitions
            )

    def name(self, status):
        with self._lock:
            return self._names.get(str(status), str(status))

    def route(
            self,
            workflow,
            start,
            target,
            live
    ):
        """Statuses to go through, target included, fewest transitions first; None when no known path leads
        there. Out of the start status, only what Jira offers right now (live) counts."""
        return self.routes(
            workflow,
            start,
            live
        ).get(str(target))

    def routes(
            self,
            workflow,
            start,
            live
    ):
        """Path to every status reachable from start, as for route(), in at most MAX_TRANSITION_STEPS."""
        start = str(start)
        with self._lock:
            # The issue types of a project often share one workflow, which only an administrator can see: a
            # status never seen with this type borrows the transitions seen with the project's other types.
            # Each step being checked against Jira before it is taken, a wrong guess costs a refused move.
            project = workflow.split("/")[0]
            graph = {}
            for other, edges in self._graphs.items():
                if other.split("/")[0] == project:
                    for status, following in edges.items():
                        graph.setdefault(status, {}).update(following)
            graph.update(self._graphs.get(workflow, {}))
            paths = {start: []}
            queue = deque([start])
            while queue:
                status = queue.popleft()
                if len(paths[status]) == MAX_TRANSITION_STEPS:
                    continue
                edges = [str(t["to"]["id"]) for t in live] if status == start else graph.get(status, {})
                for following in edges:
                    if following not in paths:
                        paths[following] = [*paths[status], following]
                        queue.append(following)
        del paths[start]
        return paths


def workflow_of(issue):
    """Jira applies one workflow per project and issue type."""
    return f"{issue['key'].rsplit('-', 1)[0]}/{issue['fields']['issuetype']['id']}"
