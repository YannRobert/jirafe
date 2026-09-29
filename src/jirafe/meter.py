import threading
import time
from collections import deque

from .constants import METER_WINDOWS_S


class RequestMeter:
    """Timestamp of every request sent to Jira, kept for 15 minutes: enough to check that Jirafe does not
    flood the server, and to compare it with what the same browsing would cost in Jira itself."""

    def __init__(self):
        self._started_at = time.time()
        self._total = 0
        self._recent = deque()
        self._lock = threading.Lock()

    def record(self, origin):
        now = time.monotonic()
        with self._lock:
            self._total += 1
            self._recent.append((now, origin))
            self._forget_before(now - METER_WINDOWS_S[-1])

    def snapshot(self):
        now = time.monotonic()
        with self._lock:
            self._forget_before(now - METER_WINDOWS_S[-1])
            recent = list(self._recent)
            total = self._total
        windows = {}
        for window_s in METER_WINDOWS_S:
            by_origin = {}
            for at, origin in recent:
                if at >= now - window_s:
                    by_origin[origin] = by_origin.get(origin, 0) + 1
            windows[f"{window_s // 60}m"] = {"total": sum(by_origin.values()), "byOrigin": by_origin}
        return {"windows": windows, "sinceStart": total, "startedAt": int(self._started_at * 1000)}

    def _forget_before(self, horizon):
        while self._recent and self._recent[0][0] < horizon:
            self._recent.popleft()
