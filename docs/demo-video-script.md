# Demo video script — 3 minutes max (judges stop watching at 3:00)

## ⛔ The governing rule (Participant Guide §4)

The video must **only highlight features, code, and functionality built
during the Hackathon** (Oct 26 – Nov 4). Failure to clearly identify your
original contributions = immediate disqualification at judges' discretion.
So this script demos ONLY the three event-window features below. The
pre-existing foundation (synthetic world, reconcile engine, dashboard
shell) appears only as the frame, and the video states that plainly.

Record terminal + dashboard in one continuous take if possible. No music,
no trademarked assets.

## On-screen list (show at 0:00 and again at 2:30)

> **Built during this hackathon:**
> 1. Live Meta Model API investigation (muse-spark-1.3, api mode)
> 2. Multimodal pallet-label vision — label_contradiction as a real catch
> 3. Api-mode evaluation + token/spend tracking
>
> Foundation from before the event: synthetic ERP/WMS world, deterministic
> reconcile engine, dashboard shell.

## 0:00–0:15 — Hook + transparency line
"Phantom Inventory Hunter finds ERP↔warehouse inventory mismatches. What
you're about to see is what I built during this hackathon: live Meta AI
investigation and label vision, on top of a synthetic world I built
before the event."
[Show the on-screen list.]

## 0:15–1:00 — Feature 1: live Meta Model API investigation
"First: the agent now investigates with a real Meta model. Watch the mode
flag — api, not fallback — and the token log."
[Run `make agent` in api mode on the rack-14 case. Pause on: root cause
expired_available, the evidence trail, `mode: api`, and
`data/token_usage.jsonl` showing real tokens against the $150 budget.
Say: "The case is synthetic; the investigation running here is new."]

## 1:00–1:50 — Feature 2: multimodal label vision (the new catch)
"Second, and this is the one I'm proudest of: the agent can now READ
pallet labels. Before this week, a label that contradicted the system
was invisible to the pipeline. Now the model reads the image and flags
it."
[Show a contradictory label pair: system says lot X, label says lot Y.
Run the label investigation; pause on the model's read of the image and
the label_contradiction verdict with its evidence.]

## 1:50–2:30 — Feature 3: api-mode evaluation + dashboard
"Third: everything is scored in api mode — accuracy against injected
ground truth, plus token spend. Here's the dashboard on api-mode
investigations."
[Show the Evaluation tab: accuracy + per-category bars. Show the detail
drawer: evidence trail + label image + proposed fix + Approve. Click
Approve once, on camera.]

## 2:30–3:00 — Close: theme + recap
"This is Build for Your World: I integrate Dynamics 365 with an automated
warehouse for a living, and this is the mismatch hunt I do by hand —
now done by an agent that explains itself and never applies a fix
without a human. Built during this hackathon: live Meta Model API
investigation, multimodal label vision, and api-mode evaluation. One
command to run it: make agent."
[End on the on-screen list.]
