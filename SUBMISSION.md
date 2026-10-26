# Submission plan — Meta Global AI Developer Hackathon

**Deadline: Nov 4, 2026, 9:00 PM ET.** Plan to submit **Nov 3** — never cut a
hard deadline close. Nov 3 is also the last full day for submission
questions / troubleshooting.

> Governing doc: the **Participant Guide** (received Oct 26, screenshots
> from the signed-in event page). It supersedes the waiver-page read
> below wherever they differ — most importantly on the new-work rule.

## Kickoff reconciliation (2026-10-26 — rules read, gaps flagged)

Source: "Hackathon Terms & Conditions (Official Rules) and Event Waiver"
(Cerebral Valley, dated Oct 25, 2026). The public event page still says
rules "will be published before" kickoff, but the waiver page itself is
the rules text. Approval notice was already in inbox (APPROVED Oct 20);
Oct 26 blasts covered kickoff (12 PM ET / 9 AM PT) and the credit claim.

**Gaps this plan missed — fix before submitting:**

- **Judging weights:** Impact 30%, **Use of Meta AI Tooling 25%**,
  Technical Depth & Execution 20%, Demo 25%. Tooling must go "beyond a
  basic integration" and surface unexpected capabilities — the punch
  list's vision path + tool loop is the evidence, not just a chat call.
  Demo = a working, impressive live demo AND video quality, so the
  dashboard must hold up live, not just on video.
- **Track + theme:** indie developer track, one track per submission.
  Phantom's theme is **Build for Your World** (firsthand D365 + ASRS
  domain) — name it explicitly in `docs/submission-writeup.md`; the
  draft never names a theme.
- **Submission portal:** Cerebral Valley portal at
  `/e/meta-ai-developer-hackathon/hackathon/submit` — not a generic
  "official platform".
- **Credits conditions:** $150, 10-day window, claim by Nov 4, 9 PM ET,
  **each participant claims individually** (no claiming on someone
  else's behalf), distributed in batches, a credit card must be on the
  Meta account before API calls work, Spend Limit notification available
  on Billing. The agent cannot claim or create the key for Mukesh.
- **Ownership / confidentiality:** entrant keeps IP, but organisers get
  a perpetual, irrevocable, royalty-free, non-exclusive licence and
  nothing shared is treated as confidential. Synthetic data only — no
  real client data in the repo or demo.
- **⛔ NEW-WORK-ONLY RULE (Participant Guide §4 — this is now the
  governing constraint, and it is strict):** "What you present at this
  Hackathon must have been built during the event." And: "Your demo
  must only highlight the specific features, code, and functionality
  that you built during the Hackathon. Judges must be able to clearly
  identify what was created during the Hackathon. Failure to clearly
  identify your original contributions will result in immediate
  disqualification at Judges sole discretion." This CORRECTS the
  waiver-page note above (which found no such clause). Consequence:
  the Oct 13 build (M1–M5) is foundation only — it must NOT be the
  demo. The demo video, the writeup, and the submission must
  highlight ONLY the event-window work below, and must explicitly
  label what is new vs pre-existing. Startups may build on existing
  codebases if they clearly identify what's new; as an indie entrant,
  the same transparency is the safe course.
- **Problem statements (resolved):** two themes — **Build for Your
  World** ("bring Meta's models into your domain; solve a problem you
  know firsthand") and Push the Frontier (software/robotics/
  manufacturing/energy/materials). Phantom is **Build for Your World**
  — name it in the writeup and the video.
- **Stage One gate (pass/fail):** the project must reasonably fit the
  theme AND reasonably have used Meta Model API and/or Meta open-weight
  models to build the project *in the Hackathon*. The api-mode work
  below is what passes this gate — a fallback-mode demo would fail it.
- **Prizes (indie track, $400K):** 1st $150K, 2nd $100K, 3rd $75K,
  4th $50K, 5th $25K. Bonus pool $50K: Most Viral $20K (post the demo
  on X, engagement counted until Nov 8 EOD — free to attempt),
  Best Build on Meta Open Weight Models $10K (must run on own hardware
  or partner inference — stretch, see Baseten), Community Vote $10K
  (most votes in the public gallery, one per verified account),
  **Best Agentic Use-Case $5K** (autonomy, decisions, multi-step
  workflows — Phantom's natural bonus; name it in the writeup),
  Best Creative Build $5K (Muse Image / Muse Wonder — weakest fit,
  skip). Most Viral engagement counts likes + reposts + comments
  until Nov 8, 11:59 PM ET.
- **Partner credits (optional stretch):** Baseten $100 (use
  `meta-models/muse-spark-open-1026`, NOT `muse-spark-open`, per the
  guide), Modal $100, Fireworks $25 (shortlist). Baseten is the
  realistic route to the open-weight bonus.
- **Schedule (all ET):** kickoff Mon Oct 26, 12 PM; Agents 101 Tue Oct 27,
  12–1 PM; Agents 102 Wed Oct 28, 12–1 PM; Fireworks Fri Oct 30,
  12–1 PM; office hours weekdays 10–11 AM in Discord #office-hours.
  Building period Oct 27 – Nov 4. Judging Nov 5–8; closing ceremony
  Mon Nov 9, 12 PM (top 5 per track announced, live final-round
  judging); community vote winner Mon Nov 16.
- **Credits claim route (corrected):** the Guide's claim is a Google
  form ("Meta Global AI Hackathon: Model API Credit Claims"), not
  just the event page — use the form linked in the Guide, then check
  the Billing page. Conditions unchanged: individual claim only, card
  required, spend-limit notification available, claim by Nov 4, 9 PM ET.
- **Anti-project list (checked Oct 26):** Phantom clears all ten
  banned categories. Two look adjacent and are addressed in the
  writeup/video framing: (1) "Dashboards as the main feature" — the
  dashboard is a review surface for the agent's work (approval queue),
  not the product; the product is the autonomous investigation, and
  the demo leads with the agent, not the dashboard. (2) "Simple image
  analyzers" — label vision is one evidence tool inside a multi-step
  investigation (ERP + WMS + log + label), not the app itself. The
  other eight (medical advice, basic RAG, Streamlit apps, education
  chatbots, job screeners, nutrition coaches, personality/sports
  analyzers) are unrelated on their face.

**API verification (2026-10-26, no key yet):** base
`https://api.meta.ai/v1`, POST `/chat/completions`, model
`muse-spark-1.3`, Standard pricing $1.25/$4.25 per 1M in/out — all
confirmed against current public docs. No code change needed. SMALL
and LARGE still both default to `muse-spark-1.3` (no distinct large
Muse model published; do NOT switch to the discounted
`muse-spark-1.3-contributor` variant silently — it permits training
use). `make agent` in api mode is UNPROVEN until the key exists:
Oct 26 smoke test without a key printed `mode: fallback`, 2/2
accuracy, $0.00 spend.

## Timeline

| Date | Event |
|---|---|
| Oct 13 | Applications opened (rolling, 20K cap) — apply early |
| Oct 25, 11:59 PM ET | Application deadline |
| Oct 26, 12:00 PM ET | Kickoff livestream (approval already received Oct 20) |
| Oct 27 – Nov 4 | Building period; workshops + weekday office hours 10–11 AM ET |
| Nov 3 | Last full day for submission questions / troubleshooting |
| **Nov 4, 9:00 PM ET** | **Submissions due via CV platform** |
| Nov 5 – 8 | Judging — no action needed, EXCEPT the two audience bonuses: keep pushing the X demo post (Viral counts to Nov 8, 11:59 PM ET) and the gallery vote |
| Nov 9, 12:00 PM ET | Closing ceremony, top 5 per track, winners revealed |
| Nov 16 | Community vote winner announced on Discord |

## ⚠️ The "built during the hackathon" question — RESOLVED BY THE GUIDE

The Guide is explicit (see §4 note above): **demo only what was built
during the event, and identify it clearly, or risk disqualification.**
So the strategy is:

- **Foundation (pre-existing, Oct 13, NOT demoed as new):** synthetic
  world generator, deterministic reconcile engine, dashboard shell,
  approval queue, fallback investigation path.
- **The submission (built Oct 26 – Nov 4, THIS is the demo):** the
  punch list below. Every commit in this window is the evidence.
- **Transparency line (in writeup + video + README):** "Built during
  the hackathon: [punch list]. Foundation from before the event:
  [generator/engine/dashboard shell]." Never let a judge mistake
  foundation for new work, or vice versa.

## Kickoff checklist (Oct 26)

- [ ] Read the official rules when they drop; adjust this plan.
- [ ] Claim the $150 Meta Model API credits; create the API key.
- [ ] Verify the API surface against our adapter (`llm.py` was written from
      public docs as of Oct 13): base URL, `/chat/completions`, model names.
      Confirm the small-vs-large model choice (`META_MODEL_SMALL/LARGE`).
- [ ] `export META_MODEL_API_KEY=...` → `make agent` → confirm `mode: api`
      in the output; check `data/token_usage.jsonl` for real spend.

## 10-day build punch list (THE submission — demo only these)

- [ ] **Live Meta Model API integration**: `make agent` in `api` mode
      (muse-spark-1.3) end to end — real investigations, real token
      log in `data/token_usage.jsonl`, real spend vs the $150 budget.
      Record accuracy + spend in DECISIONS.md. (This is also the
      Stage One gate evidence: Meta tooling used *in* the Hackathon.)
- [ ] **Multimodal vision path**: pallet-label images through the API
      so `label_contradiction` becomes a real catch (today it's
      engine-invisible by design). Demo on 2–3 labels, including one
      contradictory pair. This is the "beyond a basic integration"
      evidence for the 25% tooling criterion.
- [ ] **Api-mode eval + dashboard refresh**: full eval in api mode,
      fresh screenshots against api-mode investigations.
- [ ] **Robustness pass**: prompt/parse fixes the real model exposes.
- [ ] **Submission framing**: README + writeup + video all carry the
      "built during the hackathon" list and the foundation disclaimer.
- [ ] Commit everything Oct 26 – Nov 4 (history is the proof).
- [ ] (Stretch, only if time remains) Baseten muse-spark-open-1026
      route for the $10K open-weight bonus; X post of the demo for
      the $20K Most Viral bonus (engagement counted until Nov 8 EOD).

## Submission checklist

- [ ] Public GitHub repo (create it; push; MIT license already in repo).
- [ ] README carries the "built during the hackathon" list + foundation
      disclaimer; screenshots are api-mode.
- [ ] Demo video ≤ 3 minutes, public (YouTube/Vimeo) — highlights
      ONLY the punch-list features, per Guide §4 — see
      `docs/demo-video-script.md`.
- [ ] Text description names the theme (Build for Your World) and the
      hackathon-built list — see `docs/submission-writeup.md`.
- [ ] Submit via the Cerebral Valley portal by **Nov 3** (buffer day);
      double-check repo public, video link works, all contributors
      listed (solo: just Mukesh).
- [ ] (Free bonus) Post the demo on X after the event; submit the post
      link through the platform for Most Viral.

## Risks

- **Disqualification risk if the demo blurs old vs new work** — the
  video script and writeup are written to prevent exactly this.
- API docs may have shifted since Oct 13 — the adapter is env-configurable
  (`META_MODEL_API_BASE`, `META_MODEL_SMALL/LARGE`) so no code changes
  should be needed, but verify before burning credits.
- Credits are distributed in batches — claim early so the key exists
  well before Nov 3.
