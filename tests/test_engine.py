import csv
import hashlib
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import engine  # noqa: E402

EXPECTED_PATH = os.path.join(ROOT, "tests", "expected_results.csv")

POLICY = {"agent_id": "AG-101", "max_per_payment": 10000, "daily_cap": 50000, "hourly_count_limit": 20}
MERCHANTS = {"ToolCloud", "MetricsLane"}


def load_expected():
    with open(EXPECTED_PATH, encoding="utf-8", newline="") as f:
        return {r["txn_id"]: r for r in csv.DictReader(f)}


def file_hash(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def txn(amount, timestamp, merchant="ToolCloud", txn_id="FX-1"):
    return {"txn_id": txn_id, "agent_id": "AG-101", "task_id": "", "merchant": merchant,
            "amount": amount, "timestamp": timestamp, "reference": "FIXTURE"}


def run(txns):
    state = engine.ControlState()
    return [engine.apply_controls(t, POLICY, MERCHANTS, state) for t in txns]


class TestReplay(unittest.TestCase):
    def tearDown(self):
        engine.reset()

    def test_replay_all_matches_expected_card_decisions(self):
        expected = load_expected()
        events = engine.replay_all("controls_only")
        self.assertEqual(sorted(e["txn_id"] for e in events), sorted(expected))
        for e in events:
            with self.subTest(txn_id=e["txn_id"]):
                self.assertEqual(e["card_decision"], expected[e["txn_id"]]["expected_card_decision"])
                self.assertEqual(e["card_decision"], "APPROVED")

    def test_replay_is_deterministic(self):
        path = engine.output_path("card_control_results")
        for scenario_id in engine.SCENARIO_IDS:
            with self.subTest(scenario_id=scenario_id):
                list(engine.replay(scenario_id))
                first = file_hash(path)
                list(engine.replay(scenario_id))
                self.assertEqual(first, file_hash(path))

    def test_reset_leaves_headers_only(self):
        list(engine.replay("S2"))
        engine.reset()
        for name, header in engine.OUTPUT_SCHEMAS.items():
            with self.subTest(file=name):
                with open(engine.output_path(name), encoding="utf-8", newline="") as f:
                    self.assertEqual(list(csv.reader(f)), [header])

    def test_mode_parity(self):
        decisions = {}
        for mode in engine.MODES:
            decisions[mode] = [(e["txn_id"], e["card_decision"], e["rule_triggered"])
                               for e in engine.replay_all(mode)]
        self.assertEqual(decisions["controls_only"], decisions["controls_plus_monitoring"])


class TestCardControls(unittest.TestCase):
    def test_max_per_payment(self):
        self.assertEqual(run([txn("150.00", "2026-11-02T10:00:00Z")]),
                         [("DECLINED", "MAX_PER_PAYMENT_EXCEEDED")])

    def test_merchant_not_allowed(self):
        self.assertEqual(run([txn("20.00", "2026-11-02T10:00:00Z", merchant="CloudDesk")]),
                         [("DECLINED", "MERCHANT_NOT_ALLOWED")])

    def test_daily_cap(self):
        txns = [txn("90.00", f"2026-11-02T{9 + i:02d}:00:00Z", txn_id=f"FX-{i}") for i in range(6)]
        results = run(txns)
        self.assertEqual(results[:5], [("APPROVED", "")] * 5)
        self.assertEqual(results[5], ("DECLINED", "DAILY_CAP_EXCEEDED"))

    def test_hourly_count(self):
        txns = [txn("5.00", f"2026-11-02T10:{i:02d}:00Z", txn_id=f"FX-{i}") for i in range(21)]
        results = run(txns)
        self.assertEqual(results[:20], [("APPROVED", "")] * 20)
        self.assertEqual(results[20], ("DECLINED", "HOURLY_COUNT_EXCEEDED"))

    def test_declined_payment_does_not_count(self):
        # Daily cap: 5 x 90.00 = 450.00 approved; a declined 150.00 must not consume headroom.
        txns = [txn("90.00", f"2026-11-02T{9 + i:02d}:00:00Z", txn_id=f"FX-{i}") for i in range(5)]
        txns.insert(2, txn("150.00", "2026-11-02T10:30:00Z", txn_id="FX-BIG"))
        txns.append(txn("50.00", "2026-11-02T15:00:00Z", txn_id="FX-LAST"))
        results = run(txns)
        self.assertEqual(results[2], ("DECLINED", "MAX_PER_PAYMENT_EXCEEDED"))
        self.assertEqual(results[-1], ("APPROVED", ""))

        # Hourly count: 19 approved + 1 declined (unlisted merchant), then the 21st is still approved.
        txns = [txn("5.00", f"2026-11-02T10:{i:02d}:00Z", txn_id=f"FX-{i}") for i in range(19)]
        txns.append(txn("5.00", "2026-11-02T10:19:00Z", merchant="CloudDesk", txn_id="FX-BAD"))
        txns.append(txn("5.00", "2026-11-02T10:20:00Z", txn_id="FX-20"))
        results = run(txns)
        self.assertEqual(results[19], ("DECLINED", "MERCHANT_NOT_ALLOWED"))
        self.assertEqual(results[20], ("APPROVED", ""))

    def test_evaluate_is_pure(self):
        state = engine.ControlState()
        engine.evaluate(txn("40.00", "2026-11-02T10:00:00Z"), POLICY, MERCHANTS, state)
        self.assertEqual(dict(state.approved), {})


class TestPathGuard(unittest.TestCase):
    def test_engine_cannot_open_tests_files(self):
        with self.assertRaises(engine.TestsPathAccessError):
            engine.read_csv(EXPECTED_PATH)
        with self.assertRaises(engine.TestsPathAccessError):
            engine._open(os.path.join(engine.SEED_DIR, "..", "..", "tests", "expected_results.csv"))


if __name__ == "__main__":
    unittest.main()
