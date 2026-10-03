"""Build the static snapshot for the GitHub-Pages deployment.

GitHub Pages serves static files only, so the Vercel Python API cannot run
there. This script precomputes everything the client needs:

- for seeds {0,1,2,3}: the fixture emails + the (seed-perturbed) mock-Jev
  answers for each mail — the ONLY dynamic inputs to the decision math.
- static copy: contacts, questions, default thresholds, cost math, privacy,
  scopes, demo notes.

All decision/tuner math is re-implemented in `web/src/static/triage.js`
(a faithful port of src/inboxpilot/triage.py + tuner.py + demo_store.py's
branch classification), so counts, branches, what-ifs and tune reports are
computed client-side with zero drift from the server version.

Output: web/public/snapshot.json (served at /inboxpilot/snapshot.json).
No secrets: fixture data + scripted answers only.
"""

import json
import os
import sys

LIB_DIR = os.path.dirname(os.path.abspath(__file__))  # web/tools
WEB_DIR = os.path.dirname(LIB_DIR)
sys.path.insert(0, os.path.join(WEB_DIR, "lib"))

import demo_store  # noqa: E402
from inboxpilot.triage import (  # noqa: E402
    DEFAULT_THRESHOLDS,
    CATEGORIES,
    build_questions,
)

SEEDS = [0, 1, 2, 3]

DEMO_NOTES = [
    "Fixture inbox (21 messages) — no real email touched",
    "Scripted mock-Jev answers — no API key, no network",
    "Static build: corrections & tunes live in your browser only",
    "seed>0 simulates Jev's 1.3-2.2% answer flips",
]

HONESTY = [
    "Answers are scripted for the demo (mock-jev-1.13.0)",
    "Real Jev flips 1.3-2.2% of answers on identical repeats — nothing is presented as certain",
]

DEMO_CAVEATS = [
    "Demo runs on a fixture inbox with scripted answers",
    "Real usage needs YOUR TypeSafe API key (BYOK) and YOUR Gmail OAuth client — see the 'Connect your own' cards in the UI",
    "Thresholds start conservative: digest-heavy first week by design",
]


def main():
    snapshot = {
        "seeds": {},
        "contacts": list(demo_store.DEMO_CONTACTS),
        "questions": build_questions(),
        "thresholds": dict(DEFAULT_THRESHOLDS),
        "categories": dict(CATEGORIES),
        "cost": demo_store.COST_MATH,
        "privacy": list(demo_store.PRIVACY_COPY),
        "scopes": dict(demo_store.SCOPES_COPY),
        "demo_notes": DEMO_NOTES,
        "honesty": HONESTY,
        "demo_caveats": DEMO_CAVEATS,
    }
    for seed in SEEDS:
        emails = demo_store.load_emails()
        answers = {}
        for email in emails:
            a = demo_store.answers_for(email, seed)
            answers[email["id"]] = {
                "urgency_p": a["urgency"]["p"],
                "needs_reply_p": a["needs_reply"]["p"],
                "probs": {k: float(v) for k, v in a["category"]["probabilities"].items()},
                "confidence": float(a["category"]["confidence"]),
            }
        snapshot["seeds"][str(seed)] = {"emails": emails, "answers": answers}

    out_path = os.path.join(WEB_DIR, "public", "snapshot.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(snapshot, f, separators=(",", ":"))
    size_kb = os.path.getsize(out_path) / 1024
    print(f"wrote {out_path} ({size_kb:.1f} KB), seeds={SEEDS}")


if __name__ == "__main__":
    main()
