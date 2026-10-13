# Submission plan — Meta Global AI Developer Hackathon

**Deadline: Nov 4, 2026, 9:00 PM ET.** Plan to submit **Nov 3** — never cut a
hard deadline close.

> Official rules publish **Oct 26** (kickoff). The checklist below follows the
> standard hackathon pattern (working project + public repo + ≤3-min demo
> video + text description) — confirm against the official rules on Oct 26
> and adjust.

## Timeline

| Date | Event |
|---|---|
| Oct 13 | Applications opened (rolling, 20K cap) — apply early |
| Oct 25, 11:59 PM ET | Application deadline |
| Oct 26, 9:00 AM ET | Approval notices; kickoff livestream; hacking begins |
| Oct 27 – Nov 4 | Live workshops + office hours on Discord |
| **Nov 4, 9:00 PM ET** | **Submissions due** |
| Nov 4 – 8 | Judging |
| Nov 9 | Closing ceremony, winners announced |

## ⚠️ The "built during the hackathon" question

This project is substantially built *before* the event (Oct 13). Most
hackathons require projects to be created — or **significantly updated** —
during the hacking period. The 10-day punch list below is designed to be
genuinely significant new work (real model integration, vision, eval
re-runs), all committed **Oct 26 – Nov 4** so the commit history shows it.
Don't submit the Oct 13 code as-is; do the punch list, then submit.

## Kickoff checklist (Oct 26)

- [ ] Read the official rules when they drop; adjust this plan.
- [ ] Claim the $150 Meta Model API credits; create the API key.
- [ ] Verify the API surface against our adapter (`llm.py` was written from
      public docs as of Oct 13): base URL, `/chat/completions`, model names.
      Confirm the small-vs-large model choice (`META_MODEL_SMALL/LARGE`).
- [ ] `export META_MODEL_API_KEY=...` → `make agent` → confirm `mode: api`
      in the output; check `data/token_usage.jsonl` for real spend.

## 10-day build punch list (the significant new work)

- [ ] **Real-model eval**: re-run the 10-sample investigation + full eval in
      `api` mode; record accuracy and token spend in DECISIONS.md.
- [ ] **Vision path**: wire pallet-label image reading through the API so
      `label_contradiction` becomes a real catch (today it's engine-
      invisible by design). Demo it on 2–3 labels.
- [ ] **Dashboard refresh**: screenshots against api-mode investigations.
- [ ] **Robustness pass**: any prompt/parse fixes the real model exposes.
- [ ] Commit everything Oct 26 – Nov 4 (history matters).

## Submission checklist

- [ ] Public GitHub repo (create it; push; MIT license already in repo).
- [ ] README renders with screenshots (already does).
- [ ] Demo video ≤ 3 minutes, public (YouTube/Vimeo) — see
      `docs/demo-video-script.md`.
- [ ] Text description — draft in `docs/submission-writeup.md`.
- [ ] Submit on the official platform by **Nov 3** (buffer day).

## Risks

- Official rules (Oct 26) may add requirements — re-check this file then.
- API docs may have shifted since Oct 13 — the adapter is env-configurable
  (`META_MODEL_API_BASE`, `META_MODEL_SMALL/LARGE`) so no code changes
  should be needed, but verify before burning credits.
