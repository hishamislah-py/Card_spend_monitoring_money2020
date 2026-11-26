import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import ai  # noqa: E402
import engine  # noqa: E402
import server  # noqa: E402


def file_hash(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class ApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        def offline_client(url, headers, body, timeout):  # these tests never reach Groq
            raise OSError("AI disabled in API tests")

        cls.cache_dir = tempfile.mkdtemp(prefix="ag101-ai-cache-")
        cls.server = server.make_server(port=0, quiet=True, ai_service=ai.AIService(
            client=offline_client, model="test-model", cache_dir=cls.cache_dir))
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        engine.reset()
        shutil.rmtree(cls.cache_dir, ignore_errors=True)

    def setUp(self):
        self.request("POST", "/api/reset")

    # ---- helpers

    def request(self, method, path, body=None, expect=200):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                status, payload = resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            status, payload = e.code, json.loads(e.read().decode("utf-8"))
        self.assertEqual(status, expect, payload)
        self.assertIs(payload.get("simulation"), True)
        return payload

    def get(self, path, expect=200):
        return self.request("GET", path, expect=expect)

    @staticmethod
    def iter_sse(resp):
        event, data = None, []
        for raw in resp:
            line = raw.decode("utf-8").rstrip("\r\n")
            if line.startswith("event: "):
                event = line[len("event: "):]
            elif line.startswith("data: "):
                data.append(line[len("data: "):])
            elif not line and event:
                yield event, json.loads("\n".join(data))
                event, data = None, []

    def stream(self, scenario, mode="controls_plus_monitoring", delay_ms=0):
        url = f"{self.base}/api/replay/stream?scenario={scenario}&mode={mode}&delay_ms={delay_ms}"
        with urllib.request.urlopen(url, timeout=30) as resp:
            self.assertTrue(resp.headers["Content-Type"].startswith("text/event-stream"))
            events = list(self.iter_sse(resp))
        for _, payload in events:
            self.assertIs(payload["simulation"], True)
        return events


class TestApi(ApiTestCase):
    def test_scenarios(self):
        scenarios = self.get("/api/scenarios")["scenarios"]
        self.assertEqual([s["scenario_id"] for s in scenarios], engine.SCENARIO_IDS)
        self.assertEqual(set(scenarios[0]), {"scenario_id", "name", "description"})

    def test_stream_s2(self):
        events = self.stream("S2")
        self.assertEqual([e for e, _ in events], ["transaction"] * 8 + ["done"])
        txns = {p["txn_id"]: p for e, p in events if e == "transaction"}
        self.assertEqual(txns["TX-2001"]["agent_monitoring"]["classification"], "NORMAL")
        for n in range(2, 9):
            self.assertEqual(txns[f"TX-200{n}"]["agent_monitoring"]["classification"], "HIGH")
        self.assertTrue(all(p["card_controls"]["decision"] == "APPROVED" for p in txns.values()))
        done = events[-1][1]
        self.assertEqual(done["case_ids"], ["CASE-S2-01"])
        self.assertEqual(done["txn_count"], 8)
        streamed = [{k: v for k, v in p.items() if k != "simulation"} for e, p in events if e == "transaction"]
        self.assertEqual(self.get("/api/feed")["transactions"], streamed)

    def test_stream_delay_does_not_change_results(self):
        self.assertEqual(self.stream("S2", delay_ms=0), self.stream("S2", delay_ms=50))

    def test_stream_rejects_bad_params(self):
        self.get("/api/replay/stream?scenario=S99", expect=400)
        self.get("/api/replay/stream?scenario=S1&mode=other", expect=400)
        self.get("/api/replay/stream?scenario=S1&delay_ms=5000", expect=400)

    def test_case_detail_s2(self):
        self.stream("S2")
        detail = self.get("/api/cases/CASE-S2-01")
        activity = detail["actual_activity"]
        self.assertEqual(len(activity), 8)
        self.assertEqual(sum(engine.to_pence(a["amount"]) for a in activity), 32000)
        self.assertEqual(detail["case"]["total_amount"], "320.00")
        self.assertIn("permitted_payment_count", detail["mismatched_fields"])
        self.assertIn("Owner task instruction", [e["evidence_label"] for e in detail["evidence"]])
        self.assertEqual(detail["authorised_task"]["task_id"], "T-101")
        self.assertIs(detail["authorised_task"]["verified_source"], True)
        self.assertEqual([s["code"] for s in detail["signals"]],
                         ["COUNT_EXCEEDED", "DUPLICATE_REFERENCE", "BURST_VS_HISTORY"])
        stamps = [e["timestamp"] for e in detail["evidence"]]
        self.assertEqual(stamps, sorted(stamps))

    def test_case_detail_s3(self):
        self.stream("S3")
        case_id = self.get("/api/cases")["cases"][0]["case_id"]
        detail = self.get(f"/api/cases/{case_id}")
        web_reads = [e for e in detail["evidence"] if e["action_type"] == "web_read"]
        self.assertEqual(len(web_reads), 1)
        self.assertEqual(web_reads[0]["source_type"], "external")
        self.assertEqual(web_reads[0]["evidence_label"], engine.LABEL_SUPPORTING)
        self.assertIn("approved_merchant", detail["mismatched_fields"])

    def test_case_detail_s5(self):
        self.stream("S5")
        cases = self.get("/api/cases")["cases"]
        self.assertEqual(len(cases), 1)
        detail = self.get(f"/api/cases/{cases[0]['case_id']}")
        self.assertIsNone(detail["authorised_task"])
        self.assertEqual(detail["case"]["case_type"], "MISSING_EVIDENCE")
        self.assertEqual(detail["mismatched_fields"], [])
        self.assertEqual([a["txn_id"] for a in detail["actual_activity"]], ["TX-5001"])

    def test_no_cases_for_s1_and_s4(self):
        for scenario in ("S1", "S4"):
            with self.subTest(scenario=scenario):
                self.stream(scenario)
                self.assertEqual(self.get("/api/cases")["cases"], [])

    def test_case_status(self):
        self.stream("S2")
        updated = self.request("POST", "/api/cases/CASE-S2-01/status", {"status": "REVIEWED"})
        self.assertEqual(updated["case"]["status"], "REVIEWED")
        self.assertEqual(self.get("/api/cases")["cases"][0]["status"], "REVIEWED")
        self.assertEqual(self.get("/api/overview")["agent_monitoring"]["open_cases"], 0)
        self.request("POST", "/api/cases/CASE-S2-01/status", {"status": "BLOCKED"}, expect=400)
        self.request("POST", "/api/cases/CASE-XX-99/status", {"status": "REVIEWED"}, expect=404)
        self.get("/api/cases/CASE-XX-99", expect=404)

    def test_second_stream_conflicts(self):
        url = f"{self.base}/api/replay/stream?scenario=S2&delay_ms=3000"
        resp = urllib.request.urlopen(url, timeout=30)
        try:
            first = next(self.iter_sse(resp))
            self.assertEqual(first[0], "transaction")
            self.get("/api/replay/stream?scenario=S1&delay_ms=0", expect=409)
            self.request("POST", "/api/cases/CASE-S2-01/status", {"status": "REVIEWED"}, expect=409)
            self.request("POST", "/api/reset")  # stops the running stream
            self.assertEqual(next(self.iter_sse(resp))[0], "stopped")
        finally:
            resp.close()
        self.assertEqual(self.get("/api/feed")["transactions"], [])
        self.assertEqual(len(self.stream("S1")), 2)  # lock released

    def test_reset_clears_feed_and_cases(self):
        self.stream("S2")
        self.assertTrue(self.get("/api/feed")["transactions"])
        self.assertEqual(self.request("POST", "/api/reset")["reset"], True)
        self.assertEqual(self.get("/api/feed")["transactions"], [])
        self.assertEqual(self.get("/api/cases")["cases"], [])

    def test_compare_s3_does_not_write(self):
        self.stream("S2")
        paths = [engine.output_path(n) for n in engine.OUTPUT_SCHEMAS]
        before = [file_hash(p) for p in paths]
        result = self.get("/api/compare?scenario=S3")
        self.assertEqual([file_hash(p) for p in paths], before)
        self.assertEqual(result["controls_only"], {"approved": 1, "declined": 0, "cases": 0})
        self.assertEqual(result["controls_plus_monitoring"]["cases"], 1)
        self.assertEqual(result["controls_plus_monitoring"]["high"], 1)
        self.assertEqual(result["per_transaction"],
                         [{"txn_id": "TX-3001", "card_decision": "APPROVED", "monitoring_classification": "HIGH"}])
        self.get("/api/compare?scenario=nope", expect=400)

    def test_overview(self):
        self.stream("S2")
        ov = self.get("/api/overview")
        self.assertEqual(ov["total_payments"], 8)
        self.assertEqual(ov["total_spend"], "320.00")
        self.assertEqual(ov["daily_cap"], "500.00")
        self.assertEqual(ov["spend_by_date"], {"2026-10-13": "320.00"})
        self.assertEqual(ov["card_controls"], {"approved": 8, "declined": 0})
        self.assertEqual(ov["agent_monitoring"], {"normal": 1, "high": 7, "review": 0, "open_cases": 1})
        self.assertEqual(ov["signal_counts"]["COUNT_EXCEEDED"], 7)
        self.assertEqual(len(ov["history_daily"]), 14)
        self.assertEqual(ov["history_daily"][0]["date"], "2026-09-28")
        self.assertEqual(ov["history_daily"][-1]["date"], "2026-10-11")

    def test_all_alerts_cover_every_scenario_without_writing(self):
        self.stream("S2")
        self.request("POST", "/api/cases/CASE-S2-01/status", {"status": "ESCALATED"})
        paths = [engine.output_path(n) for n in engine.OUTPUT_SCHEMAS]
        before = [file_hash(p) for p in paths]
        result = self.get("/api/alerts")
        alerts = result["alerts"]
        self.assertEqual([file_hash(p) for p in paths], before)
        payments = result["payments"]
        self.assertEqual(len(payments), 50)  # every scenario's payments
        self.assertEqual({p["agent_monitoring"]["case_id"] for p in payments if p["agent_monitoring"]["case_id"]},
                         {a["case_id"] for a in alerts})
        self.assertEqual(set(payments[0]), {"run_id", "scenario_id", "txn_id", "timestamp", "agent_id", "merchant", "amount",
                                            "task_id", "reference", "card_controls", "agent_monitoring"})
        self.assertEqual(len(alerts), 25)
        self.assertEqual({a["scenario_id"] for a in alerts}, set(engine.SCENARIO_IDS) - {"S1", "S4"})
        self.assertEqual(sum(a["severity"] == "HIGH" for a in alerts), 18)
        by_id = {a["case_id"]: a for a in alerts}
        self.assertEqual((by_id["CASE-S2-01"]["status"], by_id["CASE-S2-01"]["live"]), ("ESCALATED", True))
        self.assertEqual((by_id["CASE-S3-01"]["status"], by_id["CASE-S3-01"]["live"]), ("OPEN", False))
        self.assertEqual(by_id["CASE-S10-03"]["merchant"], "ToolCloud")

    def test_alert_refs_and_merchants(self):
        ref_re = re.compile(r"^ALT-\d{4}$")
        seen = {}
        for scenario in engine.SCENARIO_IDS:
            self.stream(scenario)
            cases = self.get("/api/cases")["cases"]
            for c in cases:
                with self.subTest(case=c["case_id"]):
                    self.assertRegex(c["alert_ref"], ref_re)
                    self.assertTrue(c["merchant"])
                    self.assertEqual(c["agent_id"], "AG-101")
                    detail = self.get(f"/api/cases/{c['case_id']}")["case"]
                    self.assertEqual((detail["alert_ref"], detail["merchant"]), (c["alert_ref"], c["merchant"]))
                    seen[c["case_id"]] = c["alert_ref"]
        self.assertEqual(len(set(seen.values())), len(seen), "alert_ref must be unique per case")
        self.assertEqual(seen["CASE-S2-01"], "ALT-1001")
        latest = {c["case_id"]: c["merchant"] for c in self.get("/api/cases")["cases"]}  # S16 is the latest run
        self.assertEqual(latest, {"CASE-S16-01": "MetricsLane", "CASE-S16-02": "DocuForge", "CASE-S16-03": "SeatPilot",
                                  "CASE-S16-04": "ToolCloud"})

        alerts = self.get("/api/alerts")["alerts"]
        self.assertEqual({a["case_id"]: a["alert_ref"] for a in alerts}, seen)
        self.assertEqual({a["case_id"]: a["merchant"] for a in alerts}["CASE-S3-01"], "MetricsLane")

    def test_alert_refs_identical_across_runs(self):
        def refs():
            self.stream("S10")
            return {c["case_id"]: c["alert_ref"] for c in self.get("/api/cases")["cases"]},                    {a["case_id"]: a["alert_ref"] for a in self.get("/api/alerts")["alerts"]}
        first = refs()
        self.request("POST", "/api/reset")
        self.stream("S3")  # a different latest run must not renumber anything
        self.assertEqual({a["case_id"]: a["alert_ref"] for a in self.get("/api/alerts")["alerts"]}, first[1])
        self.assertEqual(refs(), first)

    def test_layers_separate_and_card_decisions_identical_across_modes(self):
        for scenario in engine.SCENARIO_IDS:
            with self.subTest(scenario=scenario):
                controls = [p for e, p in self.stream(scenario, "controls_only") if e == "transaction"]
                monitored = [p for e, p in self.stream(scenario) if e == "transaction"]
                self.assertTrue(all(p["agent_monitoring"] is None for p in controls))
                self.assertTrue(all(p["agent_monitoring"] is not None for p in monitored))
                self.assertEqual([p["card_controls"] for p in controls], [p["card_controls"] for p in monitored])
                for p in monitored:
                    self.assertNotIn("decision", p["agent_monitoring"])
                    self.assertEqual(set(p["card_controls"]), {"decision", "rule_triggered"})

    def test_unknown_routes_and_static_guard(self):
        self.get("/api/nope", expect=404)
        self.get("/../tests/expected_results.csv", expect=404)
        self.get("/%2e%2e/tests/expected_results.csv", expect=404)


if __name__ == "__main__":
    unittest.main()
