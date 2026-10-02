# ✈️ InboxPilot

**Confidence-gated email triage for founders drowning in mail — powered by [Jev](https://typesafe.ai) (TypeSafe AI's System One decision model).**

InboxPilot doesn't summarize your inbox. Summarization is table stakes and free everywhere. InboxPilot makes **decisions**: what's urgent, what can wait, what's noise — and it only acts when it's sure. When it isn't sure, you get a morning digest with suggested actions, one tap to approve. **Uncertainty is a first-class output, not an error.**

The core bet: a missed critical email is a five-to-seven-figure event. One miss destroys trust permanently; a thousand correct archives buy nothing. So the system is engineered around **never missing P0** — auto-actions require decisive confidence, doubt goes to the digest, and auto-archive is gated behind near-certainty on provably-calm mail.

## 5-minute demo (zero keys, zero network)

```bash
./inboxpilot demo
```

Runs the full loop — triage 21 emails of a fixture founder inbox, auto-label, archive one crypto spam, and print the morning digest. Nothing leaves your machine.

## How it works

```
Gmail (read-only) → state shaping → ONE Jev call, 3 parallel questions
                                              ↓
                                   ┌──────────┴──────────┐
                              sure enough              unsure
                                   ↓                      ↓
                              auto-label            morning digest
                              / auto-archive        (suggested actions)
```

**The three questions** (one Jev call per email, evaluated in parallel):

| question | type | what it asks |
|---|---|---|
| `urgency` | yes/no + probability | does this need attention within 24h? |
| `category` | pick one of 5 | `needs_action` / `fyi` / `receipt` / `newsletter` / `noise` |
| `needs_reply` | yes/no + probability | is the thread awaiting your reply? |

**The design law** (learned from [Inbox Zero's production Jev integration](https://github.com/elie222/inbox-zero), the most honest data point in the ecosystem): Jev *cannot reliably separate overlapping secondary rules from negative instructions*. So every option set is small, clean, mutually exclusive — and anything ambiguous escalates with suggestions instead of guessing.

**Escalation policy** (defaults; the tuner refits them to you):

- Auto-label only at category confidence ≥ 0.85 **and** decisive urgency.
- Auto-archive (noise only) only at confidence ≥ 0.95 **and** urgency < 0.3.
- Top-two categories within 0.15 of each other → digest ("too close, not guessing").
- **Hard guardrails:** never auto-archive anything possibly urgent. Never auto-send (no send path exists). A "noise" verdict on a sender in your contacts is treated as a contradiction → digest.

## Cost

~120 emails/day → **~$2–3/user/year** in Jev inference ($0.042/M input tokens, output free). Inference was never the constraint — trust is.

## Real usage (BYOK)

1. Get a TypeSafe API key → `export TYPESAFE_API_KEY=...`
2. Gmail setup (10 min, your own OAuth client): [`docs/gmail-setup.md`](docs/gmail-setup.md)
3. `./inboxpilot run --live` — triage your unread mail (read-only by default)
4. `./inboxpilot run --live --auto-label` — also apply labels (asks for `gmail.modify`)
5. `./inboxpilot digest` — the morning digest · `./inboxpilot tune` — refit thresholds from your corrections

**The scary-scopes story, told straight:** `gmail.readonly` is a Google *restricted* scope. For personal/self-hosted use (this repo's model), no verification is needed. Shipping this as a public multi-tenant SaaS would require Google OAuth verification + annual CASA assessment — five figures and weeks. That's a real moat, and a real future cost. We ask for `gmail.modify` only when you explicitly enable auto-label, and we tell you why at the moment we ask.

## Privacy

Email text sent for classification goes to TypeSafe AI: **US-only hosting**, vague retention ("as long as reasonably necessary"), no training on your inputs, zero-retention available on enterprise tiers only. Everything else — your labels, thresholds, corrections, the full decision audit log — stays in a local SQLite database. Read this before connecting a real inbox.

## The threshold tuner

`inboxpilot correct <id> <category> [--urgent|--not-urgent]` records your corrections; `inboxpilot tune` grid-searches thresholds against them under asymmetric costs (a wrongly archived urgent email costs 100× a needless digest entry) and shows a before/after backtest on your own history. Under 10 corrections it refuses to change anything; under 50 it flags the result provisional. Research says 50–300 of your own labels for stable thresholds — the tuner tells you where you stand.

## Honest limitations (v0.1)

- English-first; other languages work "but not equally well" (Jev).
- No attachment or calendar-invite parsing yet; no calendar-aware urgency.
- Jev is non-deterministic (1–2% answer flips on identical repeats, no seed) — the digest shows confidence; nothing is presented as certain.
- TypeSafe is weeks old: no SLA, dynamic rate limits. The client retries with backoff and degrades to "digest everything" on sustained overload.
- We don't solve Inbox Zero's hard case (overlapping enterprise rules) — we design around it via escalation. Claiming otherwise would be lying.

## Roadmap

v0.2: Gmail push (Pub/Sub) instead of polling · calendar-aware urgency · attachment/invite text extraction · polished web UI (`inboxpilot serve` is a minimal start) · live label application for digest approvals.

---

*Built with the Jev research in [`ARCHITECTURE.md`](ARCHITECTURE.md). Honesty first, math first.*
