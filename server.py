"""Thin HTTP API over engine.py for the AG-101 Agent Spend Monitor POC.

Standard library only. No business logic: every result comes from engine
functions and is only joined and shaped into JSON here. Card controls and
agent monitoring are always reported as separate layers ("card_controls" and
"agent_monitoring"). All data is simulated.
"""

import argparse
import json
import mimetypes
import os
import queue
import sys
import threading
import time
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import ai
import engine

UI_DIR = os.path.join(engine.ROOT, "ui")
ANALYST_ROUTES = (["analyst"], ["review"], ["checklist"], ["notes"], ["ai", "ask"], ["ai", "suggest-review"])
NOTE_SOURCES = ("analyst", "ai_answer", "ai_suggestion")
AGENT_ID = "AG-101"
HISTORY_DAYS = 14
MAX_DELAY_MS = 3000
LIVE_HEARTBEAT_S = 15       # comment line keeping each live event stream open
LIVE_AI_DELAY_S = 2.0       # wait for a burst of payments to settle before (re)writing an alert's AI summary
LIVE_RECENT_PAYMENTS = 50
LIVE_REF_BASE = 2000        # live alerts are ALT-2001, ALT-2002, ... (replay alerts are ALT-1001 ...)
DEFAULT_DELAY_MS = 600


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class AppState:
    """Shared server state: one replay at a time, and serialised access to output files."""

    def __init__(self, ai_service):
        self.replay_lock = threading.Lock()  # held for the whole of a stream
        self.io_lock = threading.Lock()      # held around each engine step and each output read
        self.stop = threading.Event()        # asks a running stream to end early
        self.ai = ai_service
        self.live = LiveHub(self)

    def start_ai(self, case_ids):
        """Start AI generation for a finished run's cases in the background."""
        epoch = self.ai.epoch

        def run():
            for case_id in case_ids:
                try:
                    with self.io_lock:
                        detail = case_detail(case_id)
                except ApiError:
                    continue
                self.ai.ensure(case_id, detail, epoch)

        threading.Thread(target=run, daemon=True).start()


# ---------------------------------------------------------------- shaping

def transaction_json(txn, run_id, decision, rule, monitoring):
    return {
        "run_id": run_id, "scenario_id": txn["scenario_id"], "txn_id": txn["txn_id"],
        "timestamp": txn["timestamp"], "agent_id": txn["agent_id"], "merchant": txn["merchant"],
        "amount": txn["amount"], "task_id": txn["task_id"], "reference": txn["reference"],
        "card_controls": {"decision": decision, "rule_triggered": rule},
        "agent_monitoring": None if monitoring is None else {
            "classification": monitoring["classification"],
            "signals": monitoring["signals"].split(";") if monitoring["signals"] else [],
            "case_id": monitoring["case_id"],
        },
    }


def event_json(event):
    return transaction_json(event, event["run_id"], event["card_decision"], event["rule_triggered"],
                            event["monitoring"])


def load_feed(seed_dir=engine.SEED_DIR, out_dir=engine.OUTPUT_DIR):
    auths = {r["txn_id"]: r for r in engine.read_seed("authorisations", seed_dir)}
    monitoring = {r["txn_id"]: r for r in engine.read_output("monitoring_results", out_dir)}
    return [transaction_json(auths[c["txn_id"]], c["run_id"], c["decision"], c["rule_triggered"],
                             monitoring.get(c["txn_id"]))
            for c in engine.read_output("card_control_results", out_dir)]


def case_summary(case, refs, merchants):
    keys = ("case_id", "scenario_id", "agent_id", "task_id", "severity", "case_type", "reason", "status",
            "txn_count", "total_amount", "opened_at", "updated_at")
    return dict({k: case[k] for k in keys}, **display_fields(case["case_id"], refs, merchants))


def display_fields(case_id, refs, merchants):
    """Production-style fields for showing a case: a neutral alert reference and the merchant paid."""
    return {"alert_ref": refs.get(case_id, case_id), "merchant": merchants.get(case_id, "")}


def case_merchants(payments):
    """case_id -> merchant(s) of the payments flagged on that case, joined with ", " when they differ.

    Accepts feed rows (agent_monitoring) or engine events (monitoring).
    """
    found = defaultdict(dict)
    for p in payments:
        m = p.get("agent_monitoring", p.get("monitoring"))
        if m and m["case_id"]:
            found[m["case_id"]][p["merchant"]] = None
    return {case_id: ", ".join(names) for case_id, names in found.items()}


def simulate_all(context=None):
    """(events, cases) for every scenario, run in memory with monitoring on; data/output is not touched."""
    context = context or engine.load_context()
    runs = [engine.simulate_with_cases(s, context) for s in engine.SCENARIO_IDS]
    return [e for events, _ in runs for e in events], [c for _, cases in runs for c in cases]


def alert_refs(all_cases):
    """case_id -> "ALT-1001"... numbered by (opened_at, case_id) across every scenario's simulated cases, so a
    case keeps the same reference whichever scenario was replayed last."""
    ordered = sorted(all_cases, key=lambda c: (c["opened_at"], c["case_id"]))
    return {c["case_id"]: f"ALT-{1001 + i:04d}" for i, c in enumerate(ordered)}


def task_json(row):
    return dict(row, verified_source=row["verified_source"] == "true")


def case_detail(case_id):
    seed_dir, out_dir = engine.case_dirs(case_id)
    case = next((c for c in engine.read_output("cases", out_dir) if c["case_id"] == case_id), None)
    if case is None:
        raise ApiError(404, f"Case {case_id} not found")
    feed = load_feed(seed_dir, out_dir)
    task_rows = engine.read_seed("owner_tasks", seed_dir)
    task = next((t for t in task_rows if case["task_id"] and t["task_id"] == case["task_id"]), None)

    def on_case(f):
        return f["agent_monitoring"] is not None and f["agent_monitoring"]["case_id"] == case_id

    activity = [f for f in feed if f["task_id"] == case["task_id"]] if task else [f for f in feed if on_case(f)]
    fired = {s for f in feed if on_case(f) for s in f["agent_monitoring"]["signals"]}
    signals = [s for s in engine.SIGNAL_ORDER if s in fired]

    mismatched = set()
    if task is not None:
        for s in signals:
            mismatched.update(engine.SIGNAL_TASK_FIELDS.get(s, []))
    mismatched_fields = [k for k in task_rows[0] if k in mismatched] if task_rows else []

    actions = {a["action_id"]: a for a in engine.read_seed("agent_actions", seed_dir)}
    evidence = []
    for e in engine.read_output("case_evidence", out_dir):
        if e["case_id"] != case_id:
            continue
        a = actions[e["action_id"]]
        evidence.append({"action_id": a["action_id"], "timestamp": a["timestamp"], "action_type": a["action_type"],
                         "source_type": a["source_type"], "excerpt": a["excerpt"],
                         "evidence_label": e["evidence_label"]})
    evidence.sort(key=lambda e: (e["timestamp"], e["action_id"]))

    return {
        "case": case,
        "authorised_task": task_json(task) if task else None,
        "actual_activity": activity,
        "mismatched_fields": mismatched_fields,
        "signals": [{"code": s, "description": engine.SIGNAL_DESCRIPTIONS[s]} for s in signals],
        "evidence": evidence,
        "recommended_action": case["recommended_action"],
    }


def overview():
    feed = [f for f in load_feed() if f["agent_id"] == AGENT_ID]
    cases = engine.read_output("cases")
    policy = next(p for p in engine.read_seed("policy") if p["agent_id"] == AGENT_ID)

    spend_by_date = defaultdict(int)
    for f in feed:
        spend_by_date[f["timestamp"][:10]] += engine.to_pence(f["amount"])
    decisions = Counter(f["card_controls"]["decision"] for f in feed)
    monitored = [f["agent_monitoring"] for f in feed if f["agent_monitoring"] is not None]
    classes = Counter(m["classification"] for m in monitored)
    signal_counts = Counter(s for m in monitored for s in m["signals"])

    history = [h for h in engine.read_seed("agent_history") if h["agent_id"] == AGENT_ID]
    daily = defaultdict(lambda: [0, 0])
    for h in history:
        day = daily[h["timestamp"][:10]]
        day[0] += 1
        day[1] += engine.to_pence(h["amount"])
    history_daily = []
    if history:
        first = engine.parse_ts(min(h["timestamp"] for h in history)).date()
        for i in range(HISTORY_DAYS):
            d = (first + timedelta(days=i)).isoformat()
            count, amount = daily.get(d, (0, 0))
            history_daily.append({"date": d, "count": count, "amount": engine.money(amount)})

    return {
        "agent_id": AGENT_ID,
        "total_payments": len(feed),
        "total_spend": engine.money(sum(spend_by_date.values())),
        "daily_cap": policy["daily_cap"],
        "spend_by_date": {d: engine.money(p) for d, p in sorted(spend_by_date.items())},
        "card_controls": {"approved": decisions[engine.APPROVED], "declined": decisions[engine.DECLINED]},
        "agent_monitoring": {
            "normal": classes[engine.NORMAL], "high": classes[engine.HIGH], "review": classes[engine.REVIEW],
            "open_cases": sum(1 for c in cases if c["status"] == "OPEN"),
        },
        "signal_counts": {s: signal_counts[s] for s in engine.SIGNAL_ORDER},
        "history_daily": history_daily,
    }


def all_alerts():
    """(alerts, payments) for every scenario, computed in memory with monitoring on; data/output is not touched.

    The latest replay's cases come from cases.csv instead, so their analyst review status is current. Payments are
    every scenario's payments, in the same shape as the feed, so the dashboard can list each with its alert.
    """
    events, cases = simulate_all()
    refs, merchants = alert_refs(cases), case_merchants(events)
    live = {c["case_id"]: c for c in engine.read_output("cases")}
    alerts = [dict(case_summary(live.get(c["case_id"], c), refs, merchants), live=c["case_id"] in live) for c in cases]
    return alerts, [event_json(e) for e in events]


def live_display(case_id=None):
    """(refs, merchants) for decorating cases: the latest replay's, or the live session's for a CASE-L-.. case."""
    if case_id and engine.is_live_case(case_id):
        return live_refs(), case_merchants(load_feed(engine.LIVE_DIR, engine.LIVE_DIR))
    _, cases = simulate_all()
    return alert_refs(cases), case_merchants(load_feed())


def live_refs():
    """CASE-L-01 -> ALT-2001: live alerts are numbered in the order they open."""
    return {c["case_id"]: f"ALT-{LIVE_REF_BASE + int(c['case_id'].rsplit('-', 1)[1]):04d}"
            for c in engine.read_output("cases", engine.LIVE_DIR)}


# ---------------------------------------------------------------- analyst review

def engine_case(case_id):
    """The case row from cases.csv with its display fields (alert_ref, merchant)."""
    case = next(c for c in engine.read_output("cases", engine.case_dirs(case_id)[1]) if c["case_id"] == case_id)
    refs, merchants = live_display(case_id)
    return dict(case, **display_fields(case_id, refs, merchants))


def now_utc():
    """Real wall-clock time for analyst actions. They are human actions, not part of the simulated replay clock."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def analyst_view(case_id):
    """Review record, checklist, notes, activity and suggested questions for one case of the latest run."""
    detail = case_detail(case_id)  # 404 for an unknown case
    case = detail["case"]
    codes = {s["code"] for s in detail["signals"]}
    review, checked, notes, activity = engine.analyst_records(case_id)
    review = dict(review or {"case_id": case_id, "disposition": "", "updated_at": ""}, status=case["status"])
    opened = {"activity_id": "A-0000", "case_id": case_id, "at": case["opened_at"], "kind": "case_opened",
              "detail": case["reason"]}
    return {
        "review": review,
        "dispositions": engine.DISPOSITIONS,
        "checklist": [{"item_id": i, "text": t, "checked": checked.get(i, False)} for i, t in engine.checklist_items(codes)],
        "notes": sorted(notes, key=lambda n: (n["created_at"], n["note_id"]), reverse=True),
        "activity": sorted(activity + [opened], key=lambda a: (a["at"], a["activity_id"]), reverse=True),
        "suggested_questions": engine.suggested_questions(codes),
    }


def _text(body, field, low, high, label):
    value = body.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        return ""
    if not isinstance(value, str):
        raise ApiError(400, f"{label} must be text")
    value = value.strip()
    if not low <= len(value) <= high:
        raise ApiError(400, f"{label} must be {low}–{high} characters")
    return value


def validate_review(body):
    """(status, disposition, note) from a review request, or ApiError 400 with a clear message."""
    status = body.get("status")
    if status not in engine.CASE_STATUSES:
        raise ApiError(400, f"Invalid status {status!r}; expected one of {list(engine.CASE_STATUSES)}")
    disposition = body.get("disposition") or ""
    if disposition and disposition not in engine.DISPOSITIONS:
        raise ApiError(400, f"Invalid disposition {disposition!r}; expected one of {list(engine.DISPOSITIONS)}")
    if status in engine.DISPOSITION_REQUIRED and not disposition:
        raise ApiError(400, f"A disposition is required to mark a case {status.replace('_', ' ').lower()}")
    if status in engine.NOTE_REQUIRED:
        note = _text(body, "note", engine.NOTE_REQUIRED_MIN, engine.NOTE_MAX, "The note")
        if not note:
            raise ApiError(400, f"A note of at least {engine.NOTE_REQUIRED_MIN} characters is required to mark a case "
                                f"{status.lower()}")
    else:
        note = _text(body, "note", 1, engine.NOTE_MAX, "The note")
    return status, disposition, note


def log_ai_ready(case_id, view):
    """Record "AI summary generated" in the case activity once, the first time the summary is seen ready."""
    if not view or view["ai_status"] != "ready" or not view["summary"]:
        return
    if any(a["case_id"] == case_id and a["kind"] == "ai_summary"
           for a in engine.read_output("case_activity", engine.case_dirs(case_id)[1])):
        return
    engine.log_activity(case_id, now_utc(), "ai_summary", f"Groq · {view['summary']['model']}")


def compare(scenario_id):
    context = engine.load_context()
    controls = engine.simulate(scenario_id, "controls_only", context)
    monitored = engine.simulate(scenario_id, "controls_plus_monitoring", context)

    def card_counts(events):
        d = Counter(e["card_decision"] for e in events)
        return {"approved": d[engine.APPROVED], "declined": d[engine.DECLINED]}

    classes = Counter(e["monitoring"]["classification"] for e in monitored)
    return {
        "scenario_id": scenario_id,
        "controls_only": dict(card_counts(controls), cases=0),
        "controls_plus_monitoring": dict(
            card_counts(monitored), normal=classes[engine.NORMAL], high=classes[engine.HIGH],
            review=classes[engine.REVIEW],
            cases=len({e["monitoring"]["case_id"] for e in monitored if e["monitoring"]["case_id"]})),
        "per_transaction": [{"txn_id": c["txn_id"], "card_decision": c["card_decision"],
                             "monitoring_classification": m["monitoring"]["classification"]}
                            for c, m in zip(controls, monitored)],
    }


# ---------------------------------------------------------------- HTTP

def _scenario_param(query):
    scenario_id = query.get("scenario", [""])[0]
    if scenario_id not in engine.SCENARIO_IDS:
        raise ApiError(400, f"Unknown scenario {scenario_id!r}; expected one of {engine.SCENARIO_IDS}")
    return scenario_id


class Handler(BaseHTTPRequestHandler):
    server_version = "AG101SpendMonitor/0.1"

    @property
    def app(self):
        return self.server.app

    def log_message(self, fmt, *args):
        if not getattr(self.server, "quiet", False):
            super().log_message(fmt, *args)

    # ---- responses

    def send_json(self, status, payload):
        body = json.dumps(dict(payload, simulation=True), ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_sse(self, event, payload):
        data = json.dumps(dict(payload, simulation=True), ensure_ascii=False)
        self.wfile.write(f"event: {event}\ndata: {data}\n\n".encode("utf-8"))
        self.wfile.flush()

    def read_json_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, UnicodeDecodeError):
            raise ApiError(400, "Request body must be JSON")

    # ---- dispatch

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def _dispatch(self, method):
        url = urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        query = parse_qs(url.query)
        try:
            if not parts or parts[0] != "api":
                if method != "GET":
                    raise ApiError(404, "Not found")
                return self.serve_static(url.path)
            route = parts[1:]
            if method == "GET" and route == ["replay", "stream"]:
                return self.stream(query)
            if method == "GET" and route == ["live", "events"]:
                return self.live_events()
            payload = self.route_api(method, route, query)
            self.send_json(200, payload)
        except ApiError as e:
            self.send_json(e.status, {"error": str(e)})

    def route_api(self, method, route, query):
        app = self.app
        if route and route[0] == "live":
            return dict(self.live_route(method, route[1:]), mode="live")
        if method == "GET" and route == ["scenarios"]:
            return {"scenarios": engine.read_seed("scenarios")}
        if method == "POST" and route == ["reset"]:
            app.stop.set()
            with app.replay_lock:
                with app.io_lock:
                    engine.reset()
                app.ai.reset()
                app.stop.clear()
            return {"reset": True}
        if len(route) >= 3 and route[0] == "cases" and route[2:] in ANALYST_ROUTES:
            return self.analyst_route(method, route[1], route[2:])
        if len(route) >= 3 and route[0] == "cases" and route[2] == "ai":
            # Read case facts under the short lock, then release it before any call to the model.
            with app.io_lock:
                detail = case_detail(route[1])
            if method == "GET" and len(route) == 3:
                view = app.ai.view(route[1]) or app.ai.ensure(route[1], detail)
            elif method == "POST" and route[3:] == ["retry"]:
                view = app.ai.retry(route[1], detail)
            else:
                raise ApiError(404, "Not found")
            with app.io_lock:
                log_ai_ready(route[1], view)
            return view
        if method == "GET" and route == ["feed"]:
            with app.io_lock:
                return {"transactions": load_feed()}
        if method == "GET" and route == ["cases"]:
            with app.io_lock:
                refs, merchants = live_display()
                return {"cases": [case_summary(c, refs, merchants) for c in engine.read_output("cases")]}
        if method == "GET" and len(route) == 2 and route[0] == "cases":
            with app.io_lock:
                detail = case_detail(route[1])
                refs, merchants = live_display(route[1])
            return dict(detail, case=dict(detail["case"], **display_fields(route[1], refs, merchants)))
        if method == "POST" and len(route) == 3 and route[0] == "cases" and route[2] == "status":
            status = self.read_json_body().get("status")
            if status not in engine.CASE_STATUSES:
                raise ApiError(400, f"Invalid status {status!r}; expected one of {list(engine.CASE_STATUSES)}")
            guard = replay_guard(app, route[1])
            try:
                with app.io_lock:
                    previous = next((c["status"] for c in engine.read_output("cases", engine.case_dirs(route[1])[1])
                                     if c["case_id"] == route[1]), None)
                    case = engine.update_case_status(route[1], status)
                    if case is not None:
                        engine.log_activity(route[1], now_utc(), "status_changed", f"{previous} → {status}")
            finally:
                guard.release()
            if case is None:
                raise ApiError(404, f"Case {route[1]} not found")
            with app.io_lock:
                refs, merchants = live_display(route[1])
            return {"case": dict(case, **display_fields(route[1], refs, merchants))}
        if method == "GET" and route == ["overview"]:
            with app.io_lock:
                payload = overview()
            payload["ai"] = {"provider": "groq", "model": app.ai.model}
            return payload
        if method == "GET" and route == ["compare"]:
            return compare(_scenario_param(query))
        if method == "GET" and route == ["alerts"]:
            with app.io_lock:
                alerts, payments = all_alerts()
                return {"alerts": alerts, "payments": payments}
        raise ApiError(404, "Not found")

    def analyst_route(self, method, case_id, action):
        """Analyst review endpoints. They change review records only, never payments, and are paused (409) while a
        replay streams, because a replay replaces the cases they refer to."""
        app = self.app
        body = self.read_json_body() if method == "POST" else {}
        guard = replay_guard(app, case_id)
        try:
            if method == "GET" and action == ["analyst"]:
                with app.io_lock:
                    return analyst_view(case_id)
            if method != "POST" or action == ["analyst"]:
                raise ApiError(404, "Not found")
            if action == ["ai", "ask"]:
                return self.ask(case_id, body)
            if action == ["ai", "suggest-review"]:
                return self.suggest_review(case_id)
            with app.io_lock:
                case = case_detail(case_id)["case"]  # 404 for an unknown case
                at = now_utc()
                if action == ["review"]:
                    status, disposition, note = validate_review(body)
                    note_source = body.get("note_source") or "analyst"
                    if note_source not in NOTE_SOURCES:
                        raise ApiError(400, f"note_source must be one of {', '.join(NOTE_SOURCES)}")
                    engine.save_review(case_id, status, disposition, at)
                    if note:
                        engine.add_note(case_id, at, note, note_source)
                        engine.log_activity(case_id, at, "note_added",
                                            ("From AI suggestion: " if note_source == "ai_suggestion" else "") + note)
                    label = engine.DISPOSITIONS.get(disposition)
                    engine.log_activity(case_id, at, "status_changed",
                                        f"{case['status']} → {status}" + (f" · {label}" if label else "")
                                        + (" · AI-suggested, confirmed by analyst" if body.get("ai_suggested") is True else ""))
                elif action == ["checklist"]:
                    items = dict(engine.checklist_items({s["code"] for s in case_detail(case_id)["signals"]}))
                    item_id, checked = body.get("item_id"), body.get("checked")
                    if item_id not in items:
                        raise ApiError(400, f"Unknown checklist item {item_id!r} for {case_id}")
                    if not isinstance(checked, bool):
                        raise ApiError(400, "checked must be true or false")
                    engine.set_checklist_item(case_id, item_id, checked, at)
                    engine.log_activity(case_id, at, "checklist", f"{'Ticked' if checked else 'Unticked'}: {items[item_id]}")
                elif action == ["notes"]:
                    text = _text(body, "text", 1, engine.NOTE_MAX, "The note")
                    if not text:
                        raise ApiError(400, f"The note must be 1–{engine.NOTE_MAX} characters")
                    source = body.get("source") or "analyst"
                    if source not in NOTE_SOURCES:
                        raise ApiError(400, f"source must be one of {', '.join(NOTE_SOURCES)}")
                    engine.add_note(case_id, at, text, source)
                    engine.log_activity(case_id, at, "note_added", ("From AI answer: " if source == "ai_answer" else "") + text)
                return dict(analyst_view(case_id), case=engine_case(case_id))
        finally:
            guard.release()

    def ask(self, case_id, body):
        """Answer an analyst question with AI. Case facts are read under the short lock; the model call is made
        without it (the replay lock, already held, keeps the case from being replaced meanwhile)."""
        question = body.get("question")
        if not isinstance(question, str) or not 1 <= len(ai.normalise_question(question)) <= ai.QUESTION_MAX:
            raise ApiError(400, f"The question must be 1–{ai.QUESTION_MAX} characters")
        question = ai.normalise_question(question)
        with self.app.io_lock:
            detail = case_detail(case_id)
        try:
            result = self.app.ai.ask(detail, question)
            payload = {"answer": result["answer"], "model": result["model"], "cached": result["cached"]}
        except ai.AIError as e:
            payload = {"fallback_reason": e.reason, "model": self.app.ai.model}
        with self.app.io_lock:
            engine.log_activity(case_id, now_utc(), "ai_question", question)
        return dict(payload, question=question)

    def suggest_review(self, case_id):
        """AI-suggested review decision for the analyst to check. Nothing is saved: the analyst confirms it with
        POST /review. Logged once per case in the activity trail."""
        with self.app.io_lock:
            detail = case_detail(case_id)
        try:
            result = self.app.ai.suggest_review(detail)
            payload = {k: result[k] for k in ("status", "disposition", "note", "rationale", "model", "cached")}
        except ai.AIError as e:
            return {"fallback_reason": e.reason, "model": self.app.ai.model}
        with self.app.io_lock:
            activity = engine.read_output("case_activity", engine.case_dirs(case_id)[1])
            if not any(a["case_id"] == case_id and a["kind"] == "ai_suggestion" for a in activity):
                label = engine.DISPOSITIONS.get(payload["disposition"])
                engine.log_activity(case_id, now_utc(), "ai_suggestion",
                                    payload["status"] + (f" · {label}" if label else ""))
        return payload

    # ---- live mode

    def live_route(self, method, route):
        """Live session endpoints for the simulator page. Each step runs under one live lock and is broadcast to
        every connected dashboard."""
        app, hub = self.app, self.app.live
        if method == "GET" and route == ["state"]:
            hub.session  # starts the session (and data/live) on first use
            with app.io_lock:
                return live_state()
        if method != "POST":
            raise ApiError(404, "Not found")
        if route == ["reset"]:
            hub.reset()
            return {"reset": True}
        body = self.read_json_body()
        if not isinstance(body, dict):
            raise ApiError(400, "Request body must be a JSON object")
        if route == ["tasks"]:
            fields = validate_live_task(body)
            with hub.lock, app.io_lock:
                task = live_task_json(hub.session.create_task(fields), 0)
            hub.broadcast("task_created", {"task": task})
            return {"task": task}
        if route == ["actions"]:
            with hub.lock:
                fields = validate_live_action(body, {t["task_id"] for t in hub.session.tasks})
                with app.io_lock:
                    action = hub.session.record_action(fields)
            hub.broadcast("action_recorded", {"action": action})
            return {"action": action}
        if route == ["payments"]:
            fields = validate_live_payment(body)
            with hub.lock, app.io_lock:
                known = hub.session.case_ids()
                payment = event_json(hub.session.process_payment(fields))
                case_id = payment["agent_monitoring"]["case_id"]
                alert = None
                if case_id:
                    refs, merchants = live_display(case_id)
                    row = next(c for c in engine.read_output("cases", engine.LIVE_DIR) if c["case_id"] == case_id)
                    alert = {"change": "updated" if case_id in known else "opened",
                             "case": case_summary(row, refs, merchants)}
            hub.broadcast("payment", {"event": payment})
            if alert:
                hub.broadcast(f"alert_{alert['change']}", {"case": alert["case"]})
                hub.schedule_ai(case_id)
            return dict(payment, alert=alert)
        raise ApiError(404, "Not found")

    def live_events(self):
        """Server-Sent Events for dashboards: every live step, plus a heartbeat comment every 15 seconds."""
        hub = self.app.live
        q = hub.subscribe()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    event, payload = q.get(timeout=LIVE_HEARTBEAT_S)
                except queue.Empty:
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                    continue
                self.send_sse(event, dict(payload, mode="live"))
        except OSError:  # the dashboard went away
            pass
        finally:
            hub.unsubscribe(q)

    def stream(self, query):
        scenario_id = _scenario_param(query)
        mode = query.get("mode", ["controls_plus_monitoring"])[0]
        if mode not in engine.MODES:
            raise ApiError(400, f"Unknown mode {mode!r}; expected one of {list(engine.MODES)}")
        try:
            delay_ms = int(query.get("delay_ms", [DEFAULT_DELAY_MS])[0])
        except ValueError:
            raise ApiError(400, "delay_ms must be an integer")
        if not 0 <= delay_ms <= MAX_DELAY_MS:
            raise ApiError(400, f"delay_ms must be between 0 and {MAX_DELAY_MS}")

        app = self.app
        if not app.replay_lock.acquire(blocking=False):
            raise ApiError(409, "A replay is already running")
        app.ai.reset()  # the previous run's cases are replaced by this one
        events = engine.replay(scenario_id, mode)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            run_id, case_ids, count, stopped = f"RUN-{scenario_id}", set(), 0, False
            while True:
                # Pacing is presentation only: the next engine step runs after the wait, unchanged.
                if count and delay_ms and app.stop.wait(delay_ms / 1000):
                    stopped = True
                if stopped or app.stop.is_set():
                    stopped = True
                    break
                with app.io_lock:
                    event = next(events, None)
                if event is None:
                    break
                count += 1
                if event["monitoring"] and event["monitoring"]["case_id"]:
                    case_ids.add(event["monitoring"]["case_id"])
                self.send_sse("transaction", event_json(event))
            if stopped:
                self.send_sse("stopped", {"run_id": run_id, "txn_count": count})
            else:
                self.send_sse("done", {"run_id": run_id, "txn_count": count, "case_ids": sorted(case_ids)})
                app.start_ai(sorted(case_ids))
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        finally:
            events.close()
            app.replay_lock.release()

    def serve_static(self, path):
        rel = path.lstrip("/") or "index.html"
        if rel == "simulator":
            rel = "simulator.html"
        full = os.path.realpath(os.path.join(UI_DIR, rel))
        root = os.path.realpath(UI_DIR)
        tests = os.path.realpath(engine.TESTS_DIR)
        if not full.startswith(root + os.sep) or full.startswith(tests + os.sep) or not os.path.isfile(full):
            raise ApiError(404, "Not found")
        with open(full, "rb") as f:
            body = f.read()
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ---------------------------------------------------------------- live mode

class LiveHub:
    """The live session and the dashboards listening to it.

    One lock serialises live steps (tasks, actions, payments, reset). Events go to every subscriber's queue.
    When an alert opens or grows, its AI summary is (re)written in the background once payments settle, and
    "ai_ready" is broadcast.
    """

    def __init__(self, app):
        self.app = app
        self.lock = threading.Lock()
        self._session = None
        self._subscribers = set()
        self._ai_timers = {}
        self._mutex = threading.Lock()  # guards subscribers and timers

    @property
    def session(self):
        """The live session, started fresh (clearing data/live) on first use after the server starts."""
        with self._mutex:
            if self._session is None:
                self._session = engine.LiveSession()
            return self._session

    def subscribe(self):
        q = queue.Queue()
        with self._mutex:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q):
        with self._mutex:
            self._subscribers.discard(q)

    def broadcast(self, event, payload):
        with self._mutex:
            subscribers = list(self._subscribers)
        for q in subscribers:
            q.put((event, payload))

    def schedule_ai(self, case_id, delay=LIVE_AI_DELAY_S):
        with self._mutex:
            old = self._ai_timers.pop(case_id, None)
            if old:
                old.cancel()
            timer = threading.Timer(delay, self._write_ai, args=(case_id,))
            timer.daemon = True
            self._ai_timers[case_id] = timer
        timer.start()

    def _write_ai(self, case_id):
        app = self.app
        try:
            with app.io_lock:
                detail = case_detail(case_id)
        except ApiError:  # reset meanwhile
            return
        view = app.ai.retry(case_id, detail)  # the case as it is now; cached text comes back at once
        deadline = time.monotonic() + 90
        while view and view["ai_status"] == "pending" and time.monotonic() < deadline:
            time.sleep(0.25)
            view = app.ai.view(case_id)
        try:
            with app.io_lock:
                case_detail(case_id)
                log_ai_ready(case_id, view)
        except ApiError:
            return
        self.broadcast("ai_ready", {"case_id": case_id, "ai_status": view["ai_status"] if view else "failed"})

    def reset(self):
        with self._mutex:
            for timer in self._ai_timers.values():
                timer.cancel()
            self._ai_timers.clear()
        session = self.session
        with self.lock, self.app.io_lock:
            case_ids = session.case_ids()
            session.reset()
        self.app.ai.forget(case_ids)
        self.broadcast("reset", {})


def live_task_json(row, used):
    return dict(task_json(row), payments_used=used)


def live_state():
    """Tasks, the newest payments, alerts and totals of the live session."""
    feed = load_feed(engine.LIVE_DIR, engine.LIVE_DIR)
    used = Counter(f["task_id"] for f in feed if f["task_id"])
    refs, merchants = live_refs(), case_merchants(feed)
    cases = [case_summary(c, refs, merchants) for c in engine.read_output("cases", engine.LIVE_DIR)]
    classes = Counter(f["agent_monitoring"]["classification"] for f in feed if f["agent_monitoring"])
    decisions = Counter(f["card_controls"]["decision"] for f in feed)
    spend = defaultdict(int)
    for f in feed:
        spend[f["timestamp"][:10]] += engine.to_pence(f["amount"])
    policy = next(p for p in engine.read_seed("policy") if p["agent_id"] == AGENT_ID)
    return {
        "tasks": [live_task_json(t, used[t["task_id"]]) for t in engine.read_seed("owner_tasks", engine.LIVE_DIR)],
        "payments": list(reversed(feed))[:LIVE_RECENT_PAYMENTS],
        "cases": sorted(cases, key=lambda c: c["case_id"], reverse=True),
        "totals": {
            "payments": len(feed), "approved": decisions[engine.APPROVED], "declined": decisions[engine.DECLINED],
            "normal": classes[engine.NORMAL], "high": classes[engine.HIGH], "review": classes[engine.REVIEW],
            "alerts": len(cases), "open_cases": sum(1 for c in cases if c["status"] == "OPEN"),
            "spend_by_date": {d: engine.money(p) for d, p in sorted(spend.items())},
            "daily_cap": policy["daily_cap"],
        },
    }


def _text_field(body, field, label, high, required=True):
    value = body.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ApiError(400, f"{label} is required")
        return ""
    if not isinstance(value, str):
        raise ApiError(400, f"{label} must be text")
    value = value.strip()
    if len(value) > high:
        raise ApiError(400, f"{label} must be 1–{high} characters")
    return value


def _amount_field(body, field, label):
    """A pound amount from 0.01 to 10,000.00 with at most two decimals, returned as "40.00"."""
    value = body.get(field)
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ApiError(400, f"{label} must be an amount in pounds, e.g. 40.00")
    if not amount.is_finite() or amount != amount.quantize(Decimal("0.01")):
        raise ApiError(400, f"{label} must be an amount in pounds with at most two decimals")
    if not Decimal("0.01") <= amount <= Decimal("10000.00"):
        raise ApiError(400, f"{label} must be between £0.01 and £10,000.00")
    return f"{amount:.2f}"


def _time_field(body, field, label):
    value = body.get(field)
    if not value:
        return None
    try:
        engine.parse_ts(value)
    except (TypeError, ValueError):
        raise ApiError(400, f"{label} must be a UTC time like 2026-10-30T09:00:00Z")
    return value


def validate_live_task(body):
    try:
        count = int(str(body.get("permitted_payment_count")).strip())
    except ValueError:
        raise ApiError(400, "Number of payments allowed must be a whole number from 1 to 50")
    if not 1 <= count <= 50 or str(body.get("permitted_payment_count")).strip() not in (str(count), f"{count}.0"):
        raise ApiError(400, "Number of payments allowed must be a whole number from 1 to 50")
    verified = body.get("verified_source", True)
    if not isinstance(verified, bool):
        raise ApiError(400, "verified_source must be true or false")
    fields = {
        "approved_merchant": _text_field(body, "approved_merchant", "Supplier", 40),
        "max_amount_per_payment": _amount_field(body, "max_amount_per_payment", "Max per payment"),
        "permitted_payment_count": count,
        "reference": _text_field(body, "reference", "Reference", 30),
        "valid_from": _time_field(body, "valid_from", "valid_from"),
        "valid_to": _time_field(body, "valid_to", "valid_to"),
        "verified_source": verified,
    }
    if fields["valid_from"] and fields["valid_to"] and fields["valid_to"] <= fields["valid_from"]:
        raise ApiError(400, "valid_to must be after valid_from")
    return fields


def validate_live_action(body, task_ids):
    if body.get("action_type") not in engine.LIVE_ACTION_TYPES:
        raise ApiError(400, f"action_type must be one of {', '.join(engine.LIVE_ACTION_TYPES)}")
    if body.get("source_type") not in engine.LIVE_SOURCE_TYPES:
        raise ApiError(400, f"source_type must be one of {', '.join(engine.LIVE_SOURCE_TYPES)}")
    task_id = _text_field(body, "task_id", "task_id", 20, required=False)
    if task_id and task_id not in task_ids:
        raise ApiError(400, f"Unknown task {task_id}")
    return {"action_type": body["action_type"], "source_type": body["source_type"], "task_id": task_id,
            "excerpt": _text_field(body, "excerpt", "Excerpt", 300),
            "referenced_merchant": _text_field(body, "referenced_merchant", "referenced_merchant", 40, required=False)}


def validate_live_payment(body):
    # An unknown task_id is allowed: agent monitoring reports it as TASK_NOT_FOUND.
    return {"merchant": _text_field(body, "merchant", "Supplier", 40),
            "amount": _amount_field(body, "amount", "Amount"),
            "reference": _text_field(body, "reference", "Reference", 30),
            "task_id": _text_field(body, "task_id", "task_id", 20, required=False)}


def replay_guard(app, case_id):
    """Analyst changes to a replay case wait for no replay (409 while one streams); live cases don't depend on it."""
    if engine.is_live_case(case_id):
        lock = threading.Lock()
        lock.acquire()
        return lock
    if not app.replay_lock.acquire(blocking=False):
        raise ApiError(409, "A replay is running; analyst tools are available again when it finishes")
    return app.replay_lock


def make_server(host="127.0.0.1", port=8000, quiet=False, ai_service=None):
    server = ThreadingHTTPServer((host, port), Handler)
    server.app = AppState(ai_service or ai.AIService())
    server.quiet = quiet
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description="AG-101 Agent Spend Monitor API (simulation)")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    ai.load_env_file()
    if not ai.api_key():
        print(ai.MISSING_KEY_MESSAGE, file=sys.stderr)
        sys.exit(1)
    server = make_server(port=args.port)
    print(f"AG-101 Agent Spend Monitor (simulation) on http://127.0.0.1:{server.server_address[1]}/ "
          f"— AI assist: Groq {server.app.ai.model}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
