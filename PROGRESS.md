# InboxPilot — Build Progress

**Mission:** confidence-gated email triage for small businesses on TypeSafe Jev. Build #2 of two parallel Jev-product builds (sibling: Sentinel — SRE page-or-suppress). Coordinator reports to Petu; Aditya sees via Petu's briefs.
**Env:** `~/workspace/jev-builds/inboxpilot/` — all work lives here.
**Started:** 2026-10-02 ~13:00 IST. Multi-day build, paced for quality.

## WEB PLATFORM BUILD (Aditya's direct order, 2026-10-03 ~16:11 IST)
- **Directive:** full interactive web platform + Vercel production URL by **22:00 IST Sat 2026-10-03**. Keyless DEMO (fixture inbox + scripted mock-Jev; no keys, no Gmail, no network anywhere in the deployment). CLI product stays intact; web app lives in `web/`.
- **Stack:** React+Vite SPA (web/, built to dist/) + Python serverless functions (web/api/*.py) wrapping the REAL vendored logic (web/lib/inboxpilot/: triage, tuner, jev_client, gmail_client fixture loader — zero re-implementation drift). Session memory is per-instance (ephemeral — UI says so). Deploy: git-based via Vercel MCP (create_deployment w/ gitSource), project root = web/.
- **Lanes (parallel):** backend API (6 endpoints: inbox/explain/correct/tune/audit/cost) · frontend (6 views: dashboard/digest/explorer/tuner-playground/audit/cost+privacy) · coordinator (me): contracts, GitHub repo, Vercel project, integration, QA, deploys.
- **Checkpoints:** preview URL ~18:00 IST → staging ~20:00 → production verified well before 22:00.

## Spec foundation (read)
- [x] Report §1 (exec summary), §5.7 (email field study), §6 (funnel: idea #147 triage copilot PASS)
- [x] `notes/phase1-jev-deepdive.md` — API surface, pricing, 02:20 corrections
- [x] `notes/phase2-community-scan.md` — Inbox Zero honest failure (the design law)

## MVP v0.1 workstreams
| # | Workstream | Owner | Status |
|---|---|---|---|
| 1 | ARCHITECTURE.md (design doc + escalation policy) | coordinator (me) | DONE ~13:15 |
| 2 | System-One wire client + mock + tests | helper A | DONE ~13:25 — verified by coordinator: 30/30 tests pass |
| 3 | Gmail read-only ingestion + OAuth + fixtures | helper B | DONE ~13:27 — verified by coordinator: 56/56 full suite green |
| 4 | Triage engine (classify → gate → auto-label vs digest) | coordinator (me) | DONE — triage.py + store.py, golden tests for every gating branch |
| 5 | Threshold tuner (corrections → tuned thresholds) | coordinator (me) | DONE — asymmetric-cost grid search, honesty floors (<10 refuse, <50 provisional) |
| 6 | CLI, then minimal web UI | coordinator (me) | DONE — full CLI (demo/run/digest/approve/undo/correct/tune/serve); `serve` minimal |
| 7 | README + demo script | coordinator (me) | DONE — README.md with 5-min demo, cost math, honest scopes/privacy/limitations |
| 8 | Git push-ready | coordinator (me) | local repo committed (a0ec7a1); push to AdityaPagare619/inboxpilot BLOCKED on token repo access (Aditya's 30-sec phone step) |

## Key design decisions (from research)
- **Positioning:** NOT a generic "smart inbox" (report verdict: demo #47, crowded, incumbents bundle free). Wedge = founder "never-miss P0" guardrail + confidence-gated triage. Compete on *decisions*, not summarization.
- **Inbox Zero design law:** Jev cannot reliably separate overlapping secondary rules from negative instructions → keep every Choice option set small, clean, mutually exclusive; overlapping/ambiguous cases escalate with suggestions, never guess.
- **Asymmetric stakes:** false-negative cost 100–1,000× false-positive → auto-archive/noise threshold extremely high; default to digest on doubt; never auto-archive P0, never auto-send.
- **Jev ground truth:** `POST /v1/systemone`, Bearer `TYPESAFE_API_KEY`; Choice ≤255 options w/ one-line descriptions (bare labels fail); Noul = single probability, no confidence; questions parallel+isolated (cascade in code); non-deterministic (1.3–2.2% flips, no seed); 64k req / 32k state; dynamic rate limits, no SLA; 429/529 → backoff honoring retry-after; set User-Agent (urllib default gets 403); pin `jev-1.13.0`.
- **Cost:** ~120 emails/day → ~$1.90/user/year inference. Never the constraint; trust is.
- **Gmail scopes:** start `gmail.readonly`; `gmail.modify` only when user enables auto-label. Scary-scopes story documented honestly (restricted scope → verification+CASA for public apps; v0.1 = self-hosted BYOK, user creates own OAuth client, no verification needed for personal use).
- **Privacy:** email content goes to TypeSafe (US-only, vague retention, no training on inputs, zero-retention enterprise-only). Documented in README, plain language.
- **₹0 ops:** no paid services, no external signups; mocks/fixtures for everything touchable; real OAuth client creation is Aditya's call, documented not done.

## Log
- 2026-10-02 ~13:00 — coordinator started; env scaffolded; spec foundation read.
- 2026-10-02 ~13:15 — MILESTONE 1: ARCHITECTURE.md complete (positioning, pipeline, Jev question design, Inbox-Zero-law escalation policy, asymmetric-cost gating, tuner, Gmail scopes + honest CASA note, privacy, cost math, limitations). Helpers A (Jev wire client + mock + tests) and B (Gmail ingestion + OAuth + fixture inbox + setup docs) dispatched in parallel with full briefs. Next: triage engine + tuner (me/helper C) once client interfaces land.
- 2026-10-02 ~13:25 — Helper A DONE: src/inboxpilot/jev_client.py (~460 lines, stdlib only) + 30 tests, all passing — verified by coordinator re-running the suite. Normalized answer shapes per spec, 429/529 backoff honoring Retry-After, typed errors, MockSystemOneClient for keyless tests/demo, cost math matches ARCHITECTURE.md §9 ($2.76/user/yr at 120 emails/day). Notable: no pytest on VM + PEP 668 pip block → stdlib unittest, repo stays dependency-free. Helper B (Gmail) still running. Coordinator to build triage engine + store next against the mock + specified Gmail interface (no need to wait for B's fixtures).
- 2026-10-02 ~13:30 — Helper B DONE: src/inboxpilot/gmail_client.py (~560 lines) — fixture mode (network fully disabled) + real OAuth2 installed-app flow (localhost callback, 0600 token storage, auto-refresh), gmail.modify gated behind enable_write with plain-language explanation, multipart body extraction. tests/fixtures/fixture_inbox.json (25-msg founder inbox, 21 unread, incl. ambiguous thread + contact-as-noise contradiction case) + generator. docs/gmail-setup.md (setup walkthrough + honest restricted-scope/CASA note + test-mode caveats). Verified by coordinator: full suite 56/56 green, fixture sane. Open item (honest): real-mode OAuth paths not live-tested — first human `inboxpilot run` is the live shakedown. Both foundation workstreams complete; coordinator building triage engine + store now.
- 2026-10-02 ~14:00 — MILESTONE 2 (MVP v0.1 COMPLETE): triage.py + store.py (SQLite audit) with golden tests for every escalation branch; tuner.py (asymmetric-cost grid search, refuses <10 labels, provisional <50); digest.py (terminal + minimal HTML); cli.py (demo/run/digest/approve/undo/correct/tune/serve); repo-root ./inboxpilot launcher; README.md. Demo verified end-to-end: 21 triaged -> 13 auto-handled (5 P0, 3 FYI, 2 newsletters, 2 receipts, 1 archived spam), 8 digest. Full suite 82/82 green, stdlib only. Local git committed (a0ec7a1), push-ready for AdityaPagare619/inboxpilot — push BLOCKED on PAT repo access (Aditya's phone step). Real-mode Gmail OAuth untested (needs Aditya's 10-min console setup + first live run).
