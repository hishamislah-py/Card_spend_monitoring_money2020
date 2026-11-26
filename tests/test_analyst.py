import csv
import os
import sys
import unittest
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import engine  # noqa: E402
from test_api import ApiTestCase, file_hash  # noqa: E402

CASE = "/api/cases/CASE-S2-01"


def rows(name):
    with open(engine.output_path(name), encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def kinds(view):
    return [a["kind"] for a in view["activity"]]


class TestReview(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.stream("S2")

    def review(self, body, expect=200):
        return self.request("POST", f"{CASE}/review", body, expect=expect)

    def test_analyst_view_defaults(self):
        view = self.get(f"{CASE}/analyst")
        self.assertEqual(view["review"]["status"], "OPEN")
        self.assertEqual(view["review"]["disposition"], "")
        self.assertEqual(view["notes"], [])
        self.assertEqual(kinds(view), ["case_opened"])
        self.assertEqual(view["activity"][0]["at"], "2026-10-13T10:00:20Z")
        self.assertEqual(len(view["suggested_questions"]), 3)
        self.assertEqual(set(view["dispositions"]), set(engine.DISPOSITIONS))
        self.get("/api/cases/CASE-XX-99/analyst", expect=404)

    def test_disposition_required(self):
        for status in ("REVIEWED", "ESCALATED", "DISMISSED"):
            with self.subTest(status=status):
                error = self.review({"status": status, "note": "Checked with the owner today."}, expect=400)["error"]
                self.assertIn("disposition is required", error)
        self.assertIn("Invalid disposition", self.review({"status": "REVIEWED", "disposition": "NOPE"}, expect=400)["error"])

    def test_note_required_for_escalate_and_dismiss(self):
        for status in ("ESCALATED", "DISMISSED"):
            with self.subTest(status=status):
                body = {"status": status, "disposition": "CONFIRMED_ISSUE"}
                self.assertIn("note of at least 10", self.review(body, expect=400)["error"])
                self.assertIn("10–1000", self.review(dict(body, note="too short"), expect=400)["error"])
        view = self.review({"status": "ESCALATED", "disposition": "CONFIRMED_ISSUE", "note": "Owner confirms one payment only."})
        self.assertEqual(view["review"]["status"], "ESCALATED")
        self.assertEqual(view["case"]["status"], "ESCALATED")
        self.assertEqual(view["notes"][0]["text"], "Owner confirms one payment only.")

    def test_ai_suggested_decision_is_recorded_as_confirmed(self):
        note = "The payment reference differs from the task reference."
        view = self.review({"status": "ESCALATED", "disposition": "NEEDS_OWNER_CONFIRMATION", "note": note,
                            "ai_suggested": True, "note_source": "ai_suggestion"})
        self.assertEqual((view["notes"][0]["text"], view["notes"][0]["source"]), (note, "ai_suggestion"))
        self.assertEqual(view["activity"][0]["detail"],
                         "OPEN → ESCALATED · Needs owner confirmation · AI-suggested, confirmed by analyst")
        self.assertEqual(view["activity"][1]["detail"], f"From AI suggestion: {note}")
        self.review({"status": "IN_REVIEW", "note": "Checking.", "note_source": "robot"}, expect=400)

    def test_in_review_and_reviewed(self):
        view = self.review({"status": "IN_REVIEW"})
        self.assertEqual((view["review"]["status"], view["review"]["disposition"]), ("IN_REVIEW", ""))
        self.assertEqual(self.get("/api/cases")["cases"][0]["status"], "IN_REVIEW")
        view = self.review({"status": "REVIEWED", "disposition": "EXPECTED_BEHAVIOUR"})
        self.assertEqual((view["review"]["status"], view["review"]["disposition"]), ("REVIEWED", "EXPECTED_BEHAVIOUR"))
        self.assertEqual(rows("case_review"), [{"case_id": "CASE-S2-01", "status": "REVIEWED",
                                                "disposition": "EXPECTED_BEHAVIOUR",
                                                "updated_at": view["review"]["updated_at"]}])
        self.assertEqual(self.review({"status": "BLOCKED"}, expect=400)["error"][:14], "Invalid status")
        self.request("POST", "/api/cases/CASE-XX-99/review", {"status": "IN_REVIEW"}, expect=404)


class TestChecklistNotesActivity(ApiTestCase):
    def test_checklist_matches_signal_mapping(self):
        expected = {
            "S2": ["duplicate-payments", "owner-intended-count", "consider-pause", "compare-history"],
            "S3": ["confirm-supplier", "review-external-content"],
            "S5": ["owner-intended-payment", "task-recorded"],
            "S6": ["confirm-price", "task-limit"],
            "S7": ["outside-window"],
            "S8": ["confirm-reference", "authorised-invoice"],
            "S9": ["owner-intended-payment", "task-recorded"],
        }
        for scenario, item_ids in expected.items():
            with self.subTest(scenario=scenario):
                self.stream(scenario)
                view = self.get(f"/api/cases/CASE-{scenario}-01/analyst")
                self.assertEqual([i["item_id"] for i in view["checklist"]], item_ids)
                self.assertTrue(all(i["text"] == engine.CHECKLIST_TEXT[i["item_id"]] and not i["checked"]
                                    for i in view["checklist"]))
                if scenario == "S8":
                    self.assertEqual(view["suggested_questions"],
                                     ["What exactly doesn’t match?", "Was the payment otherwise within the task?",
                                      "What should I check first?"])

    def test_checklist_persists(self):
        self.stream("S2")
        self.request("POST", f"{CASE}/checklist", {"item_id": "consider-pause", "checked": True})
        self.request("POST", f"{CASE}/checklist", {"item_id": "compare-history", "checked": True})
        self.request("POST", f"{CASE}/checklist", {"item_id": "compare-history", "checked": False})
        view = self.get(f"{CASE}/analyst")
        self.assertEqual({i["item_id"]: i["checked"] for i in view["checklist"]},
                         {"duplicate-payments": False, "owner-intended-count": False, "consider-pause": True,
                          "compare-history": False})
        self.assertEqual(len(rows("case_checklist")), 2)
        self.request("POST", f"{CASE}/checklist", {"item_id": "confirm-price", "checked": True}, expect=400)
        self.request("POST", f"{CASE}/checklist", {"item_id": "consider-pause", "checked": "yes"}, expect=400)

    def test_note_limits_and_order(self):
        self.stream("S2")
        self.request("POST", f"{CASE}/notes", {"text": "   "}, expect=400)
        self.request("POST", f"{CASE}/notes", {"text": "x" * 1001}, expect=400)
        self.request("POST", f"{CASE}/notes", {"text": "x", "source": "robot"}, expect=400)
        self.request("POST", f"{CASE}/notes", {"text": "x"})
        view = self.request("POST", f"{CASE}/notes", {"text": "y" * 1000, "source": "ai_answer"})
        self.assertEqual([(n["text"][:1], n["source"], n["author"]) for n in view["notes"]],
                         [("y", "ai_answer", "Analyst (demo)"), ("x", "analyst", "Analyst (demo)")])

    def test_activity_logged_for_every_action(self):
        self.stream("S2")
        self.request("POST", f"{CASE}/review", {"status": "IN_REVIEW"})
        self.request("POST", f"{CASE}/checklist", {"item_id": "consider-pause", "checked": True})
        self.request("POST", f"{CASE}/notes", {"text": "Called the supplier."})
        self.request("POST", f"{CASE}/ai/ask", {"question": "What should I check first?"})
        self.request("POST", f"{CASE}/status", {"status": "OPEN"})
        view = self.get(f"{CASE}/analyst")
        self.assertEqual(kinds(view), ["status_changed", "ai_question", "note_added", "checklist", "status_changed",
                                       "case_opened"])
        details = [a["detail"] for a in view["activity"]]
        self.assertEqual(details[0], "IN_REVIEW → OPEN")
        self.assertEqual(details[1], "What should I check first?")
        self.assertEqual(details[3], "Ticked: Consider pausing the agent via card controls")
        self.assertEqual(details[4], "OPEN → IN_REVIEW")
        self.assertTrue(all(a["at"].endswith("Z") for a in view["activity"]))

    def test_reset_clears_analyst_files(self):
        self.stream("S2")
        self.request("POST", f"{CASE}/review", {"status": "DISMISSED", "disposition": "EXPECTED_BEHAVIOUR",
                                               "note": "Duplicate retries were refunded."})
        self.request("POST", f"{CASE}/checklist", {"item_id": "consider-pause", "checked": True})
        self.assertTrue(all(rows(n) for n in engine.ANALYST_SCHEMAS))
        self.request("POST", "/api/reset")
        for name, header in engine.ANALYST_SCHEMAS.items():
            with self.subTest(file=name):
                with open(engine.output_path(name), encoding="utf-8", newline="") as f:
                    self.assertEqual(list(csv.reader(f)), [header])


class TestReplayIsolation(ApiTestCase):
    def test_analyst_endpoints_409_during_replay(self):
        self.stream("S2")
        resp = urllib.request.urlopen(f"{self.base}/api/replay/stream?scenario=S3&delay_ms=3000", timeout=30)
        try:
            self.assertEqual(next(self.iter_sse(resp))[0], "transaction")
            case = "/api/cases/CASE-S3-01"
            self.get(f"{case}/analyst", expect=409)
            self.request("POST", f"{case}/review", {"status": "IN_REVIEW"}, expect=409)
            self.request("POST", f"{case}/checklist", {"item_id": "confirm-supplier", "checked": True}, expect=409)
            self.request("POST", f"{case}/notes", {"text": "note"}, expect=409)
            self.request("POST", f"{case}/ai/ask", {"question": "Why?"}, expect=409)
            self.request("POST", f"{case}/ai/suggest-review", {}, expect=409)
            self.request("POST", "/api/reset")
        finally:
            resp.close()

    def test_replay_outputs_identical_regardless_of_analyst_activity(self):
        paths = [engine.output_path(n) for n in engine.OUTPUT_SCHEMAS]
        self.stream("S2")
        clean = [file_hash(p) for p in paths]
        self.request("POST", f"{CASE}/review", {"status": "ESCALATED", "disposition": "CONFIRMED_ISSUE",
                                               "note": "Supplier confirms eight charges."})
        self.request("POST", f"{CASE}/checklist", {"item_id": "duplicate-payments", "checked": True})
        self.request("POST", f"{CASE}/notes", {"text": "Asked the owner to confirm."})
        self.stream("S2")
        self.assertEqual([file_hash(p) for p in paths], clean)
        self.assertEqual(self.get(f"{CASE}/analyst")["notes"], [])  # a new replay starts a fresh review record


if __name__ == "__main__":
    unittest.main()
