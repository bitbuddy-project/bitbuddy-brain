from __future__ import annotations

import http.client
import os
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-static-test-")

from bitbuddy import http_api  # noqa: E402


def _make_build_dir(root: Path) -> Path:
    build = root / "build"
    (build / "_app").mkdir(parents=True)
    (build / "index.html").write_text("<html><head><title>BitBuddy</title></head><body>BitBuddy SPA</body></html>", encoding="utf-8")
    (build / "_app" / "app.js").write_text("console.log('app');", encoding="utf-8")
    (root / "secret.txt").write_text("top secret", encoding="utf-8")
    return build


class ResolveWebAssetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.build = _make_build_dir(Path(self.tmp.name))
        self.patcher = patch.object(http_api, "WEB_BUILD_DIR", self.build)
        self.patcher.start()
        self.handler = http_api.BitBuddyRequestHandler.__new__(http_api.BitBuddyRequestHandler)

    def tearDown(self) -> None:
        self.patcher.stop()
        self.tmp.cleanup()

    def _resolve(self, path: str):
        return http_api.BitBuddyRequestHandler._resolve_web_asset(self.handler, path)

    def test_root_maps_to_index(self) -> None:
        self.assertEqual(self._resolve("/"), (self.build / "index.html").resolve())

    def test_asset_is_resolved(self) -> None:
        self.assertEqual(self._resolve("/_app/app.js"), (self.build / "_app" / "app.js").resolve())

    def test_missing_file_returns_none(self) -> None:
        self.assertIsNone(self._resolve("/does-not-exist.js"))

    def test_traversal_is_rejected(self) -> None:
        self.assertIsNone(self._resolve("/../secret.txt"))
        self.assertIsNone(self._resolve("/_app/../../secret.txt"))

    def test_navigation_detection(self) -> None:
        self.handler.headers = {"Accept": "text/html,application/xhtml+xml"}
        self.assertTrue(http_api.BitBuddyRequestHandler._is_navigation_request(self.handler))
        self.handler.headers = {"Accept": "*/*"}
        self.assertFalse(http_api.BitBuddyRequestHandler._is_navigation_request(self.handler))
        self.handler.headers = {"Accept": "*/*", "Sec-Fetch-Mode": "navigate"}
        self.assertTrue(http_api.BitBuddyRequestHandler._is_navigation_request(self.handler))

    def test_maybe_serve_web_false_without_build(self) -> None:
        with patch.object(http_api, "WEB_BUILD_DIR", Path(self.tmp.name) / "nope"):
            self.assertFalse(http_api.BitBuddyRequestHandler._maybe_serve_web(self.handler, "/"))

    def test_public_paths_skip_spa_fallback(self) -> None:
        # OAuth callbacks arrive as browser navigations but must reach their API
        # handlers, not be swallowed by the SPA fallback (which renders a 404).
        self.handler.headers = {"Accept": "text/html", "Sec-Fetch-Mode": "navigate"}
        for path in http_api.PUBLIC_PATHS:
            self.assertFalse(
                http_api.BitBuddyRequestHandler._maybe_serve_web(self.handler, path),
                msg=f"{path} should not be served the SPA",
            )


class InjectBootstrapTest(unittest.TestCase):
    def test_globals_injected_in_head(self) -> None:
        out = http_api._inject_bootstrap("<head><title>x</title></head>", "secret-token", "http://127.0.0.1:8787")
        self.assertIn('window.__BITBUDDY_TOKEN__="secret-token"', out)
        self.assertIn('window.__BITBUDDY_API__="http://127.0.0.1:8787"', out)
        self.assertLess(out.index("__BITBUDDY_TOKEN__"), out.index("</head>"))

    def test_script_break_out_is_escaped(self) -> None:
        out = http_api._inject_bootstrap("<head></head>", "abc</script><script>evil()", "http://x")
        self.assertNotIn("</script><script>evil()", out)
        self.assertIn("<\\/script>", out)

    def test_falls_back_without_head(self) -> None:
        out = http_api._inject_bootstrap("<html>no head</html>", "tok", "http://x")
        self.assertTrue(out.startswith("<script>"))


class StaticServingIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.build = _make_build_dir(Path(self.tmp.name))
        self.patcher = patch.object(http_api, "WEB_BUILD_DIR", self.build)
        self.patcher.start()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), http_api.BitBuddyRequestHandler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.patcher.stop()
        self.tmp.cleanup()

    def _get(self, path: str, headers: dict[str, str]):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path, headers=headers)
        response = conn.getresponse()
        body = response.read()
        conn.close()
        return response, body

    def test_navigation_serves_spa(self) -> None:
        response, body = self._get("/", {"Accept": "text/html"})
        self.assertEqual(response.status, 200)
        self.assertIn("text/html", response.getheader("Content-Type", ""))
        self.assertIn(b"BitBuddy SPA", body)

    def test_asset_is_served(self) -> None:
        response, body = self._get("/_app/app.js", {"Accept": "*/*"})
        self.assertEqual(response.status, 200)
        self.assertIn(b"console.log", body)

    def test_index_injects_token_for_loopback(self) -> None:
        response, body = self._get("/", {"Accept": "text/html"})
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Cache-Control"), "no-store")
        token = http_api.get_api_token()
        self.assertIn(f'window.__BITBUDDY_TOKEN__="{token}"'.encode(), body)
        self.assertIn(b"window.__BITBUDDY_API__=", body)

    def test_client_route_falls_back_to_spa(self) -> None:
        # /projects is also an API route; a browser navigation gets the SPA.
        response, body = self._get("/projects", {"Accept": "text/html"})
        self.assertEqual(response.status, 200)
        self.assertIn(b"BitBuddy SPA", body)

    def test_api_fetch_still_token_gated(self) -> None:
        # A data fetch (no text/html, no token) must hit the gated API, not the SPA.
        response, _ = self._get("/projects", {"Accept": "application/json"})
        self.assertEqual(response.status, 401)

    def test_oauth_callback_navigation_reaches_handler(self) -> None:
        # Google redirects the browser to the callback (a navigation). It must
        # reach the gmail callback handler, not get the SPA's 404. With no code
        # the handler reports an authorization failure rather than the SPA page.
        response, body = self._get(
            "/email/gmail/callback",
            {"Accept": "text/html", "Sec-Fetch-Mode": "navigate"},
        )
        self.assertNotIn(b"BitBuddy SPA", body)


if __name__ == "__main__":
    unittest.main()
