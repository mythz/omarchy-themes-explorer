"""The server's request boundary: rebound hosts, foreign origins, and the token.

Runs the real server.py on a free port with HOME and OMARCHY_PATH pointed at an
empty directory, so the requests that are let through find no themes and change
nothing.

    python3 -m unittest discover tests
"""

import http.client
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WRITES = ("/api/hide", "/api/apply", "/api/install")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerBoundaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.TemporaryDirectory()
        cls.port = free_port()
        env = dict(os.environ, HOME=cls.home.name, OMARCHY_PATH=cls.home.name)
        env.pop("XDG_CACHE_HOME", None)
        cls.proc = subprocess.Popen(
            [sys.executable, str(REPO / "app/server.py"), str(cls.port)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 10
        while True:
            try:
                status, body = cls.request("GET", "/")
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.05)
        match = re.search(rb'<meta name="explorer-token" content="([^"]+)">', body)
        assert status == 200 and match, "index.html carries no token"
        cls.token = match.group(1).decode()

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=5)
        cls.home.cleanup()

    @classmethod
    def request(cls, method, path, host=None, headers=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=10)
        sent = {"Host": host or "127.0.0.1:%d" % cls.port}
        sent.update(headers or {})
        try:
            conn.request(method, path, body=body, headers=sent)
            res = conn.getresponse()
            return res.status, res.read()
        finally:
            conn.close()

    def app_headers(self, host):
        """What the app's own fetch sends from a page served under `host`."""
        return {
            "Origin": "http://" + host,
            "Sec-Fetch-Site": "same-origin",
            "Content-Type": "application/json",
            "X-Themes-Explorer-Token": self.token,
        }

    def test_token_is_unguessable(self):
        self.assertGreaterEqual(len(self.token), 32)

    def test_rebound_host_cannot_read(self):
        evil = "evil.example:%d" % self.port
        for path in ("/", "/app.js", "/api/themes"):
            status, body = self.request("GET", path, host=evil)
            self.assertEqual(status, 403, path)
            self.assertNotIn(self.token.encode(), body, path)

    def test_missing_host_is_refused(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.putrequest("GET", "/", skip_host=True)
            conn.endheaders()
            self.assertEqual(conn.getresponse().status, 403)
        finally:
            conn.close()

    def test_rebound_host_cannot_write_even_with_token(self):
        # The browser sees evil.example as same-origin with itself once its DNS
        # points at loopback, so everything but Host looks like the app.
        evil = "evil.example:%d" % self.port
        for path in WRITES:
            status, _ = self.request("POST", path, host=evil, headers=self.app_headers(evil), body=b'{"theme":"x"}')
            self.assertEqual(status, 403, path)

    def test_writes_require_the_token(self):
        host = "127.0.0.1:%d" % self.port
        for token in (None, "", "wrong", self.token[:-1]):
            headers = self.app_headers(host)
            if token is None:
                del headers["X-Themes-Explorer-Token"]
            else:
                headers["X-Themes-Explorer-Token"] = token
            for path in WRITES:
                status, _ = self.request("POST", path, headers=headers, body=b'{"theme":"x"}')
                self.assertEqual(status, 403, (path, token))

    def test_foreign_origin_is_refused(self):
        host = "127.0.0.1:%d" % self.port
        for origin in ("http://evil.example", "http://127.0.0.1:1", "null"):
            headers = dict(self.app_headers(host), Origin=origin)
            for path in WRITES:
                status, _ = self.request("POST", path, headers=headers, body=b'{"theme":"x"}')
                self.assertEqual(status, 403, (path, origin))

    def test_cross_site_fetch_is_refused(self):
        host = "127.0.0.1:%d" % self.port
        headers = dict(self.app_headers(host), **{"Sec-Fetch-Site": "cross-site"})
        for path in WRITES:
            status, _ = self.request("POST", path, headers=headers, body=b'{"theme":"x"}')
            self.assertEqual(status, 403, path)

    def test_the_app_itself_gets_through(self):
        # Past the boundary the handlers answer 404: no such theme here. /api/hide
        # is left out because getting through would run the launcher.
        for name in ("127.0.0.1", "localhost", "omarchy-themes-explorer.localhost"):
            host = "%s:%d" % (name, self.port)
            headers = self.app_headers(host)
            status, _ = self.request("GET", "/api/themes", host=host)
            self.assertEqual(status, 200, host)
            for path in ("/api/apply", "/api/install"):
                status, _ = self.request("POST", path, host=host, headers=headers, body=b'{"theme":"not-a-theme"}')
                self.assertEqual(status, 404, (host, path))


if __name__ == "__main__":
    unittest.main()
