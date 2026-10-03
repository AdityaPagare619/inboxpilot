"""Session layer for the InboxPilot web demo.

Keyless DEMO: fixture inbox + scripted mock-Jev answers (demo_script.py).
No API keys, no Gmail, no network. All state is per-process session memory
(serverless instances are ephemeral) — the UI says so plainly.

Uses the REAL vendored logic: triage.decide_from_answers, tuner, gmail_client
fixture loader. The `seed` param deterministically perturbs probabilities by
up to +/-2% to *simulate* Jev's real 1.3-2.2% non-determinism (labeled as such
in the UI). seed=0 = scripted answers exactly.
"""

import copy
import hashlib
import json
import os

from inboxpilot.gmail_client import GmailClient
from inboxpilot.triage import (
    CATEGORIES,
    DEFAULT_THRESHOLDS,
    LABELS,
    decide_from_answers,
)
from inboxpilot import tuner as tuner_mod

from demo_script import DEMO_CONTACTS, demo_jev_client, _demo_answers_for
from inboxpilot.triage import shape_state, build_questions

LIB_DIR = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(LIB_DIR, "fixture_inbox.json")

# Per-process session memory (resets on cold start — UI says so).
_SESSION = {
    "corrections": {},   # email_id -> {"category": str, "urgent": bool|None}
    "thresholds": None,  # None = defaults
    "tune_events": [],   # audit entries for tune runs
}

FLIP_MAGNITUDE = 0.02  # simulated Jev flip band, per research 1.3-2.2%


# ---------------------------------------------------------------------------
# Fixture + triage
# ---------------------------------------------------------------------------

def load_emails():
    g = GmailClient(fixture_path=FIXTURE)
    ids = g.list_unread(max_n=50)
    emails = []
    for mid in ids:
        m = g.get_message(mid)
        emails.append({
            "id": m["id"],
            "from": m.get("from", ""),
            "subject": m.get("subject", ""),
            "date": m.get("date", ""),
            "snippet": (m.get("body") or "")[:160],
            "body": m.get("body") or "",
            "thread_n": m.get("thread_n"),
        })
    return emails


def _flip_for(seed: int, email_id: str, field: str) -> float:
    """Deterministic pseudo-random in [-1, 1] for (seed, email, field)."""
    h = hashlib.sha256(f"{seed}|{email_id}|{field}".encode()).hexdigest()
    return (int(h[:8], 16) / 0xFFFFFFFF) * 2 - 1


def answers_for(email: dict, seed: int) -> dict:
    """Scripted demo answers, optionally perturbed to simulate a Jev flip."""
    state = shape_state(email, DEMO_CONTACTS)
    base = _demo_answers_for(state)
    if seed == 0:
        return copy.deepcopy(base)
    out = copy.deepcopy(base)
    # perturb urgency + needs_reply within the flip band
    for qid in ("urgency", "needs_reply"):
        delta = _flip_for(seed, email["id"], qid) * FLIP_MAGNITUDE
        out[qid]["p"] = min(0.99, max(0.01, out[qid]["p"] + delta))
    # perturb category probs, renormalize
    probs = out["category"]["probabilities"]
    pert = {c: max(0.001, p + _flip_for(seed, email["id"], "cat:" + c) * FLIP_MAGNITUDE)
            for c, p in probs.items()}
    total = sum(pert.values())
    out["category"]["probabilities"] = {c: p / total for c, p in pert.items()}
    return out


def get_thresholds() -> dict:
    t = dict(DEFAULT_THRESHOLDS)
    if _SESSION["thresholds"]:
        t.update(_SESSION["thresholds"])
    return t


def triage_all(seed: int = 0, thresholds: dict | None = None):
    """Triage the whole fixture inbox. Returns (emails_with_decisions, counts)."""
    t = dict(get_thresholds())
    if thresholds:
        t.update({k: v for k, v in thresholds.items() if k in t})
    emails = load_emails()
    out = []
    for email in emails:
        answers = answers_for(email, seed)
        decision = decide_from_answers(
            answers, email, DEMO_CONTACTS, t, model="mock (scripted demo)"
        )
        branch, rule = classify_branch(decision, email, t)
        decision["branch"] = branch
        decision["branch_rule"] = rule
        email = dict(email)
        email["decision"] = decision
        out.append(email)
    counts = {"total": len(out), "auto_label": 0, "auto_archive": 0, "digest": 0}
    for e in out:
        counts[e["decision"]["action"]] += 1
    return out, counts


# ---------------------------------------------------------------------------
# Branch classification — which escalation-policy rule fired (the trust layer)
# ---------------------------------------------------------------------------

BRANCH_RULES = {
    "guardrail_contact_noise": {
        "title": "Guardrail: contact contradiction",
        "quote": "Never act on noise when the sender is in contacts (contradiction → digest).",
    },
    "auto_archive": {
        "title": "Auto-archive: provably calm noise",
        "quote": "Auto-archive (noise only) ONLY at confidence ≥ τ_noise AND urgency < 0.3.",
    },
    "auto_label_p0": {
        "title": "Auto-label: decisive P0",
        "quote": "Auto-label ONLY when category confidence ≥ τ_cat, urgency decisive, top-2 margin ≥ δ.",
    },
    "auto_label": {
        "title": "Auto-label: decisive, calm",
        "quote": "Auto-label ONLY when category confidence ≥ τ_cat, urgency decisive, top-2 margin ≥ δ.",
    },
    "guardrail_urgent_mismatch": {
        "title": "Guardrail: urgent-but-routine mismatch",
        "quote": "Marked urgent but categorized as fyi/receipt/newsletter — mismatch, needs your call.",
    },
    "digest_noise_bar": {
        "title": "Digest: below the archive bar",
        "quote": "Probably noise but below the auto-archive bar (τ_noise) — your call.",
    },
    "digest_low_conf": {
        "title": "Digest: below confidence bar",
        "quote": "Category confidence below the auto-label bar (τ_cat). Uncertainty is a first-class output.",
    },
    "digest_close_call": {
        "title": "Digest: too close to call",
        "quote": "Top categories within δ of each other — ambiguous, not guessing.",
    },
    "digest_urgent_uncertain": {
        "title": "Digest: urgency uncertain",
        "quote": "Urgency not decisive (between the low/high bands) — doubt goes to the digest.",
    },
}


def classify_branch(decision: dict, email: dict, t: dict):
    action = decision["action"]
    top1 = decision["category"]
    conf = decision["category_confidence"]
    probs = decision["category_probs"]
    ranked = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)
    margin = ranked[0][1] - (ranked[1][1] if len(ranked) > 1 else 0.0)
    up = decision["urgency_p"]
    sender_lc = (email.get("from") or "").lower()
    known = any(c.lower() in sender_lc for c in DEMO_CONTACTS)

    if action == "digest" and top1 == "noise" and known:
        b = "guardrail_contact_noise"
    elif action == "auto_archive":
        b = "auto_archive"
    elif action == "auto_label":
        b = "auto_label_p0" if decision.get("label") == "InboxPilot/P0" else "auto_label"
    elif action == "digest" and up >= t["urgent_high"] and top1 in ("fyi", "receipt", "newsletter"):
        b = "guardrail_urgent_mismatch"
    elif action == "digest" and top1 == "noise":
        b = "digest_noise_bar"
    elif action == "digest" and conf < t["tau_cat"]:
        b = "digest_low_conf"
    elif action == "digest" and margin < t["delta"]:
        b = "digest_close_call"
    elif action == "digest":
        b = "digest_urgent_uncertain"
    else:
        b = "digest_urgent_uncertain"
    return b, {"id": b, **BRANCH_RULES[b]}


# ---------------------------------------------------------------------------
# Corrections + tuner (session memory)
# ---------------------------------------------------------------------------

class SessionStore:
    """In-memory adapter with the Store interface tuner.py needs."""

    def __init__(self, rows: list[dict]):
        self._rows = rows
        self._thresholds = get_thresholds()

    def labeled_cases(self):
        return self._rows

    def get_thresholds(self):
        return dict(self._thresholds)

    def set_threshold(self, name: str, value: float):
        if name in self._thresholds:
            self._thresholds[name] = value


def _labeled_rows(seed: int):
    """Build tuner rows from current triage decisions + session corrections."""
    emails, _ = triage_all(seed=seed)
    rows = []
    for e in emails:
        corr = _SESSION["corrections"].get(e["id"])
        if not corr:
            continue
        d = e["decision"]
        rows.append({
            "email_id": e["id"],
            "sender": e["from"],
            "urgency_p": d["urgency_p"],
            "needs_reply_p": d["needs_reply_p"],
            "category_probs_json": json.dumps(d["category_probs"]),
            "category_confidence": d["category_confidence"],
            "correct_category": corr["category"],
            "correct_urgent": corr["urgent"],
        })
    return rows


def record_correction(email_id: str, category: str, urgent):
    if category not in CATEGORIES:
        raise ValueError(f"unknown category {category!r}")
    _SESSION["corrections"][email_id] = {"category": category, "urgent": urgent}
    n = len(_SESSION["corrections"])
    if n < tuner_mod.MIN_LABELS_FIT:
        status, msg = "refuse", f"{n}/10 corrections — tuner holds conservative defaults."
    elif n < tuner_mod.MIN_LABELS_STABLE:
        status, msg = "provisional", f"{n}/50 corrections — any tune would be PROVISIONAL."
    else:
        status, msg = "stable", f"{n} corrections — stable enough to tune."
    return {"n_labels": n, "status": status, "message": msg}


def run_tune(seed: int = 0, fn_cost: float = 100.0, preview: dict | None = None,
             apply: bool = True):
    """Run the REAL tuner grid search over session corrections.

    fn_cost: asymmetric cost of a wrongly-archived urgent mail (100-1000x).
    preview: custom {tau_cat, tau_noise, delta} for what-if counts (no apply).
    """
    rows = _labeled_rows(seed)
    store = SessionStore(rows)
    old_cost = tuner_mod.COST_WRONG_ARCHIVE
    tuner_mod.COST_WRONG_ARCHIVE = -abs(fn_cost)
    try:
        if preview is not None:
            # what-if: counts under custom thresholds, nothing applied
            emails, counts = triage_all(seed=seed, thresholds=preview)
            return {
                "mode": "preview", "applied": False,
                "thresholds": preview, "counts": counts,
                "n_labels": len(rows),
                "note": "What-if only — thresholds not applied, no corrections consumed.",
            }
        report = tuner_mod.tune(store, DEMO_CONTACTS)
    finally:
        tuner_mod.COST_WRONG_ARCHIVE = old_cost

    if report["applied"]:
        _SESSION["thresholds"] = {k: report["after"][k]
                                  for k in ("tau_cat", "tau_noise", "delta")}
        _SESSION["tune_events"].append(
            {"n": report["n_labels"], "after": dict(report["after"])})
    # decision distribution under before/after thresholds
    _, counts_before = triage_all(seed=seed, thresholds=report["before"])
    _, counts_after = triage_all(seed=seed, thresholds=report["after"])
    report["mode"] = "tune"
    report["fn_cost"] = fn_cost
    report["counts_before"] = counts_before
    report["counts_after"] = counts_after
    return report


# ---------------------------------------------------------------------------
# Audit + greeting
# ---------------------------------------------------------------------------

ACTION_COPY = {
    "auto_label": "Auto-labeled",
    "auto_archive": "Auto-archived",
    "digest": "Sent to digest",
}


def build_audit(seed: int = 0):
    emails, _ = triage_all(seed=seed)
    entries = []
    for e in emails:
        d = e["decision"]
        action = d["action"]
        if action == "auto_label":
            summary = f"Labeled {d['label']}"
        elif action == "auto_archive":
            summary = "Archived (noise, provably calm)"
        else:
            sugg = (d.get("suggested") or {}).get("action", "review")
            summary = f"Digest — suggested: {sugg}"
        entries.append({
            "kind": "decision",
            "email_id": e["id"],
            "subject": e["subject"],
            "summary": summary,
            "detail": "; ".join(d["reasons"]),
            "category": d["category"],
            "confidence": round(d["category_confidence"], 2),
            "urgency_p": round(d["urgency_p"], 2),
            "branch": d["branch"],
            "ts": e["date"],
        })
    for eid, corr in _SESSION["corrections"].items():
        entries.append({
            "kind": "correction", "email_id": eid,
            "subject": next((e["subject"] for e in emails if e["id"] == eid), eid),
            "summary": f"You corrected → {corr['category']}"
                       + (f" ({'urgent' if corr['urgent'] else 'not urgent'})"
                          if corr["urgent"] is not None else ""),
            "detail": "Correction recorded in session memory; feeds the threshold tuner.",
            "ts": "session",
        })
    for ev in _SESSION["tune_events"]:
        entries.append({
            "kind": "tune", "email_id": None, "subject": "Threshold tune",
            "summary": f"Tuned on {ev['n']} corrections",
            "detail": "New thresholds: " + ", ".join(
                f"{k}={v:.2f}" for k, v in ev["after"].items()
                if k in ("tau_cat", "tau_noise", "delta")),
            "ts": "session",
        })
    entries.sort(key=lambda x: str(x["ts"]), reverse=True)
    return entries


def morning_greeting(counts: dict) -> str:
    n = counts["total"]
    auto = counts["auto_label"] + counts["auto_archive"]
    dig = counts["digest"]
    p0 = "P0s"  # refined by frontend from data
    return (f"\u2615 Good morning. {n} emails arrived overnight. "
            f"{auto} handled automatically. {dig} want your call.")


COST_MATH = {
    "emails_per_day": 120,
    "tokens_per_email": 1500,
    "price_per_m_input_usd": 0.042,
    "per_email_usd": 120 * 0 + 1500 / 1e6 * 0.042,
    "per_day_usd": round(120 * 1500 / 1e6 * 0.042, 4),
    "per_year_usd": round(120 * 1500 / 1e6 * 0.042 * 365, 2),
    "note": "Output tokens free. Inference was never the constraint — trust is.",
}

PRIVACY_COPY = [
    "Email text sent for classification goes to TypeSafe AI: US-only hosting, vague retention (\"as long as reasonably necessary\"), no training on your inputs. Zero-retention is enterprise-only.",
    "Everything else — labels, thresholds, corrections, the audit log — stays local. In this demo, nothing leaves the Vercel instance at all: fixture inbox + scripted answers, zero network.",
    "TypeSafe's terms forbid distilling Jev outputs into your own model. We store decisions, not training data.",
]

SCOPES_COPY = {
    "read": "gmail.readonly — list + read mail. Triage and digest work fully read-only.",
    "write": "gmail.modify — requested ONLY when you explicitly enable auto-label, with a plain-language why. Labels are applied; nothing is ever deleted.",
    "honest_moat": "gmail.readonly is a Google restricted scope: shipping as public multi-tenant SaaS would need OAuth verification + annual CASA assessment (five figures, weeks). Self-hosted BYOK sidesteps it — a real moat and a real future cost.",
}
