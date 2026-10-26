from __future__ import annotations

import http.client
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from android_agent import android_runtime


class RuntimeLifecycleTests(unittest.TestCase):
    def test_start_stop_restart_rotates_token_and_releases_port(self):
        with tempfile.TemporaryDirectory() as temporary:
            try:
                first = android_runtime.start(temporary, 0)
                self.assertEqual(first, android_runtime.launch_url())
                self.assertEqual(first, android_runtime.start(temporary, 0))
                parsed = urlsplit(first)
                conn = http.client.HTTPConnection(parsed.hostname,parsed.port,timeout=2)
                conn.request("GET","/api/health/live")
                response=conn.getresponse()
                self.assertEqual(response.status,200)
                self.assertEqual(response.read(),b'{"status":"alive"}')
                conn.close()
                android_runtime.stop()
                android_runtime.stop()
                with self.assertRaises(RuntimeError):
                    android_runtime.launch_url()
                second=android_runtime.start(temporary,parsed.port)
                self.assertNotEqual(urlsplit(first).fragment,urlsplit(second).fragment)
            finally:
                android_runtime.stop()

    def test_missing_or_empty_frontend_resources_fail_before_serving(self):
        for missing in ("index.html", "static/app.css", "static/app.js", "static/markdown.js"):
            with self.subTest(resource=missing), tempfile.TemporaryDirectory() as temporary:
                web = Path(temporary) / "web"
                for name in ("index.html", "static/app.css", "static/app.js", "static/markdown.js"):
                    target = web / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if name != missing:
                        target.write_text("nonempty fixture", encoding="utf-8")
                try:
                    with patch("android_agent.server.WEB_ROOT", web):
                        with self.assertRaisesRegex(RuntimeError, missing.replace(".", r".")):
                            android_runtime.start(temporary, 0)
                        with self.assertRaises(RuntimeError):
                            android_runtime.launch_url()
                        (web / missing).write_text("", encoding="utf-8")
                        with self.assertRaises(RuntimeError):
                            android_runtime.start(temporary, 0)
                    healthy = android_runtime.start(temporary, 0)
                    self.assertIn("/#token=", healthy)
                finally:
                    android_runtime.stop()


if __name__ == "__main__":
    unittest.main()
