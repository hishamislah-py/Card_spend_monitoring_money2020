import copy
import csv
import hashlib
import os
import sys
import unittest
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import engine  # noqa: E402

EXPECTED_PATH = os.path.join(ROOT, "tests", "expected_results.csv")
MON = "controls_plus_monitoring"
BANNED_WORDS = ("compromised", "malicious", "fraud", "blocked", "declined", "approved")


def load_expected():
    with open(EXPECTED_PATH, encoding="utf-8", newline="") as f:
        return {r["txn_id"]: r for r in csv.DictReader(f)}


def read_output(name):
    with open(engine.output_path(name), encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def file_hash(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def run_scenario(scenario_id, context=None):
    """Replay one scenario with monitoring; return events, cases and evidence left on disk."""
    events = list(engine.replay(scenario_id, MON, context))
    return events, read_output("cases"), read_output("case_evidence")


def fixture_txn(task_id, amount, timestamp, merchant="ToolCloud", reference="INV-42", txn_id="FX-1"):
    return {"txn_id": txn_id, "agent_id": "AG-101", "task_id": task_id, "merchant": merchant,
            "amount": amount, "timestamp": timestamp, "reference": reference}


def without_external_actions(context):
    return engine.MappingProxyType(dict(context, actions=tuple(
        a for a in context["actions"] if a["source_type"] != "external")))


class MonitoringTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = engine.load_context()

    def tearDown(self):
        engine.reset()


class TestScenarios(MonitoringTestCase):
    def test_replay_all_matches_expected(self):
        expected = load_expected()
        case_ids = defaultdict(set)
        for e in engine.replay_all(MON, self.context):
            with self.subTest(txn_id=e["txn_id"]):
                self.assertEqual(e["monitoring"]["classification"],
                                 expected[e["txn_id"]]["expected_classification"])
            if e["monitoring"]["case_id"]:
                case_ids[e["scenario_id"]].add(e["monitoring"]["case_id"])
        for txn_id, row in expected.items():
            with self.subTest(scenario=row["scenario_id"], txn_id=txn_id):
                self.assertEqual(len(case_ids[row["scenario_id"]]), int(row["expected_case_count"]))
        for scenario_id in engine.SCENARIO_IDS:
            _, cases, _ = run_scenario(scenario_id, self.context)
            expected_count = {int(r["expected_case_count"]) for r in expected.values()
                              if r["scenario_id"] == scenario_id}
            with self.subTest(scenario=scenario_id, source="cases.csv"):
                self.assertEqual({len(cases)}, expected_count)

    def test_s2_runaway_duplicates(self):
        events, cases, _ = run_scenario("S2", self.context)
        mon = {e["txn_id"]: e["monitoring"] for e in events}
        self.assertEqual(mon["TX-2001"], {"classification": "NORMAL", "signals": "", "case_id": ""})
        first_high = next(e["txn_id"] for e in events if e["monitoring"]["classification"] == "HIGH")
        self.assertEqual(first_high, "TX-2002")
        signals = mon["TX-2002"]["signals"].split(";")
        self.assertIn("COUNT_EXCEEDED", signals)
        self.assertIn("DUPLICATE_REFERENCE", signals)
        self.assertIn("BURST_VS_HISTORY", signals)
        self.assertEqual(len(cases), 1)
        case = cases[0]
        self.assertEqual(case["case_id"], "CASE-S2-01")
        self.assertEqual(case["txn_count"], "8")
        self.assertEqual(case["total_amount"], "320.00")
        self.assertEqual(case["case_type"], "RULE_MISMATCH")
        self.assertEqual(case["opened_at"], "2026-10-13T10:00:20Z")
        self.assertEqual(case["updated_at"], "2026-10-13T10:02:20Z")
        self.assertEqual(case["reason"], "8 payments made against task T-101, which authorises 1.")

        state = engine.MonitorState("RUN-S2", "S2")
        facts = [engine.apply_monitoring(t, self.context, state)["facts"]
                 for t in engine.load_authorisations("S2")]
        self.assertFalse(any(f["burst_suppressed"] for f in facts))

    def test_s3_payee_change(self):
        events, cases, evidence = run_scenario("S3", self.context)
        self.assertEqual(events[0]["monitoring"]["classification"], "HIGH")
        self.assertIn("MERCHANT_MISMATCH", events[0]["monitoring"]["signals"].split(";"))
        web_read = next(a for a in self.context["actions"]
                        if a["scenario_id"] == "S3" and a["action_type"] == "web_read")
        self.assertIn({"case_id": cases[0]["case_id"], "action_id": web_read["action_id"],
                       "evidence_label": engine.LABEL_SUPPORTING}, evidence)

        events, _, evidence = run_scenario("S3", without_external_actions(self.context))
        self.assertEqual(events[0]["monitoring"]["classification"], "HIGH")
        self.assertNotIn(web_read["action_id"], {r["action_id"] for r in evidence})

    def test_s4_fast_batch_is_normal(self):
        events, cases, evidence = run_scenario("S4", self.context)
        self.assertTrue(all(e["monitoring"]["classification"] == "NORMAL" for e in events))
        self.assertEqual(cases, [])
        self.assertEqual(evidence, [])

        state = engine.MonitorState("RUN-S4", "S4")
        facts = [engine.apply_monitoring(t, self.context, state)["facts"]
                 for t in engine.load_authorisations("S4")]
        self.assertFalse(facts[0]["burst_suppressed"])  # a single payment is within baseline
        self.assertTrue(all(f["burst_suppressed"] for f in facts[1:]))

    def test_s5_no_task(self):
        events, cases, _ = run_scenario("S5", self.context)
        self.assertEqual(events[0]["monitoring"]["classification"], "REVIEW")
        self.assertEqual(events[0]["monitoring"]["signals"], "NO_TASK")
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["case_type"], "MISSING_EVIDENCE")
        self.assertIn("intent not verifiable", cases[0]["reason"])

    def test_single_signal_scenarios(self):
        for scenario_id, classification, signal, case_type in [
            ("S6", "HIGH", "AMOUNT_EXCEEDS_TASK", "RULE_MISMATCH"),
            ("S7", "HIGH", "OUTSIDE_TASK_WINDOW", "RULE_MISMATCH"),
            ("S8", "HIGH", "REFERENCE_MISMATCH", "RULE_MISMATCH"),
            ("S9", "REVIEW", "TASK_UNVERIFIED", "MISSING_EVIDENCE"),
        ]:
            with self.subTest(scenario=scenario_id):
                events, cases, _ = run_scenario(scenario_id, self.context)
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0]["card_decision"], "APPROVED")
                self.assertEqual(events[0]["monitoring"]["classification"], classification)
                self.assertEqual(events[0]["monitoring"]["signals"], signal)
                self.assertEqual(len(cases), 1)
                self.assertEqual(cases[0]["case_type"], case_type)

    def test_outside_window_reason(self):
        _, cases, _ = run_scenario("S7", self.context)
        self.assertEqual(cases[0]["reason"], "Payment at 19:30 UTC is outside the task T-700 window (08:00–18:00).")
        state = engine.MonitorState("RUN-FX", "FX")
        engine.apply_monitoring(fixture_txn("T-100", "40.00", "2026-10-12T19:00:00Z"), self.context, state)
        self.assertEqual(engine.case_rows(state)[0]["reason"],
                         "Payment at 19:00 UTC is outside the task T-100 window (08:00–18:00).")

    def test_s10_several_alerts(self):
        events, cases, _ = run_scenario("S10", self.context)
        self.assertEqual([e["monitoring"]["classification"] for e in events],
                         ["NORMAL", "HIGH", "REVIEW", "NORMAL", "HIGH"])
        self.assertTrue(all(e["card_decision"] == "APPROVED" for e in events))
        self.assertFalse(any("BURST_VS_HISTORY" in e["monitoring"]["signals"] for e in events))
        self.assertEqual([(c["case_id"], c["severity"], c["txn_count"]) for c in cases],
                         [("CASE-S10-01", "HIGH", "1"), ("CASE-S10-02", "REVIEW", "1"), ("CASE-S10-03", "HIGH", "2")])
        self.assertEqual(cases[0]["reason"], "Payment of £45.00 exceeds task T-1002 maximum of £30.00.")
        self.assertEqual(cases[2]["reason"], "2 payments made against task T-1003, which authorises 1.")


class TestIndependence(MonitoringTestCase):
    def test_excerpt_blind(self):
        blank = engine.MappingProxyType(dict(self.context, actions=tuple(
            engine.MappingProxyType(dict(a, excerpt="")) for a in self.context["actions"])))
        for scenario_id in engine.SCENARIO_IDS:
            with self.subTest(scenario=scenario_id):
                normal = run_scenario(scenario_id, self.context)
                blinded = run_scenario(scenario_id, blank)
                self.assertEqual([e["monitoring"] for e in normal[0]], [e["monitoring"] for e in blinded[0]])
                self.assertEqual(normal[1], blinded[1])
                self.assertEqual(normal[2], blinded[2])

    def test_card_decisions_unchanged_by_monitoring(self):
        def decisions(mode):
            return [(e["txn_id"], e["card_decision"], e["rule_triggered"]) for e in engine.replay_all(mode)]
        controls = decisions("controls_only")
        self.assertEqual(len(controls), 50)
        self.assertEqual(controls, decisions(MON))

    def test_controls_only_writes_no_monitoring_output(self):
        for scenario_id in engine.SCENARIO_IDS:
            events = list(engine.replay(scenario_id, "controls_only"))
            with self.subTest(scenario=scenario_id):
                self.assertTrue(all(e["monitoring"] is None for e in events))
                for name in ("monitoring_results", "cases", "case_evidence"):
                    self.assertEqual(read_output(name), [])

    def test_simulate_matches_replay_without_writing(self):
        engine.reset()
        list(engine.replay("S4", MON, self.context))  # leave a known run on disk
        paths = [engine.output_path(n) for n in engine.OUTPUT_SCHEMAS]
        before = [file_hash(p) for p in paths]
        for mode in engine.MODES:
            for scenario_id in engine.SCENARIO_IDS:
                with self.subTest(mode=mode, scenario=scenario_id):
                    simulated = engine.simulate(scenario_id, mode, self.context)
                    self.assertEqual([file_hash(p) for p in paths], before)
                    replayed = list(engine.replay(scenario_id, mode, self.context))
                    self.assertEqual(simulated, replayed)
                    list(engine.replay("S4", MON, self.context))

    def test_determinism(self):
        for scenario_id in engine.SCENARIO_IDS:
            hashes = []
            for _ in range(2):
                list(engine.replay(scenario_id, MON))
                hashes.append([file_hash(engine.output_path(n)) for n in engine.OUTPUT_SCHEMAS])
            with self.subTest(scenario=scenario_id):
                self.assertEqual(hashes[0], hashes[1])


class TestFixtures(MonitoringTestCase):
    def check(self, txn, context, classification, signal):
        result = engine.apply_monitoring(txn, context, engine.MonitorState("RUN-FX", "FX"))
        self.assertEqual(result["classification"], classification)
        self.assertIn(signal, result["signals"].split(";"))
        self.assertTrue(result["case_id"])

    def test_amount_exceeds_task(self):
        self.check(fixture_txn("T-200", "70.00", "2026-10-14T11:00:00Z", reference="LIC-7"),
                   self.context, "HIGH", "AMOUNT_EXCEEDS_TASK")

    def test_outside_task_window(self):
        self.check(fixture_txn("T-100", "40.00", "2026-10-12T19:00:00Z"),
                   self.context, "HIGH", "OUTSIDE_TASK_WINDOW")

    def test_task_unverified(self):
        unverified = dict(self.context["tasks"]["T-100"], task_id="T-998", verified_source=False)
        context = engine.MappingProxyType(dict(self.context, tasks=engine.MappingProxyType(
            dict(self.context["tasks"], **{"T-998": engine.MappingProxyType(unverified)}))))
        self.check(fixture_txn("T-998", "40.00", "2026-10-12T09:00:00Z"), context, "REVIEW", "TASK_UNVERIFIED")

    def test_task_not_found(self):
        self.check(fixture_txn("T-999", "40.00", "2026-10-12T09:00:00Z"),
                   self.context, "REVIEW", "TASK_NOT_FOUND")


class TestGuards(MonitoringTestCase):
    def test_wording(self):
        texts = []
        for scenario_id in engine.SCENARIO_IDS:
            _, cases, _ = run_scenario(scenario_id, self.context)
            texts += [c[k] for c in cases for k in ("reason", "recommended_action")]
        fixtures = [
            (fixture_txn("T-200", "70.00", "2026-10-14T11:00:00Z", reference="LIC-7"), self.context),
            (fixture_txn("T-100", "40.00", "2026-10-12T19:00:00Z", reference="X-1"), self.context),
            (fixture_txn("T-999", "40.00", "2026-10-12T09:00:00Z"), self.context),
        ]
        for txn, context in fixtures:
            state = engine.MonitorState("RUN-FX", "FX")
            engine.apply_monitoring(txn, context, state)
            texts += [r[k] for r in engine.case_rows(state) for k in ("reason", "recommended_action")]
        self.assertTrue(texts)
        for text in texts:
            for word in BANNED_WORDS:
                with self.subTest(text=text, word=word):
                    self.assertNotIn(word, text.lower())

    def test_assess_does_not_mutate_state(self):
        state = engine.MonitorState("RUN-S2", "S2")
        txns = engine.load_authorisations("S2")
        for t in txns[:3]:
            engine.apply_monitoring(t, self.context, state)
        before = copy.deepcopy(vars(state))
        engine.assess(txns[3], self.context, state)
        engine.assess(engine.load_authorisations("S5")[0], self.context, state)
        self.assertEqual(vars(state), before)


if __name__ == "__main__":
    unittest.main()
