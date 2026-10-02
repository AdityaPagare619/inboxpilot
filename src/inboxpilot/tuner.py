"""Threshold tuner: refit gating thresholds from user corrections.

The engine starts conservative (ARCHITECTURE.md §4). Every time the user
corrects a triage decision, that label becomes fuel: the tuner re-simulates
each labeled email under a grid of candidate thresholds and picks the set
that maximizes expected utility under the asymmetric cost model
(false archive of something important >> wrong label >> digest).

Honesty rules (from the research: 50–300 own labels for stable thresholds):
- <10 corrections: refuse to change anything, say so.
- 10–49: apply, but flag the result PROVISIONAL.
- >=50: stable enough to trust.

No inference is spent: decide_from_answers re-scores stored probabilities.
"""

from __future__ import annotations

import json

from .triage import DEFAULT_THRESHOLDS, LABELS, decide_from_answers

# Asymmetric costs. A wrongly archived urgent email is the catastrophe the
# whole product is designed to avoid; a needless digest entry is just a
# moment of the founder's attention.
COST_WRONG_ARCHIVE = -100.0
COST_WRONG_LABEL = -10.0
COST_DIGEST = -0.1
REWARD_CORRECT_AUTO = 1.0

GRID = {
    "tau_cat": [0.70, 0.75, 0.80, 0.85, 0.90, 0.95],
    "tau_noise": [0.90, 0.93, 0.95, 0.97, 0.99],
    "delta": [0.05, 0.10, 0.15, 0.20, 0.25],
}

MIN_LABELS_FIT = 10
MIN_LABELS_STABLE = 50


def _expected_label(correct_category: str, correct_urgent: bool | None) -> str | None:
    """The label a perfect triage would have applied (None = archive/digest)."""
    if correct_category == "noise" and not correct_urgent:
        return "ARCHIVE"
    if correct_urgent is None:
        return None  # unknown — only digest counts as safe
    return LABELS.get((correct_category, bool(correct_urgent)))


def utility(decision: dict, correct_category: str, correct_urgent: bool | None) -> float:
    """Score one simulated decision against ground truth."""
    action = decision.get("action")
    if action == "digest":
        return COST_DIGEST
    if action == "auto_archive":
        if correct_category == "noise" and not correct_urgent:
            return REWARD_CORRECT_AUTO
        return COST_WRONG_ARCHIVE
    if action == "auto_label":
        expected = _expected_label(correct_category, correct_urgent)
        if expected is not None and decision.get("label") == expected:
            return REWARD_CORRECT_AUTO
        return COST_WRONG_LABEL
    return COST_DIGEST  # unknown action: fail safe


def _answers_from_row(row: dict) -> dict:
    return {
        "urgency": {"p": row["urgency_p"]},
        "needs_reply": {"p": row["needs_reply_p"]},
        "category": {
            "probabilities": json.loads(row["category_probs_json"]),
            "confidence": row["category_confidence"],
        },
    }


def score_thresholds(cases: list[dict], thresholds: dict, contacts=()) -> float:
    """Total utility of `thresholds` over the labeled cases."""
    total = 0.0
    for row in cases:
        correct_urgent = row["correct_urgent"]
        if correct_urgent is not None:
            correct_urgent = bool(correct_urgent)
        email = {"id": row["email_id"], "from": row.get("sender") or ""}
        decision = decide_from_answers(
            _answers_from_row(row), email, contacts, thresholds
        )
        total += utility(decision, row["correct_category"], correct_urgent)
    return total


def tune(store, contacts=()) -> dict:
    """Grid-search thresholds on the user's corrections. Applies the winner.

    Returns a report dict (never raises for lack of data — reports it).
    """
    cases = store.labeled_cases()
    n = len(cases)
    current = store.get_thresholds()
    report: dict = {
        "n_labels": n,
        "before": dict(current),
        "after": dict(current),
        "utility_before": score_thresholds(cases, current, contacts) if n else 0.0,
        "utility_after": 0.0,
        "applied": False,
        "provisional": False,
        "notes": [],
    }
    if n < MIN_LABELS_FIT:
        report["notes"].append(
            f"Only {n} corrections — need at least {MIN_LABELS_FIT} before "
            "tuning. Thresholds unchanged (conservative defaults hold)."
        )
        return report

    best, best_u = None, float("-inf")
    for tau_cat in GRID["tau_cat"]:
        for tau_noise in GRID["tau_noise"]:
            for delta in GRID["delta"]:
                cand = dict(current)
                cand.update(
                    {"tau_cat": tau_cat, "tau_noise": tau_noise, "delta": delta}
                )
                u = score_thresholds(cases, cand, contacts)
                # Tie-break: prefer the candidate closest to current (stability).
                dist = sum(
                    abs(cand[k] - current[k]) for k in ("tau_cat", "tau_noise", "delta")
                )
                if u > best_u or (
                    u == best_u
                    and best is not None
                    and dist
                    < sum(
                        abs(best[k] - current[k])
                        for k in ("tau_cat", "tau_noise", "delta")
                    )
                ):
                    best, best_u = cand, u

    assert best is not None
    for k in ("tau_cat", "tau_noise", "delta"):
        store.set_threshold(k, best[k])
    report["after"] = dict(best)
    report["utility_after"] = best_u
    report["applied"] = True
    if n < MIN_LABELS_STABLE:
        report["provisional"] = True
        report["notes"].append(
            f"Tuned on {n} corrections — PROVISIONAL. Research says 50–300 "
            "labels for stable thresholds; the tuner stays conservative until then."
        )
    else:
        report["notes"].append(
            f"Tuned on {n} corrections — thresholds considered stable."
        )
    improved = best_u - report["utility_before"]
    report["notes"].append(
        f"Expected utility on your labeled history: "
        f"{report['utility_before']:.1f} → {best_u:.1f} (Δ {improved:+.1f})."
    )
    return report


def format_report(report: dict) -> str:
    """Human-readable tuner report for the CLI."""
    lines = [f"Corrections used: {report['n_labels']}"]
    for k in ("tau_cat", "tau_noise", "delta"):
        b, a = report["before"][k], report["after"][k]
        mark = "  ← changed" if b != a else ""
        lines.append(f"  {k}: {b:.2f} → {a:.2f}{mark}")
    lines.append(
        f"Utility: {report['utility_before']:.1f} → {report['utility_after']:.1f}"
    )
    for note in report["notes"]:
        lines.append(f"• {note}")
    return "\n".join(lines)
