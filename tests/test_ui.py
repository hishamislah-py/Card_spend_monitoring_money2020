import json
import os
import re
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import ai  # noqa: E402
import engine  # noqa: E402
import server  # noqa: E402

UI_FILE = os.path.join(ROOT, "ui", "index.html")
SIMULATOR_FILE = os.path.join(ROOT, "ui", "simulator.html")
LIVE_PATHS = ["/api/live/tasks", "/api/live/actions", "/api/live/payments", "/api/live/state", "/api/live/reset",
              "/api/live/events"]

# Every API path the UI calls; per-case paths are built as /api/cases/{id}/analyst, /review, /checklist, /notes,
# /ai, /ai/retry and /ai/ask.
API_PATHS = ["/api/scenarios", "/api/replay/stream", "/api/feed", "/api/cases", "/analyst", "/review",
             "/checklist", "/notes", "/ai", "/ai/retry", "/ai/ask", "/ai/suggest-review", "/api/overview", "/api/alerts"]


class TestUi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        def offline_client(url, headers, body, timeout):  # never reaches Groq
            raise OSError("AI disabled in UI tests")

        cls.cache_dir = tempfile.mkdtemp(prefix="ag101-ai-cache-")
        cls.server = server.make_server(port=0, quiet=True, ai_service=ai.AIService(
            client=offline_client, model="test-model", cache_dir=cls.cache_dir))
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        with open(UI_FILE, encoding="utf-8") as f:
            cls.html = f.read()
        with open(SIMULATOR_FILE, encoding="utf-8") as f:
            cls.simulator = f.read()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        engine.reset()
        shutil.rmtree(cls.cache_dir, ignore_errors=True)

    def test_root_serves_html(self):
        with urllib.request.urlopen(self.base + "/", timeout=10) as resp:
            self.assertEqual(resp.status, 200)
            self.assertTrue(resp.headers["Content-Type"].startswith("text/html"))
            self.assertEqual(resp.read().decode("utf-8"), self.html)

    def test_self_contained(self):
        for page in (self.html, self.simulator):
            for needle in ("http://", "https://"):
                self.assertNotIn(needle, page)
            # Only the local theme files under /styles/ may be loaded; nothing remote or from elsewhere.
            self.assertIsNone(re.search(r"<(script|link|img)[^>]+(src|href)=(?![\"']/styles/)", page))

    def test_simulator_page(self):
        with urllib.request.urlopen(self.base + "/simulator", timeout=10) as resp:
            self.assertEqual(resp.status, 200)
            self.assertTrue(resp.headers["Content-Type"].startswith("text/html"))
            self.assertEqual(resp.read().decode("utf-8"), self.simulator)
        for path in LIVE_PATHS:
            self.assertIn(path, self.simulator)
        for text in ("Agent Simulator · AG-101", "Open dashboard ↗", "Reset live session", "Pay 5 times fast",
                     "Read a tricky webpage, then pay", "Pay unknown supplier"):
            self.assertIn(text, self.simulator)
        lowered = self.simulator.lower()
        for word in ("fraud", "malicious", "compromised", "attack"):
            self.assertNotIn(word, lowered)

    def test_dashboard_live_mode(self):
        self.assertNotIn("view-toggle", self.html)  # one combined dashboard: replay and live together
        for text in ("Live · connected", "Reconnecting…", "/api/live/events", "min ago", "day", "just now",
                     "/api/live/state", "alert_opened", "alert_updated", "ai_ready", "New alert · "):
            self.assertIn(text, self.html)

    def test_references_every_api_path(self):
        for path in API_PATHS:
            self.assertIn(path, self.html)

    def test_payments_and_alerts_table(self):
        match = re.search(r"const ACTIVITY_COLUMNS = (\[[^\]]*\]);", self.html)
        self.assertIsNotNone(match, "table column list not found")
        self.assertEqual(json.loads(match.group(1)),
                         ["Txn", "Merchant", "Amount", "Reference", "Task", "Card controls", "Agent monitoring", "Alert",
                          "Status", "Time"])
        self.assertNotIn('"Scenario"', match.group(1))
        self.assertIn("ACTIVITY_COLUMNS.map(", self.html)
        for gone in ("Overview · ", "Payment feed", '"Cases"'):  # one table replaces them
            self.assertNotIn(gone, self.html)

    def test_case_tabs_and_ai_labels(self):
        self.assertNotIn("· Groq ·", self.html)  # no provider or model names on screen
        for text in ('"Overview"', '"Analyst"', "/analyst", "AI-generated", "AI recommendation", "AI-filled",
                     "nothing is saved until you press Save decision",
                     "AI text explains the case; it does not affect classification.",
                     "Updates the review record only. Card payments are not affected."):
            with self.subTest(text=text):
                self.assertIn(text, self.html)

    def test_layers_never_merged_and_wording(self):
        self.assertIn("Card controls", self.html)
        self.assertIn("Agent monitoring", self.html)
        lowered = self.html.lower()
        for word in ("fraud", "malicious", "compromised", "attack"):
            self.assertNotIn(word, lowered)


if __name__ == "__main__":
    unittest.main()
