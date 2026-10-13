# Demo video script — 3 minutes max (judges stop watching at 3:00)

Record terminal + dashboard in one continuous take if possible. No music,
no trademarked assets. Script is timed to `make showcase` + dashboard.

## 0:00–0:20 — The hook (dashboard, discrepancy table)
"Forty-eight thousand dollars of product. The ERP says it's available.
It expired yesterday, sitting in rack 14. Nobody noticed — until Phantom did."
[Show the dashboard: $486K at risk, the expired_available row at top.]

## 0:20–0:50 — The world + the catch (terminal: `make showcase`, Acts 1–2)
"Phantom Inventory Hunter watches the gap between an ERP and the automated
warehouse. It builds a synthetic world — 200 SKUs, 30 days — then reconciles
every lot deterministically."
[Run it; pause on the reconcile output: ERP 4,379.56 AVAILABLE vs WMS
4,379.56 in rack 14, $47,999.98 at risk.]

## 0:50–1:40 — The investigation (terminal: Act 3)
"The engine flags; the agent investigates. It queries ERP postings, WMS
pallets, the integration log — then concludes: expired lot, 95% confidence,
with the evidence trail and a proposed write-off."
[Scroll the evidence lines slowly.]

## 1:40–2:10 — The human stays in charge (dashboard: detail drawer)
"The agent never applies fixes. Everything waits in an approval queue.
Here's the evidence, the pallet label, the proposed fix — one click to
approve." [Click into the row, show the drawer, click Approve.]

## 2:10–2:40 — It's long-running (terminal: `make loop`, 3 ticks)
"It doesn't stop. Every day it streams new activity, re-reconciles,
prioritizes by dollars times expiry risk, and groups repeat failures.
Watch a stale timing-gap message escalate into a failed delivery on its own."

## 2:40–3:00 — Close (evaluation tab)
"Every diagnosis is scored against injected ground truth: 100% root-cause
accuracy. Built with Muse Spark on the Meta Model API — smallest model for
routine cases, larger for the hard ones — with every token logged against
a $150 budget. One command to run it all: make showcase."
[End on the Evaluation tab: 100.0%, per-category bars.]
