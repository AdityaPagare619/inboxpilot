"""Triage engine: Jev question design, state shaping, confidence gating.

Implements ARCHITECTURE.md §2–§4. The two laws this module never breaks:

1. Inbox-Zero law: Choice option sets are small, clean, mutually exclusive.
   Overlapping/ambiguous cases escalate to the digest with suggestions — never guess.
2. Asymmetric stakes: a missed urgent email costs 100–1,000× a needless digest
   entry. Auto-actions require decisive confidence; doubt goes to the digest.
   Never auto-archive anything possibly urgent. Never auto-send (no send path exists).
"""

from __future__ import annotations

from typing import Iterable

# ---------------------------------------------------------------------------
# Thresholds (defaults = conservative; tuner.py refits from user corrections)
# ---------------------------------------------------------------------------
DEFAULT_THRESHOLDS = {
    "tau_cat": 0.85,          # min category confidence for auto-label
    "tau_noise": 0.95,        # min confidence for auto-archive (noise only)
    "delta": 0.15,            # min top1-top2 probability margin (ambiguity)
    "urgent_high": 0.75,      # urgency decisive bands
    "urgent_low": 0.25,
    "urgency_archive_max": 0.3,  # never auto-archive at/above this urgency
}

# ---------------------------------------------------------------------------
# Category taxonomy — mutually exclusive by construction (Inbox-Zero law).
# One-line descriptions: bare labels fail, described labels work (37/40).
# ---------------------------------------------------------------------------
CATEGORIES: dict[str, str] = {
    "needs_action": "Requires the recipient to do something: reply, decide, approve, pay, or sign.",
    "fyi": "Informational only. No action needed, but worth knowing.",
    "receipt": "Transactional record: receipts, order confirmations, notifications of already-completed actions.",
    "newsletter": "Bulk or marketing content: newsletters, promotions, announcements.",
    "noise": "Spam-like, irrelevant, or safe to ignore entirely.",
}

# Gmail labels applied on auto-label. Noise is archived, not labeled.
LABELS: dict[tuple[str, bool], str] = {
    ("needs_action", True): "InboxPilot/P0",
    ("needs_action", False): "InboxPilot/Action",
    ("fyi", False): "InboxPilot/FYI",
    ("receipt", False): "InboxPilot/Receipts",
    ("newsletter", False): "InboxPilot/Newsletters",
}

MAX_STATE_CHARS = 6000  # ≈1,500 tokens; keeps cost/latency flat


def build_questions() -> dict:
    """The three atomic gut-checks. One call, evaluated in parallel by Jev."""
    return {
        "urgency": {
            "type": "noul",
            "instructions": (
                "Does this email need the founder's attention within 24 hours? "
                "Yes for: direct requests, escalations, deadlines, money movement, "
                "outages, anything a customer or investor is waiting on. "
                "No for: routine updates, FYIs, receipts, newsletters."
            ),
        },
        "category": {
            "type": "choice",
            "instructions": (
                "Pick the single category that best describes this email. "
                "The categories are mutually exclusive — choose the best fit."
            ),
            "criteria": dict(CATEGORIES),
        },
        "needs_reply": {
            "type": "noul",
            "instructions": (
                "Is this thread awaiting the recipient's response? "
                "Yes if the latest message asks them a question or clearly "
                "expects a reply from them."
            ),
        },
    }


def shape_state(email: dict, contacts: Iterable[str] = ()) -> str:
    """Build the Jev `state` string: facts first, body last, bounded size."""
    contacts_lc = {c.lower() for c in contacts}
    sender = email.get("from", "")
    sender_lc = sender.lower()
    in_contacts = any(c in sender_lc for c in contacts_lc) if contacts_lc else False

    thread_bits = []
    if email.get("thread_n"):
        thread_bits.append(f"{email['thread_n']} messages in thread")
    if email.get("thread_last_from"):
        thread_bits.append(f"last message from: {email['thread_last_from']}")
    if email.get("thread_days_since") is not None:
        thread_bits.append(f"days since their last reply: {email['thread_days_since']}")
    thread_ctx = "; ".join(thread_bits) if thread_bits else "single message (no thread context)"

    body = (email.get("body") or email.get("snippet") or "")[:1200]

    parts = [
        f"From: {sender}",
        f"Subject: {email.get('subject', '')}",
        f"Date: {email.get('date', '')}",
        f"Thread: {thread_ctx}",
        f"Sender is in the recipient's contacts: {'yes' if in_contacts else 'no'}",
        f"You have replied in this thread before: {'yes' if email.get('replied_before') else 'no'}",
        "Body:",
        body,
    ]
    state = "\n".join(parts)
    return state[:MAX_STATE_CHARS]


def _top_two(probs: dict[str, float]) -> tuple[tuple[str, float], tuple[str, float]]:
    ranked = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)
    if len(ranked) == 1:
        return ranked[0], (ranked[0][0], 0.0)
    return ranked[0], ranked[1]


def triage_email(
    jev,
    email: dict,
    contacts: Iterable[str] = (),
    thresholds: dict | None = None,
) -> dict:
    """Classify one email and decide: auto-label, auto-archive, or digest.

    Returns a decision dict with action, label/suggestion, reasons, and the
    raw Jev answers for the audit log. Never raises on low confidence —
    uncertainty becomes a digest entry.
    """
    state = shape_state(email, list(contacts))
    result = jev.decide(state, build_questions())
    return decide_from_answers(
        result.get("answers", {}),
        email,
        contacts,
        thresholds,
        model=result.get("model"),
        usage=result.get("usage", {}),
    )


def decide_from_answers(
    answers: dict,
    email: dict,
    contacts: Iterable[str] = (),
    thresholds: dict | None = None,
    model: str | None = None,
    usage: dict | None = None,
) -> dict:
    """Pure decision function over already-obtained Jev answers.

    Split out so the threshold tuner can re-score stored decisions without
    spending inference. Same contract as triage_email's return value.
    """
    t = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        t.update({k: v for k, v in thresholds.items() if k in t})
    contacts_list = list(contacts)

    urgency_p = float(answers["urgency"]["p"])
    needs_reply_p = float(answers["needs_reply"]["p"])
    cat = answers["category"]
    probs = {k: float(v) for k, v in cat["probabilities"].items()}
    (top1, p1), (top2, p2) = _top_two(probs)
    conf = float(cat["confidence"])

    sender_lc = (email.get("from") or "").lower()
    sender_known = any(c.lower() in sender_lc for c in contacts_list) if contacts_list else False

    urgent = urgency_p >= t["urgent_high"]
    calm = urgency_p <= t["urgent_low"]
    ambiguous = conf < t["tau_cat"] or (p1 - p2) < t["delta"]

    reasons: list[str] = []
    decision: dict = {
        "email_id": email.get("id"),
        "category": top1,
        "category_confidence": conf,
        "category_probs": probs,
        "urgency_p": urgency_p,
        "needs_reply_p": needs_reply_p,
        "model": model,
        "usage": usage or {},
        "reasons": reasons,
    }

    def digest(suggested_action: str, suggested_label: str | None = None) -> dict:
        decision["action"] = "digest"
        decision["label"] = None
        decision["suggested"] = {"action": suggested_action, "label": suggested_label}
        return decision

    # --- Guardrail 1: contradiction — "noise" from a known contact ----------
    if top1 == "noise" and sender_known:
        reasons.append(
            "Classified as noise but the sender is in your contacts — "
            "contradiction, needs your call."
        )
        return digest("review", None)

    # --- Auto-archive: noise only, extreme confidence, provably calm --------
    if (
        top1 == "noise"
        and conf >= t["tau_noise"]
        and urgency_p < t["urgency_archive_max"]
    ):
        reasons.append(
            f"Noise at {conf:.2f} confidence (bar {t['tau_noise']:.2f}), "
            f"urgency {urgency_p:.2f} — safe to archive."
        )
        decision["action"] = "auto_archive"
        decision["label"] = None
        return decision

    # --- Auto-label: decisive category AND decisive urgency ------------------
    if not ambiguous and (urgent or calm):
        if top1 == "needs_action":
            label = LABELS[(top1, urgent)]
            reasons.append(
                f"{top1} at {conf:.2f} confidence, "
                f"urgency {urgency_p:.2f} → {label}."
            )
            decision["action"] = "auto_label"
            decision["label"] = label
            return decision
        if calm and top1 in ("fyi", "receipt", "newsletter"):
            label = LABELS[(top1, False)]
            reasons.append(f"{top1} at {conf:.2f} confidence, calm → {label}.")
            decision["action"] = "auto_label"
            decision["label"] = label
            return decision
        if urgent and top1 in ("fyi", "receipt", "newsletter"):
            reasons.append(
                f"Marked urgent ({urgency_p:.2f}) but categorized as {top1} — "
                "mismatch, needs your call."
            )
            return digest("review", None)
        # noise below the archive bar
        reasons.append(
            f"Probably noise ({conf:.2f}) but below the auto-archive bar "
            f"({t['tau_noise']:.2f}) — your call."
        )
        return digest("archive", None)

    # --- Everything else: digest -------------------------------------------
    if conf < t["tau_cat"]:
        reasons.append(
            f"Category confidence {conf:.2f} below the auto-label bar "
            f"({t['tau_cat']:.2f})."
        )
    if (p1 - p2) < t["delta"]:
        reasons.append(
            f"Top categories too close: {top1} ({p1:.2f}) vs {top2} ({p2:.2f}) — "
            "ambiguous, not guessing."
        )
    if not (urgent or calm):
        reasons.append(f"Urgency uncertain ({urgency_p:.2f}).")
    suggested = "archive" if top1 == "noise" else "label"
    suggested_label = LABELS.get((top1, urgent)) if top1 != "noise" else None
    return digest(suggested, suggested_label)
