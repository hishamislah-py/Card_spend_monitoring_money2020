# AG-101 Agent Spend Monitor (POC)

Replays synthetic AI-agent card payments through (1) simulated card controls and
(2) an advisory agent-intent monitoring layer, with AI-written case explanations.
All data is fictional and synthetic.

## Quick start

```
python generate_data.py            # (re)create the seed CSVs
set GROQ_API_KEY=...               # PowerShell: $env:GROQ_API_KEY = "..."
python ai.py check                 # verify the key and model
python ai.py warm                  # pre-generate AI text for the demo cases
python server.py --port 8000       # open http://127.0.0.1:8000/
python -m unittest discover -s tests
```

Other entry points: `python engine.py replay S2 --mode controls_plus_monitoring`,
`python engine.py replay-all`, `python engine.py reset`.

## How it fits together

| Layer | Module | What it decides |
| --- | --- | --- |
| Card controls | `engine.evaluate` | Merchant allowlist, max per payment, daily cap, hourly count. Knows nothing about tasks. |
| Agent monitoring | `engine.assess` | Compares each payment with the owner task (merchant, amount, window, reference, count) and with the agent's history. Advisory only. |
| AI assist | `ai.py` | Explains cases the rules have already decided. Decides nothing. |

The server (`server.py`) is a thin JSON/SSE API over the engine and serves the UI in `ui/`.

## The console (`ui/index.html`)

A single self-contained page (HTML, CSS and vanilla JavaScript; no frameworks, CDNs, web fonts or remote
images) served by `server.py` at `/`. All logic stays on the server; the page only displays and calls the API.

- **Payments and alerts**: one table, one row per payment: the live session's payments (newest at the top as the
  simulator makes them) and every scenario's payments from `/api/alerts`, which computes them in memory without
  replaying or touching `data/output`. Columns: Txn, Merchant, Amount, Reference, Task, Card controls, Agent
  monitoring (kept separate), Alert (a neutral reference such as `ALT-1001`, linking to the alert), Status and Time
  ("just now", "2 min ago", "3 days ago", with the exact UTC time underneath). Filter by All, High, Review, Open
  alerts or merchant; sort by Amount, Agent monitoring, Status or Time (newest first by default). New live alerts also pop up as a toast. Opening an alert
  from a scenario that isn't the latest replay first replays that scenario instantly, then opens its case page.
- **Case detail** (`#case/CASE-S8-01`, titled with its alert reference, "← Back to alerts"): header, the
  rule-based reason, and two tabs kept in the hash so back/forward work.
  - **Overview** (`#case/CASE-S8-01`): the AI summary panel (label "AI-generated"; no provider or model name is shown; summary,
    up to three key points, footer "AI text explains the case; it does not affect classification."), then the
    authorised task vs actual activity, signals, payments, evidence with AI assessment chips, and the
    recommended action.
  - **Analyst** (`#case/CASE-S8-01/analyst`): when any alert's tab opens, an AI recommendation fills in the whole
    review decision (status, disposition and a draft note, prompt version `review-suggest-v2`), with each filled
    field tagged "AI-filled";
    nothing is saved until the analyst presses Save decision, and the saved record notes that the decision was
    AI-suggested and confirmed by the analyst. Review decision (Open, In review, Reviewed, Escalated, Dismissed;
    a disposition is required for Reviewed, Escalated and Dismissed, and a note of at least 10 characters for
    Escalated and Dismissed), a review checklist generated from the signals by fixed rules, "Ask AI about this
    alert" (three suggested questions plus free text, answers can be added to notes), notes, an activity trail
    and the alert facts.

On load the page fills itself from `/api/feed`, `/api/overview` and `/api/cases`, so a refresh keeps the last run.
Below 1280 px the right column stacks under the feed.

**Demo check**

1. S1 → 1 payment, approved and normal; "No cases opened in this run."
2. S2 → card controls approve all 8; agent monitoring is HIGH from TX-2002; one case, CASE-S2-01
   (8 payments, £320.00), with an AI summary.
3. S3 → Merchant mismatch; the external evidence carries an AI assessment chip.
4. S4 → 8 fast payments, all normal; no cases.
5. S5 → REVIEW, "No verified owner task linked".
6. S6–S9 → amount over task, outside task window, reference mismatch, task unverified.
7. S10 → three cases from five payments. S11–S16 → mixed days across four merchants (ToolCloud, MetricsLane,
   DocuForge, SeatPilot) raising 15 more alerts: over limit, wrong supplier, duplicates, split payments,
   early or late payments, unverified tasks and payments with no task.
8. Reset during a replay → the feed clears and the page notes that the replay was stopped.

## Live demo

Live mode triggers alerts as things happen, driven by a presenter from a separate Simulator page. The scenario
replay mode, its data and its tests are unchanged.

1. Start the server: `python server.py --port 8000`.
2. Open two windows side by side:
   - **http://localhost:8000/simulator**: you play the agent's owner and the AI agent.
   - **http://localhost:8000/**: the analyst dashboard. It shows the scenario alerts and the live session together;
     the pill in the top bar shows "Live · connected".
3. In the simulator, create a task (supplier, max per payment, number of payments allowed, reference).
4. Click the quick actions and watch the dashboard: live payments are added at the top of the feed, and live alerts
   are added to the alert queue (with a pop-up) as they open or grow. Times show as "just now", "2 min ago",
   "3 days ago" and so on, with the exact UTC time underneath.
   - **Pay as asked** → normal. **Pay again** → High (count exceeded, duplicate reference).
   - **Pay 5 times fast** → High on a task that allows one payment, all normal on a task that allows five.
   - **Pay over the limit**, **Pay wrong supplier**, **Pay wrong reference** → High.
   - **Read a tricky webpage, then pay** → High, with the webpage attached as evidence.
   - **Pay without a task** → Review. **Pay unknown supplier** ("CloudDesk") → declined by card controls.
5. Open an alert: case details, the AI summary (written once payments settle) and the Analyst tab all work for live
   alerts. **Reset live session** in the simulator clears everything.

How it works: `engine.LiveSession` sends every payment through exactly the replay's per-transaction logic
(`apply_controls()` and `apply_monitoring()`), with one card ledger and one monitor state for the session. The rules
are the replay's, so several payments on one task group into one alert, which updates as more arrive. Live times
come from the real UTC clock. Everything is written to `data/live/` (never `data/seed` or `data/output`), and a
fresh live session starts each time the server starts. Live alerts are numbered ALT-2001, ALT-2002, … and live
case IDs are `CASE-L-01`, `CASE-L-02`, ….

Endpoints (every response has `"simulation": true` and `"mode": "live"`): `POST /api/live/tasks`,
`POST /api/live/actions`, `POST /api/live/payments`, `GET /api/live/state`, `POST /api/live/reset` and
`GET /api/live/events` (Server-Sent Events: `task_created`, `action_recorded`, `payment`, `alert_opened`,
`alert_updated`, `ai_ready`, `reset`, with a heartbeat comment every 15 seconds).

## Analyst review

Analyst actions change review records only; they never change a payment, a card decision or a monitoring result.
They are human actions, so they are stamped with real wall-clock time, while the cases come from the simulated
replay clock. Records live in four extra files in `data/output/`, cleared by Reset (and at the start of every
replay, since a replay replaces the cases) but never written by a replay:

| File | Columns |
| --- | --- |
| `case_review.csv` | case_id, status, disposition, updated_at |
| `case_notes.csv` | note_id, case_id, created_at, author, text, source (analyst or ai_answer) |
| `case_checklist.csv` | case_id, item_id, checked, updated_at |
| `case_activity.csv` | activity_id, case_id, at, kind, detail |

Endpoints (409 while a replay is streaming, 404 for an unknown case): `GET /api/cases/{id}/analyst`,
`POST /api/cases/{id}/review`, `POST /api/cases/{id}/checklist`, `POST /api/cases/{id}/notes` and
`POST /api/cases/{id}/ai/ask` and `POST /api/cases/{id}/ai/suggest-review` (suggests only; saves nothing).

## AI assist

AI assist is a required feature. It uses the Groq API to:

1. write a plain-English summary for every case,
2. assess each piece of external content the agent read (for example a web page) for possible
   instructions aimed at the agent, and
3. answer an analyst's question about one alert ("Ask AI about this alert", prompt version `ask-v1`), using
   only that case's data, with external excerpts wrapped in `<external_content>` tags as untrusted data.
   Answers get the same validation as summaries (at most 4 sentences and 600 characters, banned words,
   hallucination guard) and are cached per question, so suggested questions are instant on repeat.

**Configuration**

Put your settings in a `.env` file in the project folder (copy `.env.example`):

```
GROQ_API_KEY=gsk_your_key_here
GROQ_MODEL=openai/gpt-oss-120b
```

`.env` is git-ignored. `server.py` and `ai.py` load it on start. A variable that is already set in
the environment takes priority over the same name in `.env`.

| Variable | Default | Notes |
| --- | --- | --- |
| `GROQ_API_KEY` | none, required | `server.py` refuses to start without it. Never printed or cached. |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Any chat model from the [Groq model catalog](https://console.groq.com/docs/models). |
| `AI_TIMEOUT_S` | `15` | Per-request timeout in seconds. |

**Before every demo**

```
python ai.py check   # sends one tiny request; prints OK and the model, or the error
python ai.py warm    # replays every alerting scenario (all but S1 and S4), generates summaries, review
                     # recommendations and answers to every suggested question, and caches all AI text, then resets
python ai.py warm --only recommendations   # just one kind: summaries | recommendations | questions
```

After `warm`, a live demo makes no API calls: results come from `data/ai_cache/`.
The cache key covers the feature, prompt version, model and the stable case facts, so
changing a case's analyst status does not invalidate it, but changing the model or prompt does.
`python ai.py status` shows whether a key is present, the model and the cache size;
`python ai.py clear-cache` empties the cache (`engine.reset()` never touches it).

**What AI output can and cannot do**

- AI text is explanatory only. It **never** affects card decisions, monitoring classification,
  signals, severity, case grouping or anything in `data/output/`.
- The rule-based reason is always shown next to the AI text, and AI text is labelled "AI-generated".
- Every answer is validated before use: JSON shape and length, banned wording, and a hallucination
  guard (every £ amount, transaction ID, task ID and reference must appear in the case data).
  An invalid answer is retried once; after that the case shows a fallback reason
  (`timeout`, `rate_limited`, `api_error` or `invalid_output`) and a Retry button.
- External content is passed to the model as untrusted data inside `<external_content>` tags.
  Its assessment is supporting context only.
- Only synthetic data is sent. Real customer data would need a privacy/security review before
  being sent to any external model provider.
