# Submission writeup (draft — finalize Nov 3)

## Title
**Phantom Inventory Hunter** — a long-running AI agent that finds and explains
ERP↔WMS inventory mismatches, before they cost you $48K.

## The problem
In food & dairy manufacturing, the ERP (e.g., Microsoft Dynamics 365) and the
warehouse management system driving the automated storage/retrieval system
each keep their own inventory records. They drift apart — failed integration
messages, duplicate postings, wrong units of measure, mislabeled pallets,
timing gaps — and analysts trace every mismatch by hand, hours per case.
I'm an IT Business Analyst who integrates Dynamics 365 with a Mecalux-style
ASRS warehouse. I live this problem.

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
- Reasoning: **Muse Spark** via the Meta Model API — smallest model for
  routine investigations, larger for hard cases (vision, high dollar risk).
- The agent drives a tool loop (ERP/WMS/log/label reads) and synthesizes
  conclusions as structured JSON: root cause, confidence, evidence, fix.
- Responses cached; every token logged against a **$150 budget** (reference
  demo spend: $0.00 on the rule-based fallback path).
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
