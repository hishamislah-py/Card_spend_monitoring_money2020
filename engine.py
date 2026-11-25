"""Replay engine for the AG-101 Agent Spend Monitor POC.

Replays synthetic card authorisations through simulated issuer card controls
and, optionally, an advisory agent-intent monitoring layer, using transaction
timestamps as a simulated clock. Standard library only; no real time, no sleep,
no randomness, so output is byte-identical across runs.

The engine never reads anything under tests/ (enforced by _open).
"""

import argparse
import csv
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from types import MappingProxyType

ROOT = os.path.dirname(os.path.abspath(__file__))
SEED_DIR = os.path.join(ROOT, "data", "seed")
OUTPUT_DIR = os.path.join(ROOT, "data", "output")
LIVE_DIR = os.path.join(ROOT, "data", "live")  # live session only; never data/seed or data/output
TESTS_DIR = os.path.join(ROOT, "tests")

SCENARIO_IDS = [f"S{n}" for n in range(1, 17)]
MODES = ("controls_only", "controls_plus_monitoring")

OUTPUT_SCHEMAS = {
    "card_control_results": ["run_id", "txn_id", "decision", "rule_triggered"],
    "monitoring_results": ["run_id", "txn_id", "classification", "signals", "case_id"],
    "cases": ["case_id", "run_id", "scenario_id", "agent_id", "task_id", "severity", "case_type", "reason",
              "recommended_action", "status", "txn_count", "total_amount", "opened_at", "updated_at"],
    "case_evidence": ["case_id", "action_id", "evidence_label"],
}
# Analyst review records. Cleared by reset() (and so at the start of every replay) but never written by a replay,
# so they are kept apart from OUTPUT_SCHEMAS, whose files must be byte-identical for the same replay.
ANALYST_SCHEMAS = {
    "case_review": ["case_id", "status", "disposition", "updated_at"],
    "case_notes": ["note_id", "case_id", "created_at", "author", "text", "source"],
    "case_checklist": ["case_id", "item_id", "checked", "updated_at"],
    "case_activity": ["activity_id", "case_id", "at", "kind", "detail"],
}
SCHEMAS = {**OUTPUT_SCHEMAS, **ANALYST_SCHEMAS}
# Seed file layouts, used by the live session, which writes its own tasks, actions and authorisations.
SEED_SCHEMAS = {
    "owner_tasks": ["task_id", "agent_id", "approved_merchant", "max_amount_per_payment", "permitted_payment_count",
                    "reference", "valid_from", "valid_to", "verified_source", "verification_note"],
    "agent_actions": ["action_id", "scenario_id", "agent_id", "task_id", "timestamp", "action_type", "source_type",
                      "excerpt", "referenced_merchant", "related_txn_id"],
    "authorisations": ["txn_id", "scenario_id", "agent_id", "task_id", "merchant", "amount", "currency", "timestamp",
                       "reference"],
}
LIVE_SCHEMAS = {**SEED_SCHEMAS, **SCHEMAS}

APPROVED = "APPROVED"
DECLINED = "DECLINED"
MERCHANT_NOT_ALLOWED = "MERCHANT_NOT_ALLOWED"
MAX_PER_PAYMENT_EXCEEDED = "MAX_PER_PAYMENT_EXCEEDED"
DAILY_CAP_EXCEEDED = "DAILY_CAP_EXCEEDED"
HOURLY_COUNT_EXCEEDED = "HOURLY_COUNT_EXCEEDED"

NORMAL = "NORMAL"
REVIEW = "REVIEW"
HIGH = "HIGH"

NO_TASK = "NO_TASK"
TASK_NOT_FOUND = "TASK_NOT_FOUND"
TASK_UNVERIFIED = "TASK_UNVERIFIED"
MERCHANT_MISMATCH = "MERCHANT_MISMATCH"
AMOUNT_EXCEEDS_TASK = "AMOUNT_EXCEEDS_TASK"
OUTSIDE_TASK_WINDOW = "OUTSIDE_TASK_WINDOW"
REFERENCE_MISMATCH = "REFERENCE_MISMATCH"
COUNT_EXCEEDED = "COUNT_EXCEEDED"
DUPLICATE_REFERENCE = "DUPLICATE_REFERENCE"
BURST_VS_HISTORY = "BURST_VS_HISTORY"

SIGNAL_ORDER = [NO_TASK, TASK_NOT_FOUND, TASK_UNVERIFIED, MERCHANT_MISMATCH, AMOUNT_EXCEEDS_TASK,
                OUTSIDE_TASK_WINDOW, REFERENCE_MISMATCH, COUNT_EXCEEDED, DUPLICATE_REFERENCE, BURST_VS_HISTORY]
REVIEW_SIGNALS = {NO_TASK, TASK_NOT_FOUND, TASK_UNVERIFIED, BURST_VS_HISTORY}
HIGH_SIGNALS = set(SIGNAL_ORDER) - REVIEW_SIGNALS
# Which signal drives a case's reason text, highest priority first.
REASON_PRIORITY = [COUNT_EXCEEDED, MERCHANT_MISMATCH, AMOUNT_EXCEEDS_TASK, OUTSIDE_TASK_WINDOW, REFERENCE_MISMATCH,
                   DUPLICATE_REFERENCE, NO_TASK, TASK_NOT_FOUND, TASK_UNVERIFIED, BURST_VS_HISTORY]
SEVERITY_RANK = {REVIEW: 1, HIGH: 2}

BURST_WINDOW = timedelta(minutes=10)
DEFAULT_BURST_BASELINE = 1  # used only for an agent with no history

LABEL_OWNER_TASK = "Owner task instruction"
LABEL_PAYMENT_ACTION = "Agent payment action"
LABEL_SUPPORTING = "Supporting evidence – not proof of malicious intent"


class TestsPathAccessError(RuntimeError):
    """Raised if the engine attempts to open a file under tests/."""


# ---------------------------------------------------------------- file I/O

def _open(path, mode="r"):
    resolved = os.path.normcase(os.path.realpath(path))
    tests = os.path.normcase(os.path.realpath(TESTS_DIR))
    if resolved == tests or resolved.startswith(tests + os.sep):
        raise TestsPathAccessError(f"Engine must not open files under tests/: {path}")
    return open(path, mode, encoding="utf-8", newline="")


def read_csv(path):
    with _open(path) as f:
        return list(csv.DictReader(f))


def _write_rows(path, rows, mode):
    with _open(path, mode) as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerows(rows)


def output_path(name, directory=OUTPUT_DIR):
    return os.path.join(directory, f"{name}.csv")


def reset():
    """Clear all output CSVs, including analyst review records, back to headers only."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for name, header in SCHEMAS.items():
        _write_rows(output_path(name), [header], "w")


def append_output(name, row, directory=OUTPUT_DIR):
    header = LIVE_SCHEMAS[name]
    _write_rows(output_path(name, directory), [[row.get(col, "") for col in header]], "a")


def rewrite_output(name, rows, directory=OUTPUT_DIR):
    header = LIVE_SCHEMAS[name]
    _write_rows(output_path(name, directory), [header] + [[row.get(col, "") for col in header] for row in rows], "w")


# ---------------------------------------------------------------- parsing

def parse_ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def to_pence(s):
    whole, _, frac = s.partition(".")
    return int(whole) * 100 + int((frac + "00")[:2])


def money(pence):
    return f"{pence // 100}.{pence % 100:02d}"


def load_policy(agent_id):
    for row in read_csv(os.path.join(SEED_DIR, "policy.csv")):
        if row["agent_id"] == agent_id:
            return {
                "agent_id": agent_id,
                "max_per_payment": to_pence(row["max_per_payment"]),
                "daily_cap": to_pence(row["daily_cap"]),
                "hourly_count_limit": int(row["hourly_count_limit"]),
            }
    raise KeyError(f"No policy for agent {agent_id}")


def load_merchants(agent_id):
    return {r["merchant"] for r in read_csv(os.path.join(SEED_DIR, "allowed_merchants.csv"))
            if r["agent_id"] == agent_id}


def load_authorisations(scenario_id):
    rows = [r for r in read_csv(os.path.join(SEED_DIR, "authorisations.csv")) if r["scenario_id"] == scenario_id]
    return sorted(rows, key=lambda r: (parse_ts(r["timestamp"]), r["txn_id"]))


# ---------------------------------------------------------------- card controls

class ControlState:
    """Approved-payment ledger for one run. Only approved payments are recorded."""

    def __init__(self):
        self.approved = defaultdict(list)  # agent_id -> [(datetime, pence)]

    def record(self, txn):
        self.approved[txn["agent_id"]].append((parse_ts(txn["timestamp"]), to_pence(txn["amount"])))


def evaluate(txn, policy, merchants, state):
    """Pure simulated issuer controls. Returns (decision, rule_triggered).

    Deliberately ignores task_id and reference: there is no duplicate check.
    """
    amount = to_pence(txn["amount"])
    when = parse_ts(txn["timestamp"])
    ledger = state.approved.get(txn["agent_id"], [])

    if txn["merchant"] not in merchants:
        return DECLINED, MERCHANT_NOT_ALLOWED
    if amount > policy["max_per_payment"]:
        return DECLINED, MAX_PER_PAYMENT_EXCEEDED
    day_total = sum(p for t, p in ledger if t.date() == when.date())
    if day_total + amount > policy["daily_cap"]:
        return DECLINED, DAILY_CAP_EXCEEDED
    window_start = when - timedelta(minutes=60)
    hour_count = sum(1 for t, _ in ledger if window_start <= t <= when)
    if hour_count + 1 > policy["hourly_count_limit"]:
        return DECLINED, HOURLY_COUNT_EXCEEDED
    return APPROVED, ""


def apply_controls(txn, policy, merchants, state):
    """Evaluate a transaction and update state if approved."""
    decision, rule = evaluate(txn, policy, merchants, state)
    if decision == APPROVED:
        state.record(txn)
    return decision, rule


# ---------------------------------------------------------------- monitoring context

def max_in_window(times, window):
    """Largest number of timestamps in any window [t - window, t]."""
    times = sorted(times)
    best, lo = 0, 0
    for hi in range(len(times)):
        while times[hi] - times[lo] > window:
            lo += 1
        best = max(best, hi - lo + 1)
    return best


def load_context():
    """Load owner tasks, agent actions and the history baseline as a read-only mapping."""
    return build_context(read_csv(os.path.join(SEED_DIR, "owner_tasks.csv")),
                         read_csv(os.path.join(SEED_DIR, "agent_actions.csv")), history_baseline())


def history_baseline():
    """Most payments any agent made in a 10-minute window of its seed history."""
    history_times = defaultdict(list)
    for r in read_csv(os.path.join(SEED_DIR, "agent_history.csv")):
        history_times[r["agent_id"]].append(parse_ts(r["timestamp"]))
    return {agent: max_in_window(times, BURST_WINDOW) for agent, times in history_times.items()}


def build_context(task_rows, action_rows, baseline):
    """Read-only monitoring context from owner task rows, agent action rows and a burst baseline."""
    tasks = {}
    for r in task_rows:
        tasks[r["task_id"]] = MappingProxyType({
            "task_id": r["task_id"],
            "agent_id": r["agent_id"],
            "approved_merchant": r["approved_merchant"],
            "max_amount_per_payment": to_pence(r["max_amount_per_payment"]),
            "permitted_payment_count": int(r["permitted_payment_count"]),
            "reference": r["reference"],
            "valid_from": parse_ts(r["valid_from"]),
            "valid_to": parse_ts(r["valid_to"]),
            "verified_source": r["verified_source"] == "true",
        })
    actions = tuple(MappingProxyType(dict(r)) for r in action_rows)
    return MappingProxyType({
        "tasks": MappingProxyType(tasks),
        "actions": actions,
        "burst_baseline": MappingProxyType(dict(baseline)),
    })


class MonitorState:
    """Per-run monitoring state. Payments are recorded whatever the card decision."""

    def __init__(self, run_id, scenario_id):
        self.run_id = run_id
        self.scenario_id = scenario_id
        self.observed = defaultdict(list)    # task_id -> [txn]
        self.references = defaultdict(set)   # task_id -> {reference}
        self.recent = defaultdict(list)      # agent_id -> [(datetime, task_id)]
        self.cases = {}                      # case_key -> case dict


# ---------------------------------------------------------------- monitoring rules

def assess(txn, context, state):
    """Pure monitoring assessment from structured fields only. Does not mutate state.

    Returns {classification, signals, case_key, facts}. Never reads card_decision or excerpts.
    """
    tasks = context["tasks"]
    task_id = txn["task_id"]
    amount = to_pence(txn["amount"])
    when = parse_ts(txn["timestamp"])
    reference = txn["reference"]
    task_count = len(state.observed.get(task_id, ())) + 1 if task_id else 0
    signals = set()

    if not task_id:
        signals.add(NO_TASK)
    elif task_id not in tasks:
        signals.add(TASK_NOT_FOUND)
    else:
        task = tasks[task_id]
        if not task["verified_source"]:
            signals.add(TASK_UNVERIFIED)
        if txn["merchant"] != task["approved_merchant"]:
            signals.add(MERCHANT_MISMATCH)
        if amount > task["max_amount_per_payment"]:
            signals.add(AMOUNT_EXCEEDS_TASK)
        if when < task["valid_from"] or when > task["valid_to"]:
            signals.add(OUTSIDE_TASK_WINDOW)
        if reference != task["reference"] and not reference.startswith(task["reference"] + "-"):
            signals.add(REFERENCE_MISMATCH)
        if task_count > task["permitted_payment_count"]:
            signals.add(COUNT_EXCEEDED)
        if reference in state.references.get(task_id, ()):
            signals.add(DUPLICATE_REFERENCE)

    agent_id = txn["agent_id"]
    window = [tid for t, tid in state.recent.get(agent_id, ()) if when - BURST_WINDOW <= t <= when] + [task_id]
    burst_count = len(window)
    burst_suppressed = False
    if burst_count > context["burst_baseline"].get(agent_id, DEFAULT_BURST_BASELINE):
        def within_task(tid):
            t = tasks.get(tid) if tid else None
            observed = len(state.observed.get(tid, ())) + (1 if tid == task_id else 0)
            return t is not None and t["verified_source"] and observed <= t["permitted_payment_count"]

        if all(within_task(tid) for tid in window):
            burst_suppressed = True
        else:
            signals.add(BURST_VS_HISTORY)

    ordered = [s for s in SIGNAL_ORDER if s in signals]
    if signals & HIGH_SIGNALS:
        classification = HIGH
    elif signals:
        classification = REVIEW
    else:
        classification = NORMAL

    if classification == NORMAL:
        case_key = None
    elif signals & {NO_TASK, TASK_NOT_FOUND}:
        case_key = (state.run_id, "TXN", txn["txn_id"])
    else:
        case_key = (state.run_id, "TASK", task_id)

    return {
        "classification": classification,
        "signals": ordered,
        "case_key": case_key,
        "facts": {"task_count": task_count, "burst_count": burst_count, "burst_suppressed": burst_suppressed},
    }


def _case_payments(case, state):
    return case["own_txns"] if case["own_txns"] is not None else state.observed[case["task_id"]]


def _case_reason(case, context, state):
    code = next(c for c in REASON_PRIORITY if c in case["fired"])
    txn, facts = case["signal_source"][code]
    task_id = case["task_id"]
    task = context["tasks"].get(task_id)
    if code == COUNT_EXCEEDED:
        return (f"{len(state.observed[task_id])} payments made against task {task_id}, "
                f"which authorises {task['permitted_payment_count']}.")
    if code == MERCHANT_MISMATCH:
        return f"Payment to {txn['merchant']}, but task {task_id} authorises {task['approved_merchant']}."
    if code == AMOUNT_EXCEEDS_TASK:
        return (f"Payment of £{txn['amount']} exceeds task {task_id} maximum of "
                f"£{money(task['max_amount_per_payment'])}.")
    if code == OUTSIDE_TASK_WINDOW:
        return (f"Payment at {txn['timestamp'][11:16]} UTC is outside the task {task_id} window "
                f"({task['valid_from']:%H:%M}–{task['valid_to']:%H:%M}).")
    if code == REFERENCE_MISMATCH:
        return f"Reference {txn['reference']} does not match task {task_id} reference {task['reference']}."
    if code == DUPLICATE_REFERENCE:
        return f"Reference {txn['reference']} was already used for a payment against task {task_id}."
    if code in (NO_TASK, TASK_NOT_FOUND):
        return "No verified owner task is linked to this payment; intent not verifiable."
    if code == TASK_UNVERIFIED:
        return f"Linked task {task_id} is not from a verified source; intent not verifiable."
    return f"{facts['burst_count']} payments in 10 minutes, above this agent's usual pattern."


def _case_evidence(case, context, state):
    task_id = case["task_id"]
    task = context["tasks"].get(task_id) if task_id else None
    payment_ids = {t["txn_id"] for t in _case_payments(case, state)}
    found = []
    for a in context["actions"]:
        if a["agent_id"] != case["agent_id"] or parse_ts(a["timestamp"]) > case["last_flagged_at"]:
            continue
        if not ((task_id and a["task_id"] == task_id) or a["related_txn_id"] in payment_ids):
            continue
        if a["action_type"] == "task_received" and a["source_type"] == "owner":
            label = LABEL_OWNER_TASK
        elif a["action_type"] == "payment_initiated" and a["related_txn_id"] in payment_ids:
            label = LABEL_PAYMENT_ACTION
        elif (a["source_type"] == "external" and a["referenced_merchant"] and task is not None
              and a["referenced_merchant"] != task["approved_merchant"]):
            label = LABEL_SUPPORTING
        else:
            continue
        found.append((parse_ts(a["timestamp"]), a["action_id"], label))
    return [{"case_id": case["case_id"], "action_id": action_id, "evidence_label": label}
            for _, action_id, label in sorted(found)]


def _refresh_case(case, context, state):
    payments = _case_payments(case, state)
    case["txn_count"] = len(payments)
    case["total_amount"] = money(sum(to_pence(t["amount"]) for t in payments))
    if case["fired"] & HIGH_SIGNALS:
        case["case_type"] = "RULE_MISMATCH"
    elif case["fired"] == {BURST_VS_HISTORY}:
        case["case_type"] = "BEHAVIOUR_REVIEW"
    else:
        case["case_type"] = "MISSING_EVIDENCE"
    case["reason"] = _case_reason(case, context, state)
    if case["severity"] == HIGH:
        case["recommended_action"] = (f"Pause agent {case['agent_id']} via existing card controls "
                                      f"and review task {case['task_id']}.")
    else:
        case["recommended_action"] = "Confirm intent with the agent owner before further payments."
    case["evidence"] = _case_evidence(case, context, state)


def apply_monitoring(txn, context, state):
    """Assess a transaction, record it in state and open/update its case.

    Returns {classification, signals, case_id, facts}; signals is ';'-joined.
    """
    result = assess(txn, context, state)
    task_id = txn["task_id"]
    when = parse_ts(txn["timestamp"])
    if task_id:
        state.observed[task_id].append(txn)
        state.references[task_id].add(txn["reference"])
    state.recent[txn["agent_id"]].append((when, task_id))

    case_id = ""
    key = result["case_key"]
    if key is not None:
        case = state.cases.get(key)
        if case is None:
            case = {
                "case_id": f"CASE-{state.scenario_id}-{len(state.cases) + 1:02d}",
                "run_id": state.run_id, "scenario_id": state.scenario_id, "agent_id": txn["agent_id"],
                "task_id": task_id, "severity": result["classification"], "status": "OPEN",
                "opened_at": txn["timestamp"], "own_txns": [] if key[1] == "TXN" else None,
                "fired": set(), "signal_source": {},
            }
            state.cases[key] = case
        if case["own_txns"] is not None:
            case["own_txns"].append(txn)
        if SEVERITY_RANK[result["classification"]] > SEVERITY_RANK[case["severity"]]:
            case["severity"] = result["classification"]
        case["fired"].update(result["signals"])
        for code in result["signals"]:
            case["signal_source"][code] = (txn, result["facts"])
        case["updated_at"] = txn["timestamp"]
        case["last_flagged_at"] = when
        case_id = case["case_id"]

    # Keep counts and totals current on this task's case, even for unflagged payments.
    task_case = state.cases.get((state.run_id, "TASK", task_id)) if task_id else None
    for case in {id(c): c for c in (task_case, state.cases.get(key) if key else None) if c}.values():
        _refresh_case(case, context, state)

    return {
        "classification": result["classification"],
        "signals": ";".join(result["signals"]),
        "case_id": case_id,
        "facts": result["facts"],
    }


def case_rows(state):
    return sorted(({k: c[k] for k in OUTPUT_SCHEMAS["cases"]} for c in state.cases.values()),
                  key=lambda r: r["case_id"])


def evidence_rows(state):
    cases = sorted(state.cases.values(), key=lambda c: c["case_id"])
    return [row for c in cases for row in c["evidence"]]


def monitor(event, monitor_state, context, write=True):
    """Advisory monitoring for one event. Writes monitoring outputs; never touches card decisions."""
    result = apply_monitoring(event, context, monitor_state)
    if write:
        append_output("monitoring_results", {"run_id": monitor_state.run_id, "txn_id": event["txn_id"],
                                             "classification": result["classification"],
                                             "signals": result["signals"], "case_id": result["case_id"]})
        rewrite_output("cases", case_rows(monitor_state))
        rewrite_output("case_evidence", evidence_rows(monitor_state))
    return {k: result[k] for k in ("classification", "signals", "case_id")}


# ---------------------------------------------------------------- replay

def _run(scenario_id, mode, context, write, monitor_state=None):
    if mode not in MODES:
        raise ValueError(f"Unknown mode {mode!r}; expected one of {MODES}")
    txns = load_authorisations(scenario_id)
    run_id = f"RUN-{scenario_id}"
    control_state = ControlState()
    if monitor_state is None:
        monitor_state = MonitorState(run_id, scenario_id)
    if mode == "controls_plus_monitoring" and context is None:
        context = load_context()
    policies, merchant_sets = {}, {}
    if write:
        reset()

    for txn in txns:
        agent_id = txn["agent_id"]
        if agent_id not in policies:
            policies[agent_id] = load_policy(agent_id)
            merchant_sets[agent_id] = load_merchants(agent_id)
        decision, rule = apply_controls(txn, policies[agent_id], merchant_sets[agent_id], control_state)
        if write:
            append_output("card_control_results",
                          {"run_id": run_id, "txn_id": txn["txn_id"], "decision": decision, "rule_triggered": rule})

        event = {
            "run_id": run_id, "scenario_id": scenario_id, "txn_id": txn["txn_id"], "agent_id": agent_id,
            "timestamp": txn["timestamp"], "merchant": txn["merchant"], "amount": txn["amount"],
            "task_id": txn["task_id"], "reference": txn["reference"],
            "card_decision": decision, "rule_triggered": rule, "monitoring": None,
        }
        if mode == "controls_plus_monitoring":
            event["monitoring"] = monitor(event, monitor_state, context, write)
        yield event


def replay(scenario_id, mode="controls_only", context=None):
    """Replay one scenario, yielding one event per transaction and writing data/output."""
    return _run(scenario_id, mode, context, write=True)


def simulate(scenario_id, mode="controls_only", context=None):
    """Run one scenario fully in memory; data/output is not touched."""
    return list(_run(scenario_id, mode, context, write=False))


def simulate_with_cases(scenario_id, context=None):
    """Run one scenario with monitoring fully in memory. Returns (events, case rows); data/output is not touched."""
    state = MonitorState(f"RUN-{scenario_id}", scenario_id)
    events = list(_run(scenario_id, "controls_plus_monitoring", context, write=False, monitor_state=state))
    return events, case_rows(state)


def replay_all(mode="controls_only", context=None):
    """Replay every scenario (S1-S16) in order. Returns all events; leaves the last scenario's results on disk."""
    if mode == "controls_plus_monitoring" and context is None:
        context = load_context()
    events = []
    for scenario_id in SCENARIO_IDS:
        reset()
        events.extend(replay(scenario_id, mode, context))
    return events


# ---------------------------------------------------------------- read helpers (used by server.py)

CASE_STATUSES = ("OPEN", "IN_REVIEW", "REVIEWED", "ESCALATED", "DISMISSED")

SIGNAL_DESCRIPTIONS = {
    NO_TASK: "No owner task is linked to the payment.",
    TASK_NOT_FOUND: "The linked task does not exist in owner tasks.",
    TASK_UNVERIFIED: "The linked task is not from a verified source.",
    MERCHANT_MISMATCH: "Merchant differs from the task's approved merchant.",
    AMOUNT_EXCEEDS_TASK: "Amount is above the task's maximum per payment.",
    OUTSIDE_TASK_WINDOW: "Payment time is outside the task's validity window.",
    REFERENCE_MISMATCH: "Payment reference does not match the task reference.",
    COUNT_EXCEEDED: "More payments than the task permits.",
    DUPLICATE_REFERENCE: "The same reference was already paid under this task.",
    BURST_VS_HISTORY: "More payments in 10 minutes than this agent's history shows.",
}

# Owner-task fields each signal contradicts.
SIGNAL_TASK_FIELDS = {
    TASK_UNVERIFIED: ["verified_source"],
    MERCHANT_MISMATCH: ["approved_merchant"],
    AMOUNT_EXCEEDS_TASK: ["max_amount_per_payment"],
    OUTSIDE_TASK_WINDOW: ["valid_from", "valid_to"],
    REFERENCE_MISMATCH: ["reference"],
    COUNT_EXCEEDED: ["permitted_payment_count"],
    DUPLICATE_REFERENCE: ["permitted_payment_count"],
}


def read_seed(name, directory=SEED_DIR):
    return read_csv(os.path.join(directory, f"{name}.csv"))


def read_output(name, directory=OUTPUT_DIR):
    path = output_path(name, directory)
    if name in LIVE_SCHEMAS and not os.path.isfile(path):  # created by the first reset()
        return []
    return read_csv(path)


def is_live_case(case_id):
    return case_id.startswith(f"CASE-{LIVE_SCENARIO}-")


def case_dirs(case_id):
    """(input dir, output dir) holding a case: data/live for live cases, data/seed and data/output otherwise."""
    return (LIVE_DIR, LIVE_DIR) if is_live_case(case_id) else (SEED_DIR, OUTPUT_DIR)


def update_case_status(case_id, status):
    """Set analyst review status on one case in cases.csv. Returns the updated row, or None if absent."""
    if status not in CASE_STATUSES:
        raise ValueError(f"Invalid status {status!r}; expected one of {CASE_STATUSES}")
    out = case_dirs(case_id)[1]
    rows = read_output("cases", out)
    match = next((r for r in rows if r["case_id"] == case_id), None)
    if match is not None:
        match["status"] = status
        rewrite_output("cases", rows, out)
    return match


# ---------------------------------------------------------------- analyst review
# Analyst actions are human actions, not part of the simulation: callers stamp them with real wall-clock time.
# They change review records (and the case status) only; card decisions and monitoring results are untouched.

DISPOSITIONS = {
    "CONFIRMED_ISSUE": "Confirmed issue",
    "EXPECTED_BEHAVIOUR": "Expected behaviour (false positive)",
    "NEEDS_OWNER_CONFIRMATION": "Needs owner confirmation",
}
DISPOSITION_REQUIRED = ("REVIEWED", "ESCALATED", "DISMISSED")
NOTE_REQUIRED = ("ESCALATED", "DISMISSED")
NOTE_REQUIRED_MIN, NOTE_MAX = 10, 1000
ANALYST_AUTHOR = "Analyst (demo)"

CHECKLIST_TEXT = {
    "duplicate-payments": "Check whether the supplier received duplicate payments",
    "owner-intended-count": "Confirm with the owner how many payments were intended",
    "consider-pause": "Consider pausing the agent via card controls",
    "confirm-supplier": "Confirm the intended supplier with the owner",
    "review-external-content": "Review the external content the agent read before paying",
    "confirm-price": "Confirm the price with the supplier",
    "task-limit": "Check whether the task limit needs updating",
    "outside-window": "Confirm why the payment happened outside the task window",
    "confirm-reference": "Confirm the correct invoice reference with the supplier",
    "authorised-invoice": "Check whether the authorised invoice was paid separately",
    "owner-intended-payment": "Confirm with the owner that this payment was intended",
    "task-recorded": "Check whether a task should have been recorded",
    "compare-history": "Compare against the agent’s normal daily activity",
}
_COUNT_ITEMS = ["duplicate-payments", "owner-intended-count", "consider-pause"]
_TASK_ITEMS = ["owner-intended-payment", "task-recorded"]
CHECKLIST_BY_SIGNAL = {
    COUNT_EXCEEDED: _COUNT_ITEMS, DUPLICATE_REFERENCE: _COUNT_ITEMS,
    MERCHANT_MISMATCH: ["confirm-supplier", "review-external-content"],
    AMOUNT_EXCEEDS_TASK: ["confirm-price", "task-limit"],
    OUTSIDE_TASK_WINDOW: ["outside-window"],
    REFERENCE_MISMATCH: ["confirm-reference", "authorised-invoice"],
    NO_TASK: _TASK_ITEMS, TASK_NOT_FOUND: _TASK_ITEMS, TASK_UNVERIFIED: _TASK_ITEMS,
    BURST_VS_HISTORY: ["compare-history"],
}
FIRST_CHECK = "What should I check first?"
QUESTIONS_BY_SIGNAL = {
    COUNT_EXCEEDED: ["How many payments were made versus allowed?", "Were all the payments for the same invoice?"],
    DUPLICATE_REFERENCE: ["Which payments reused the same reference?", "How many payments were made versus allowed?"],
    MERCHANT_MISMATCH: ["Which supplier did the owner authorise?", "What did the agent read before paying?"],
    AMOUNT_EXCEEDS_TASK: ["How far over the task limit was the payment?", "Was the payment otherwise within the task?"],
    OUTSIDE_TASK_WINDOW: ["How far outside the task window was the payment?",
                          "Was the payment otherwise within the task?"],
    REFERENCE_MISMATCH: ["What exactly doesn’t match?", "Was the payment otherwise within the task?"],
    NO_TASK: ["What do we know about this payment?", "Why can’t the intent be verified?"],
    TASK_NOT_FOUND: ["What do we know about this payment?", "Why can’t the intent be verified?"],
    TASK_UNVERIFIED: ["Why is the task not verified?", "Was the payment otherwise within the task?"],
    BURST_VS_HISTORY: ["How does this compare with the agent’s normal activity?",
                       "How many payments were made in 10 minutes?"],
}


def checklist_items(signal_codes):
    """Deterministic review checklist for a case's signals: [(item_id, text)], de-duplicated, in signal order."""
    ids = []
    for code in SIGNAL_ORDER:
        if code in signal_codes:
            ids += [i for i in CHECKLIST_BY_SIGNAL.get(code, []) if i not in ids]
    return [(i, CHECKLIST_TEXT[i]) for i in ids]


def suggested_questions(signal_codes):
    """Three suggested questions for the case's main signal (the one that drives its reason text)."""
    main = next((c for c in REASON_PRIORITY if c in signal_codes), None)
    return (QUESTIONS_BY_SIGNAL.get(main, []) + [FIRST_CHECK])[:3]


# Analyst records are kept beside their case: data/live for live cases, data/output for replay cases.

def log_activity(case_id, at, kind, detail):
    out = case_dirs(case_id)[1]
    rows = read_output("case_activity", out)
    row = {"activity_id": f"A-{len(rows) + 1:04d}", "case_id": case_id, "at": at, "kind": kind, "detail": detail}
    append_output("case_activity", row, out)
    return row


def add_note(case_id, at, text, source="analyst"):
    out = case_dirs(case_id)[1]
    rows = read_output("case_notes", out)
    row = {"note_id": f"N-{len(rows) + 1:04d}", "case_id": case_id, "created_at": at, "author": ANALYST_AUTHOR,
           "text": text, "source": source}
    append_output("case_notes", row, out)
    return row


def set_checklist_item(case_id, item_id, checked, at):
    out = case_dirs(case_id)[1]
    rows = [r for r in read_output("case_checklist", out) if not (r["case_id"] == case_id and r["item_id"] == item_id)]
    rows.append({"case_id": case_id, "item_id": item_id, "checked": "true" if checked else "false", "updated_at": at})
    rewrite_output("case_checklist", rows, out)


def save_review(case_id, status, disposition, at):
    """Record the review decision and set the case status in cases.csv. Returns the updated case row or None."""
    case = update_case_status(case_id, status)
    if case is None:
        return None
    out = case_dirs(case_id)[1]
    rows = [r for r in read_output("case_review", out) if r["case_id"] != case_id]
    rows.append({"case_id": case_id, "status": status, "disposition": disposition, "updated_at": at})
    rewrite_output("case_review", rows, out)
    return case


def analyst_records(case_id):
    """Review row (or None), checklist state {item_id: bool}, notes and activity rows for one case."""
    out = case_dirs(case_id)[1]
    review = next((r for r in read_output("case_review", out) if r["case_id"] == case_id), None)
    checked = {r["item_id"]: r["checked"] == "true" for r in read_output("case_checklist", out) if r["case_id"] == case_id}
    notes = [r for r in read_output("case_notes", out) if r["case_id"] == case_id]
    activity = [r for r in read_output("case_activity", out) if r["case_id"] == case_id]
    return review, checked, notes, activity


# ---------------------------------------------------------------- live session

LIVE_SCENARIO = "L"          # live case IDs are CASE-L-01, CASE-L-02, ...
LIVE_RUN_ID = "RUN-LIVE"
LIVE_TASK_WINDOW = timedelta(hours=8)
LIVE_VERIFICATION_NOTE = "SIMULATED \u2013 not cryptographic"
LIVE_ACTION_TYPES = ("web_read", "tool_call")
LIVE_SOURCE_TYPES = ("external", "agent")


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class LiveSession:
    """A live, human-driven session for the presenter's simulator.

    Tasks, agent actions and payments arrive one at a time instead of from data/seed, but every payment goes
    through exactly the replay's per-transaction logic: apply_controls() for card controls and apply_monitoring()
    (via monitor()) for agent monitoring, with one card ledger and one monitor state for the whole session.
    Timestamps come from the real UTC clock, because a person drives the session; every method accepts a
    timestamp override so tests can use fixed times. Everything is persisted to its own directory (data/live),
    never data/seed, data/output or tests/.
    """

    def __init__(self, directory=None, agent_id="AG-101"):
        self.directory = directory or LIVE_DIR
        self.agent_id = agent_id
        self.policy = load_policy(agent_id)
        self.merchants = load_merchants(agent_id)
        self.baseline = history_baseline()
        self.reset()

    def reset(self):
        """Clear the session and its files."""
        os.makedirs(self.directory, exist_ok=True)
        for name, header in LIVE_SCHEMAS.items():
            _write_rows(output_path(name, self.directory), [header], "w")
        self.tasks, self.actions, self.events = [], [], []
        self.controls = ControlState()
        self.monitor_state = MonitorState(LIVE_RUN_ID, LIVE_SCENARIO)

    # ---- inputs

    def _stamp(self, timestamp):
        at = timestamp or utc_now()
        parse_ts(at)  # validates the format
        return at

    def create_task(self, fields, timestamp=None):
        """Record an owner task. fields: approved_merchant, max_amount_per_payment, permitted_payment_count,
        reference, and optionally valid_from, valid_to (default now to now + 8 hours) and verified_source."""
        at = self._stamp(timestamp)
        verified = fields.get("verified_source", True) is not False
        row = {
            "task_id": f"LT-{len(self.tasks) + 1:03d}", "agent_id": self.agent_id,
            "approved_merchant": fields["approved_merchant"],
            "max_amount_per_payment": money(to_pence(str(fields["max_amount_per_payment"]))),
            "permitted_payment_count": str(int(fields["permitted_payment_count"])),
            "reference": fields["reference"],
            "valid_from": self._stamp(fields.get("valid_from")) if fields.get("valid_from") else at,
            "valid_to": (self._stamp(fields["valid_to"]) if fields.get("valid_to")
                         else (parse_ts(at) + LIVE_TASK_WINDOW).strftime("%Y-%m-%dT%H:%M:%SZ")),
            "verified_source": "true" if verified else "false",
            "verification_note": LIVE_VERIFICATION_NOTE,
        }
        self.tasks.append(row)
        append_output("owner_tasks", row, self.directory)
        count = int(row["permitted_payment_count"])
        instruction = (f"Pay {row['approved_merchant']} for {row['reference']}, max \u00a3{row['max_amount_per_payment']}"
                       f"{'' if count == 1 else f', up to {count} payments'}")
        # A verified task comes from the owner; an unverified one reached the agent some other way.
        self._add_action(row["task_id"], at, "task_received", "owner" if verified else "agent",
                         instruction if verified else f"Unverified request: {instruction}", row["approved_merchant"])
        return row

    def record_action(self, fields, timestamp=None):
        """Record something the agent did, e.g. read a web page. fields: action_type, source_type, excerpt and
        optionally task_id and referenced_merchant."""
        at = self._stamp(timestamp)
        return self._add_action(fields.get("task_id") or "", at, fields["action_type"], fields["source_type"],
                                fields["excerpt"], fields.get("referenced_merchant") or "")

    def _add_action(self, task_id, at, action_type, source_type, excerpt, merchant="", txn_id=""):
        row = {"action_id": f"LA-{len(self.actions) + 1:04d}", "scenario_id": LIVE_SCENARIO, "agent_id": self.agent_id,
               "task_id": task_id, "timestamp": at, "action_type": action_type, "source_type": source_type,
               "excerpt": excerpt, "referenced_merchant": merchant, "related_txn_id": txn_id}
        self.actions.append(row)
        append_output("agent_actions", row, self.directory)
        return row

    def process_payment(self, fields, timestamp=None):
        """Card controls then agent monitoring for one payment, exactly as in a replay. fields: merchant, amount,
        reference and optionally task_id (empty for no task). Returns an event shaped like a replay event."""
        at = self._stamp(timestamp)
        txn = {"txn_id": f"LTX-{len(self.events) + 1:04d}", "scenario_id": LIVE_SCENARIO, "agent_id": self.agent_id,
               "task_id": fields.get("task_id") or "", "merchant": fields["merchant"],
               "amount": money(to_pence(str(fields["amount"]))), "currency": "GBP", "timestamp": at,
               "reference": fields["reference"]}
        self._add_action(txn["task_id"], at, "payment_initiated", "agent",
                         f"Paying {txn['merchant']} {txn['amount']} for {txn['reference']}", txn["merchant"], txn["txn_id"])
        append_output("authorisations", txn, self.directory)

        decision, rule = apply_controls(txn, self.policy, self.merchants, self.controls)
        append_output("card_control_results", {"run_id": LIVE_RUN_ID, "txn_id": txn["txn_id"], "decision": decision,
                                               "rule_triggered": rule}, self.directory)
        event = {
            "run_id": LIVE_RUN_ID, "scenario_id": LIVE_SCENARIO, "txn_id": txn["txn_id"], "agent_id": self.agent_id,
            "timestamp": at, "merchant": txn["merchant"], "amount": txn["amount"], "task_id": txn["task_id"],
            "reference": txn["reference"], "card_decision": decision, "rule_triggered": rule, "monitoring": None,
        }
        event["monitoring"] = monitor(event, self.monitor_state, self.context(), write=False)
        self._write_monitoring(event)
        self.events.append(event)
        return event

    def context(self):
        return build_context(self.tasks, self.actions, self.baseline)

    def _write_monitoring(self, event):
        m = event["monitoring"]
        append_output("monitoring_results", {"run_id": LIVE_RUN_ID, "txn_id": event["txn_id"],
                                             "classification": m["classification"], "signals": m["signals"],
                                             "case_id": m["case_id"]}, self.directory)
        # Keep analyst review statuses: the monitor state only knows the status a case opened with.
        statuses = {r["case_id"]: r["status"] for r in read_output("cases", self.directory)}
        rows = [dict(r, status=statuses.get(r["case_id"], r["status"])) for r in case_rows(self.monitor_state)]
        rewrite_output("cases", rows, self.directory)
        rewrite_output("case_evidence", evidence_rows(self.monitor_state), self.directory)

    def case_ids(self):
        return {c["case_id"] for c in self.monitor_state.cases.values()}


# ---------------------------------------------------------------- CLI

def format_event(e):
    line = f"{e['timestamp']}  {e['txn_id']:<8} {e['merchant']:<12} {e['amount']:>7}  {e['card_decision']:<8}"
    if e["monitoring"] is not None:
        line += f"  {e['monitoring']['classification']:<6} {e['monitoring']['case_id']}"
    if e["rule_triggered"]:
        line += f"  {e['rule_triggered']}"
    return line.rstrip()


def main(argv=None):
    parser = argparse.ArgumentParser(description="AG-101 Agent Spend Monitor replay engine")
    sub = parser.add_subparsers(dest="command", required=True)
    p_replay = sub.add_parser("replay", help="Replay one scenario")
    p_replay.add_argument("scenario_id", choices=SCENARIO_IDS)
    p_replay.add_argument("--mode", choices=MODES, default="controls_only")
    p_all = sub.add_parser("replay-all", help="Replay every scenario in order")
    p_all.add_argument("--mode", choices=MODES, default="controls_only")
    sub.add_parser("reset", help="Clear output CSVs to headers only")
    args = parser.parse_args(argv)

    if args.command == "replay":
        for event in replay(args.scenario_id, args.mode):
            print(format_event(event))
    elif args.command == "replay-all":
        current = None
        for event in replay_all(args.mode):
            if event["scenario_id"] != current:
                current = event["scenario_id"]
                print(f"--- {event['run_id']}")
            print(format_event(event))
    else:
        reset()
        print("Output CSVs reset to headers only.")


if __name__ == "__main__":
    sys.exit(main())
