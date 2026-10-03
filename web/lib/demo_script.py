"""Demo-mode Jev answers, extracted verbatim from the CLI's `inboxpilot demo`.

Keyless demo: fixture inbox + scripted mock answers (MockSystemOneClient).
NO real API key, NO real Gmail. Mirrors src/inboxpilot/cli.py DEMO_ANSWERS.
"""

from inboxpilot.jev_client import MockSystemOneClient
from inboxpilot.triage import CATEGORIES

DEMO_CONTACTS = ["rahul.verma@gmail.com", "priya@northloop.io", "rohan@peakxv.com"]

MODEL_NAME = "mock-jev-1.13.0 (scripted demo answers)"


def _p(winner, p_win, runnerup=None, p_run=0.02):
    if runnerup is None:
        runnerup = "noise" if winner == "fyi" else "fyi"
    d = {c: 0.01 for c in CATEGORIES}
    d[winner] = p_win
    d[runnerup] = p_run
    return d


# subject -> (urgency_p, category, confidence, probs, needs_reply_p)
DEMO_ANSWERS = {
    "Re: Northloop dashboard down for our entire team - P0": (0.93, "needs_action", 0.95, _p("needs_action", 0.95), 0.9),
    "Security alert: sign-in attempt blocked": (0.88, "needs_action", 0.90, _p("needs_action", 0.90), 0.1),
    "Re: v2 webhook docs - still waiting": (0.72, "needs_action", 0.88, _p("needs_action", 0.88), 0.85),
    "lol you HAVE to see this": (0.05, "noise", 0.97, _p("noise", 0.97), 0.0),
    "Your payout of \u20b984,210.00 is on the way": (0.05, "receipt", 0.94, _p("receipt", 0.94), 0.0),
    "Your AWS invoice for September 2026 is ready": (0.08, "receipt", 0.96, _p("receipt", 0.96), 0.0),
    "Monthly update - quick ask": (0.78, "needs_action", 0.89, _p("needs_action", 0.89), 0.7),
    "Question about your pricing tiers": (0.70, "needs_action", 0.91, _p("needs_action", 0.91), 0.9),
    "[northloop/api] Priya Nair requested your review: PR #482": (0.45, "needs_action", 0.86, _p("needs_action", 0.86), 0.8),
    "Ticket #3109: Can't reset my password - locked out": (0.82, "needs_action", 0.90, _p("needs_action", 0.90), 0.9),
    "New sign-in from Chrome on Mac": (0.35, "fyi", 0.88, _p("fyi", 0.88), 0.0),
    "Payment failed for Northloop Pro (Figma)": (0.85, "needs_action", 0.93, _p("needs_action", 0.93), 0.6),
    "Your Northloop Pro subscription renews in 7 days": (0.15, "fyi", 0.90, _p("fyi", 0.90), 0.0),
    "TechCrunch Daily: AI agents raise $2B in Q3": (0.02, "newsletter", 0.98, _p("newsletter", 0.98), 0.0),
    "Last chance: 50% off Notion annual plans ends today": (0.03, "newsletter", 0.95, _p("newsletter", 0.95), 0.0),
    "12 people viewed your profile this week": (0.02, "noise", 0.93, _p("noise", 0.93), 0.0),
    "You're invited: How to price your seed round (Oct 9)": (0.20, "fyi", 0.87, _p("fyi", 0.87), 0.0),
    "ELON MUSK CRYPTO GIVEAWAY - DOUBLE YOUR BTC!!!": (0.01, "noise", 0.99, _p("noise", 0.99), 0.0),
    "Staff Engineer roles at FAANG - 15 min chat?": (0.04, "noise", 0.88, _p("noise", 0.88), 0.0),
    "We've updated our Terms of Service": (0.05, "fyi", 0.92, _p("fyi", 0.92), 0.0),
    "Application: Design Intern, Winter 2026": (0.40, "needs_action", 0.60,
        {**{c: 0.01 for c in CATEGORIES}, "needs_action": 0.55, "fyi": 0.45}, 0.5),
}


def _demo_answers_for(state: str) -> dict:
    subject = ""
    for line in state.splitlines():
        if line.startswith("Subject: "):
            subject = line[len("Subject: "):]
            break
    if subject not in DEMO_ANSWERS:
        raise AssertionError(f"demo has no scripted answer for: {subject!r}")
    u_p, cat, conf, probs, nr_p = DEMO_ANSWERS[subject]
    return {
        "urgency": {"type": "noul", "p": u_p},
        "category": {"type": "choice", "choice": cat,
                     "probabilities": probs, "confidence": conf},
        "needs_reply": {"type": "noul", "p": nr_p},
    }


def demo_jev_client() -> MockSystemOneClient:
    def make(qid: str):
        def fn(state: str, questions: dict) -> dict:
            return _demo_answers_for(state)[qid]
        return fn
    return MockSystemOneClient(
        {qid: make(qid) for qid in ("urgency", "category", "needs_reply")},
        model="mock-jev-1.13.0 (scripted)",
    )
