# Submission writeup (draft — finalize Nov 3)

## Title
**Phantom Inventory Hunter** — a long-running AI agent that finds and explains
ERP↔WMS inventory mismatches, before they cost you $48K.

## Theme
**Build for Your World** — bring Meta's models into a domain you know
firsthand. I'm an IT Business Analyst who integrates Dynamics 365 with a
Mecalux-style ASRS warehouse. This is the mismatch hunt I do by hand.

## What was built during the hackathon (Oct 26 – Nov 4) — the submission
1. **Live Meta Model API investigation** — the agent investigates with
   muse-spark-1.3 in api mode: real tool-loop reasoning, real token
   spend logged against the $150 budget (see `data/token_usage.jsonl`).
   Verified Oct 26: 2/2 sample investigations concluded in pure `api`
   mode. A robustness fix was part of the work: the live model answers
   with prose and prose-prefixed JSON, so the loop now extracts the
   JSON object instead of discarding the reply, and the final round
   forces a conclusion.
2. **Multimodal pallet-label vision** — the agent reads label images
   through the API, making `label_contradiction` a real catch for the
   first time; previously it was engine-invisible by design. Verified
   Oct 26: 2/2 injected contradictions caught with exact field values
   (lot_code and qty cases), plus a clean label correctly matched.
3. **Api-mode evaluation + dashboard refresh** — accuracy scored against
   injected ground truth in api mode, dashboard refreshed on api-mode
   investigations. Verified Oct 26: 10/10 correct, accuracy 1.0, across
   four root-cause categories, $0.1511 spend for the run. Screenshots:
   `docs/dash-api-summary.png`, `docs/dash-api-eval.png`,
   `docs/dash-api-queue.png`.

## Foundation from before the event (NOT claimed as hackathon work)
Synthetic ERP/WMS world generator, deterministic reconcile engine,
dashboard shell, approval queue, rule-based fallback investigation path.
The demo video highlights only the three items above.

## The problem
In food & dairy manufacturing, the ERP (e.g., Microsoft Dynamics 365) and the
warehouse management system driving the automated storage/retrieval system
each keep their own inventory records. They drift apart — failed integration
messages, duplicate postings, wrong units of measure, mislabeled pallets,
timing gaps — and analysts trace every mismatch by hand, hours per case.
I live this problem.

## What it does
Phantom reconciles both systems deterministically, then an AI agent
investigates every mismatch like an analyst would: it queries ERP and WMS
transactions, searches the integration message log, and reads pallet-label
images, building an evidence trail that ends in a root cause, a confidence
score, and a proposed fix. The agent **never applies fixes** — everything
waits in a human approval queue. It runs continuously, prioritizes by dollar
value × expiry risk, groups repeat failures, and even escalates on its own:
a "timing gap" whose message never arrives becomes a failed delivery without
anyone touching it.

## How we built it (Meta Model API)
- Reasoning: **Muse Spark 1.3** via the Meta Model API for every
  investigation step. The code has a hard-case route, but it currently
  resolves to the same model, so no larger model is claimed.
- The agent drives a tool loop (ERP/WMS/log/label reads) and synthesizes
  conclusions as structured JSON: root cause, confidence, evidence, fix.
- Responses cached; every token logged against a **$150 budget**.
- Bonus fit: **Best Agentic Use-Case** — the agent works autonomously
  across multi-step workflows, makes decisions under uncertainty, and
  never applies a fix without human approval.
- Stack: Python, SQLite, plain HTML/JS dashboard. One command to run:
  `make showcase`.

## The demo moment
$47,999.98 of Micellar Casein. The ERP says it's available. It expired
yesterday in rack 14. The engine flags it in seconds; the agent traces it,
proposes the write-off, and a human approves — business tables untouched.

## What's hard about this
The reconciliation is deterministic, but *diagnosis* isn't: the same
quantity mismatch can mean four different root causes, and only the
integration log + posting forensics disambiguate them. The agent has to do
real investigative work, weigh evidence, and know when it's unsure —
while never taking a destructive action on its own.

## What's next
Real deployment against a D365 + ASRS integration, alerting into the
analysts' existing queue, and learning failure patterns across sites.
