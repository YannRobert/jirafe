import base64
import http.client
import ssl
import threading
import time
import urllib.request
from urllib.parse import unquote, urlsplit

from .constants import UPSTREAM_IDLE_S, UPSTREAM_MAX_IDLE_PER_HOST, UPSTREAM_TIMEOUT_S


class UpstreamPool:
    """Connections kept open per upstream host.

    Through a corporate proxy, opening a connection (CONNECT + TLS handshake) costs ~500 ms: more than the
    request itself. The proxy is read from the environment (https_proxy / no_proxy), like urllib does.
    """

    def __init__(self, meter):
        self._idle = {}
        self._lock = threading.Lock()
        self._meter = meter

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
        """Returns (status, body, headers); a reused connection the upstream has closed in the meantime is
        replaced once. Only for idempotent requests: GET, and the rank PUT (ranking A before B twice leaves
        A before B). `origin` classifies the request in the counter (page, images, sync…)."""
        target = urlsplit(url)
        path = target.path + ("?" + target.query if target.query else "")
        connection, reused = self._acquire(target)
        try:
            return self._send(
                target,
                connection,
                method,
                path,
                headers,
                origin,
                body
            )
        except (ConnectionError, http.client.HTTPException, ssl.SSLError):
            if not reused:
                raise
            return self._send(
                target,
                self._connect(target),
                method,
                path,
                headers,
                origin,
                body
            )

    def _send(
            self,
            target,
            connection,
            method,
            path,
            headers,
            origin,
            body
    ):
        # Counted before sending: a failing request has still reached Jira (or the proxy).
        self._meter.record(origin)
        try:
            connection.request(
                method,
                path,
                body=body,
                headers=headers
            )
            response = connection.getresponse()
            body = response.read()
        except BaseException:
            connection.close()
            raise
        if response.will_close:
            connection.close()
        else:
            self._release(
                target,
                connection
            )
        return response.status, body, response.headers

    def _acquire(self, target):
        now = time.monotonic()
        with self._lock:
            idle = self._idle.get(target.netloc, [])
            while idle:
                connection, released_at = idle.pop()
                if now - released_at < UPSTREAM_IDLE_S:
                    return connection, True
                connection.close()
        return self._connect(target), False

    def _release(
            self,
            target,
            connection
    ):
        with self._lock:
            idle = self._idle.setdefault(target.netloc, [])
            if len(idle) < UPSTREAM_MAX_IDLE_PER_HOST:
                idle.append((connection, time.monotonic()))
                return
        connection.close()

    @staticmethod
    def _connect(target):
        secure = target.scheme == "https"
        connection_class = http.client.HTTPSConnection if secure else http.client.HTTPConnection
        port = target.port or (443 if secure else 80)
        proxy = urllib.request.getproxies().get(target.scheme)
        if not proxy or urllib.request.proxy_bypass(target.hostname):
            return connection_class(
                target.hostname,
                port,
                timeout=UPSTREAM_TIMEOUT_S
            )
        proxy = urlsplit(proxy if "://" in proxy else "http://" + proxy)
        tunnel_headers = {}
        if proxy.username:
            credentials = f"{unquote(proxy.username)}:{unquote(proxy.password or '')}"
            tunnel_headers["Proxy-Authorization"] = "Basic " + base64.b64encode(credentials.encode()).decode()
        connection = connection_class(
            proxy.hostname,
            proxy.port or 80,
            timeout=UPSTREAM_TIMEOUT_S
        )
        connection.set_tunnel(
            target.hostname,
            port,
            headers=tunnel_headers
        )
        return connection
