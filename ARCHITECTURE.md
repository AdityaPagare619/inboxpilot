# InboxPilot — Architecture (v0.1)

**Product:** confidence-gated email triage for small-business founders drowning in mail.
**Wedge (from research, not vibes):** NOT a generic "smart inbox" — that's demo #47, crowded, and Gmail/Outlook bundle "good enough" triage free. InboxPilot is a **founder "never-miss P0" guardrail + confidence-gated triage**. We compete on *decisions* (triage, routing, urgency), never on summarization (table stakes at $0 marginal).
**Model:** BYOK — user's own `TYPESAFE_API_KEY`. Free-first; inference ~$2/user/year (math in §9).

---

## 1. Pipeline

```
Gmail (read-only) ──▶ ingest ──▶ state shaping ──▶ Jev: ONE systemone call,
                                                        3 parallel questions
                                                              │
                                                     ┌────────┴────────┐
                                              high confidence      low / ambiguous
                                              + clear urgency           │
                                                     │            MORNING DIGEST
                                              auto-label            (suggested actions,
                                              (Gmail labels)         one-tap approve)
                                                     │                  │
                                                     └──────▶ local audit log ◀─┘
                                                              │
                                                     user corrections ──▶ threshold tuner
```

One Jev call per email. Questions are evaluated in parallel and **in isolation** — they cannot see each other's answers, so all cascade logic lives in our code.

---

## 2. The Jev question design (the core)

**Design law (Inbox Zero's honest failure, production-proven):** Jev "could not reliably separate overlapping secondary rules from explicit negative instructions." Therefore: every Choice option set is **small, clean, mutually exclusive**. Overlapping/ambiguous cases **escalate with suggestions — never guess.**

Per email, one call, three atomic gut-checks:

| qid | type | semantics |
|---|---|---|
| `urgency` | Noul | "Does this email need the founder's attention within 24h?" → p ∈ [0,1] |
| `category` | Choice (5 options, one-line descriptions — bare labels fail, descriptions fix them) | see below |
| `needs_reply` | Noul | "Is this thread awaiting the recipient's response?" → p ∈ [0,1] |

**Category options (mutually exclusive by construction):**
- `needs_action` — "Requires the recipient to do something: reply, decide, approve, pay, or sign."
- `fyi` — "Informational only. No action needed, but worth knowing."
- `receipt` — "Transactional record: receipts, order confirmations, notifications of already-completed actions."
- `newsletter` — "Bulk or marketing content: newsletters, promotions, announcements."
- `noise` — "Spam-like, irrelevant, or safe to ignore entirely."

**Deliberately NOT asked of Jev:** sender importance, delegation target, thread summarization — computed deterministically in code (contacts list, thread metadata) or left to the digest. Multi-factor judgments are decomposed; Jev gets one atomic gut-check per question.

**State shaping** (kept small — cost and latency): subject, sender name+domain, date, first ~500 chars of body text, thread context (message count, who last wrote, days since last reply), plus code-computed signals *prepended as facts* ("sender is in contacts: yes", "you replied in this thread: no"). Target ≤1,500 tokens/email. No attachments in v0.1 (text extraction deferred — noted honestly).

---

## 3. Escalation policy (honest-failure-driven)

Asymmetric stakes (research: a missed critical email is a five-to-seven-figure event; **one miss destroys trust permanently, a thousand correct archives buy nothing**; false-negative cost ≈ 100–1,000× false-positive):

- **Auto-label** (apply Gmail label) ONLY when ALL hold: category confidence ≥ `τ_cat` (default 0.85), urgency is decisive (p ≤ 0.25 or p ≥ 0.75), and top-2 category probabilities differ by ≥ `δ` (default 0.15 — the ambiguity margin).
- **Auto-archive** (noise only) ONLY at `confidence ≥ τ_noise` (default 0.95) AND urgency p < 0.3. Archiving is the most dangerous action; the bar is the highest.
- **Everything else → morning digest** with the model's suggested action and one-tap approve. Uncertainty is a first-class output, not an error.
- **Hard guardrails (non-negotiable):** never auto-archive anything with urgency p ≥ 0.3. Never auto-send. Never act on `noise` when the sender is in contacts (contradiction → digest).
- **Non-determinism note:** Jev flips 1.3–2.2% of answers on identical repeats (no seed param). We never present a decision as certain; the digest shows confidence; the audit log records the resolved model version per decision.

## 4. Threshold tuner

Cold start uses the conservative defaults above (more digest, less auto-action — safe by construction). As the user corrects labels (one tap in digest/CLI), corrections accumulate in the local store; the tuner refits `τ_cat`, `τ_noise`, `δ`, and the urgency cutoffs to maximize expected utility under the asymmetric cost ratio, and shows a **before/after backtest on the user's own history** — the trust-bootstrapping mechanism from the research. Research says 50–300 own labels for stable thresholds; the tuner reports its own label count and confidence honestly ("tuned on 34 of your corrections — still conservative").

## 5. Gmail ingestion & the scary-scopes story

- **v0.1 read path:** `gmail.readonly` only — list inbox, fetch metadata + snippet + body. Triage + digest work fully read-only.
- **Write path:** `gmail.modify` is requested **only** when the user explicitly enables auto-label, with a plain-language explanation of why. Labels are applied, never deletions.
- **OAuth (self-hosted BYOK):** the user creates their own Google Cloud project (README walks through it, ~10 min); localhost OAuth callback; tokens stored locally, file perms 600. For personal/internal use this needs **no Google verification**.
- **Honest moat note (in README):** `gmail.readonly` is a Google *restricted* scope — shipping InboxPilot as a public multi-tenant SaaS would require OAuth verification + annual CASA assessment (five figures + weeks). That's a real moat against fast followers *and* a real cost to us later. v0.1 sidesteps it by being self-hosted.
- **Push:** v0.1 polls (`inboxpilot run`, cron-friendly). Gmail Pub/Sub push deferred to v0.2 — stated, not silently missing.

## 6. Privacy & data flow (plain language, in README too)

- Email text sent to Jev = sent to TypeSafe AI, **US-only hosting**, vague retention ("as long as reasonably necessary"), **no training on inputs** (their privacy policy), zero-retention available enterprise-only (not on our tier). Users deserve this in one paragraph before connecting anything.
- Local-first: labels, thresholds, corrections, audit log stay in local SQLite. Nothing else leaves the machine.
- MCA note: TypeSafe's terms forbid distilling Jev outputs into our own model — we don't; we store *decisions*, not training data.

## 7. Module map

```
src/inboxpilot/
  jev_client.py    # System-One wire client: env key, retries (429/529 + retry-after),
                   # User-Agent set (urllib default gets 403), model pinned to jev-1.13.0,
                   # + MockSystemOneClient with scripted responses for tests/demo
  gmail_client.py  # read-only ingestion, OAuth flow, label application (gated),
                   # + fixture inbox (JSON) so demo/tests run keyless
  triage.py        # question builders, state shaping, gating + escalation policy
  tuner.py         # threshold fitting from corrections + backtest report
  digest.py        # morning digest rendering (CLI/Markdown; HTML later)
  store.py         # SQLite: emails, decisions, labels, corrections, audit
  cli.py           # `inboxpilot run|digest|tune|demo`
  web.py           # minimal UI (after CLI proves the loop)
tests/             # unit + golden tests against the mock; no network in tests
docs/              # demo script, scope setup guide
```

## 8. The fun (this one earns love)

- Morning digest with personality: "☕ Good morning. 47 emails arrived overnight. 3 need you. 41 handled. 3 want your call." — never cutesy about the 3 that need you.
- `inboxpilot demo` runs the full loop on a fixture founder-inbox in under 5 minutes, **zero keys, zero network** — README-driven virality.
- "P0 streak": days since a truly urgent email went unactioned. Founders love streaks.
- Copy rule: the product is confident about what it did, humble about what it didn't. Every auto-action is undoable and logged.

## 9. Cost math (in README, worked)

120 emails/day × ~1,500 tokens × $0.042/M ≈ **$0.0076/day ≈ $2.77/user/year**. Output tokens free. Inference is never the constraint — trust is.

## 10. Honest limitations (v0.1)

- English-first (Jev's best language); other languages handled "but not equally well."
- No attachment/invite parsing yet; no calendar-aware urgency yet (both in v0.2).
- Thresholds start conservative → digest-heavy first week. That's the safe trade, stated up front.
- TypeSafe is 2.5 weeks old: no SLA, dynamic rate limits — client retries with backoff and degrades to "digest everything" (fail-safe) on sustained 529s.
- We do not solve Inbox Zero's hard case (overlapping enterprise rules) — we **design around it** via the escalation policy. Claiming otherwise would be lying.
