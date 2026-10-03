"""Dump reference outputs from the REAL Python stack for drift-checking the JS port."""
import json
import os
import sys

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))  # web/tools
WEB_DIR = os.path.dirname(TOOLS_DIR)  # web/
REPO_DIR = os.path.dirname(WEB_DIR)   # repo root
sys.path.insert(0, REPO_DIR)
sys.path.insert(0, os.path.join(WEB_DIR, "lib"))

import demo_store  # noqa: E402
from inboxpilot import tuner as tuner_mod  # noqa: E402

ref = {"seeds": {}}

for seed in [0, 1, 2, 3]:
    emails, counts = demo_store.triage_all(seed=seed)
    ref["seeds"][str(seed)] = {
        "counts": counts,
        "thresholds": demo_store.get_thresholds(),
        "decisions": {
            e["id"]: {
                "action": e["decision"]["action"],
                "label": e["decision"]["label"],
                "category": e["decision"]["category"],
                "category_confidence": e["decision"]["category_confidence"],
                "urgency_p": e["decision"]["urgency_p"],
                "branch": e["decision"]["branch"],
                "branch_rule_id": e["decision"]["branch_rule"]["id"],
                "reasons": e["decision"]["reasons"],
                "suggested": e["decision"].get("suggested"),
            }
            for e in emails
        },
    }

# what-if counts under non-default thresholds (seed 1)
_, counts_wi = demo_store.triage_all(
    seed=1, thresholds={"tau_cat": 0.75, "tau_noise": 0.93, "delta": 0.10}
)
ref["whatif"] = {"counts": counts_wi}

# correction status messages from REAL code
def status_for(n):
    demo_store._SESSION["corrections"] = {
        f"x{i}": {"category": "fyi", "urgent": False} for i in range(n - 1)
    }
    return demo_store.record_correction("xn", "fyi", False)

ref["status"] = {str(n): status_for(n) for n in (3, 12, 60)}

# tune scenario: 12 realistic fake corrections on seed-1 digest mails
demo_store._SESSION["corrections"] = {}
demo_store._SESSION["thresholds"] = None
demo_store._SESSION["tune_events"] = []
emails, _ = demo_store.triage_all(seed=1)
digest = [e for e in emails if e["decision"]["action"] == "digest"][:12]
for i, e in enumerate(digest):
    demo_store.record_correction(
        e["id"],
        ["needs_action", "fyi", "receipt", "newsletter", "noise"][i % 5],
        (i % 2 == 0),
    )
rows = demo_store._labeled_rows(seed=1)
store = demo_store.SessionStore(rows)
report = tuner_mod.tune(store, demo_store.DEMO_CONTACTS)
ref["tune"] = {"rows_n": len(rows), "report": report}

out = os.path.join(WEB_DIR, "tools", "reference.json")
with open(out, "w") as f:
    json.dump(ref, f, indent=1, default=str)
print(f"wrote {out}")
