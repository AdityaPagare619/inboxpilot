"""InboxPilot CLI.

    inboxpilot demo                      # 5-min keyless demo on a fixture inbox
    inboxpilot run --live [--auto-label] # real triage (needs TYPESAFE_API_KEY + Gmail OAuth)
    inboxpilot digest                    # show the pending morning digest
    inboxpilot approve <id> [--live]     # approve a digest suggestion
    inboxpilot correct <id> <category> [--urgent|--not-urgent]
    inboxpilot tune                      # refit thresholds from your corrections
    inboxpilot serve [--port 8734]       # minimal local web UI

Safe defaults: everything runs against the fixture inbox unless --live is
passed. Auto-labeling Gmail only happens with --live --auto-label.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from inboxpilot import digest as digest_mod
from inboxpilot.gmail_client import GmailClient
from inboxpilot.jev_client import MockSystemOneClient, SystemOneClient
from inboxpilot.store import Store, default_db_path
from inboxpilot.triage import CATEGORIES, triage_email
from inboxpilot.tuner import format_report, tune

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "fixture_inbox.json"

DEMO_CONTACTS = ["rahul.verma@gmail.com", "priya@northloop.io", "rohan@peakxv.com"]


def _p(winner, p_win, runnerup=None, p_run=0.02):
    if runnerup is None:
        runnerup = "noise" if winner == "fyi" else "fyi"
    d = {c: 0.01 for c in CATEGORIES}
    d[winner] = p_win
    d[runnerup] = p_run
    return d


# subject -> (urgency_p, category, confidence, probs, needs_reply_p)
# Exercises every gating branch: P0s, auto-labels, archive, ambiguity,
# the contact-contradiction guardrail, and the below-the-bar digest.
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
    """Normalized per-qid answers for the demo's scripted inbox."""
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
    # MockSystemOneClient scripts per qid; each entry may be a callable.
    def make(qid: str):
        def fn(state: str, questions: dict) -> dict:
            return _demo_answers_for(state)[qid]
        return fn

    return MockSystemOneClient(
        {qid: make(qid) for qid in ("urgency", "category", "needs_reply")}
    )


def get_contacts(args) -> list[str]:
    if args.contacts:
        return [c.strip() for c in args.contacts.split(",") if c.strip()]
    env = os.environ.get("INBOXPLOT_CONTACTS", "")
    if env:
        return [c.strip() for c in env.split(",") if c.strip()]
    return []


def triage_loop(gmail, jev, store, contacts, max_n, auto_label, verbose=True):
    """Run triage over unread mail. Returns (n_triaged, est_tokens)."""
    ids = gmail.list_unread(max_n=max_n)
    est_tokens = 0
    for mid in ids:
        if store.get_decision(mid):
            continue  # already triaged — idempotent
        msg = gmail.get_message(mid)
        store.save_email(msg)
        from inboxpilot.triage import shape_state

        decision = triage_email(jev, msg, contacts, store.get_thresholds())
        est_tokens += len(shape_state(msg, contacts)) // 4
        store.save_decision(mid, decision)
        action = decision["action"]
        if verbose:
            flag = {"auto_archive": "🗑", "auto_label": "🏷",
                    "digest": "📋"}.get(action, "?")
            print(f"  {flag} {msg['subject'][:56]:58} → {action}"
                  + (f" ({decision['label']})" if decision.get("label") else ""))
        if auto_label and action == "auto_label":
            gmail.apply_label(mid, decision["label"])
        elif auto_label and action == "auto_archive":
            gmail.set_archived(mid, True)
    return len(ids), est_tokens


def cmd_demo(args):
    print("✈️  InboxPilot demo — fixture founder inbox, scripted model, zero keys.\n")
    tmp = tempfile.mkdtemp(prefix="inboxpilot-demo-")
    store = Store(path=Path(tmp) / "demo.db")
    gmail = GmailClient(fixture_path=str(FIXTURE), enable_write=True)
    jev = demo_jev_client()
    n, est_tokens = triage_loop(gmail, jev, store, DEMO_CONTACTS, 50,
                                auto_label=True)
    cost = est_tokens / 1e6 * 0.042
    print()
    print(digest_mod.render_text(store))
    print()
    print(f"Triaged {n} emails · ~{est_tokens:,} input tokens · "
          f"~${cost:.4f} of Jev inference. At 120 emails/day, that's "
          f"~${cost / max(n, 1) * 120 * 365:.2f}/user/year.")
    print("Re-run anytime: ./inboxpilot demo  (nothing is sent anywhere)")
    store.close()


def cmd_run(args):
    if not args.live:
        print("Nothing to connect to yet. `inboxpilot run` without --live has no "
              "inbox to read.\nTry `./inboxpilot demo` for the keyless demo, or pass "
              "--live with TYPESAFE_API_KEY set and Gmail OAuth configured\n"
              "(see docs/gmail-setup.md).")
        return 1
    store = Store()
    jev = SystemOneClient()
    gmail = GmailClient(enable_write=args.auto_label)
    contacts = get_contacts(args)
    print(f"Triaging unread mail (auto-label={'on' if args.auto_label else 'off'})…")
    n, est_tokens = triage_loop(gmail, jev, store, contacts, args.max,
                                auto_label=args.auto_label)
    print(f"\nDone: {n} emails, ~{est_tokens:,} tokens (~${est_tokens/1e6*0.042:.4f}).")
    print(digest_mod.render_text(store))
    store.close()
    return 0


def cmd_digest(args):
    store = Store()
    print(digest_mod.render_text(store))
    store.close()


def cmd_approve(args):
    store = Store()
    d = store.get_decision(args.id)
    if not d or d["action"] != "digest":
        print(f"No pending digest suggestion for {args.id}.")
        store.close()
        return 1
    suggested = json.loads(d.get("suggested_json") or "{}")
    action, label = suggested.get("action"), suggested.get("label")
    if args.live and action == "label" and label:
        gmail = GmailClient(enable_write=True)
        gmail.apply_label(args.id, label)
        print(f"Applied {label} to {args.id}.")
    elif args.live:
        print(f"Approved ({action}) for {args.id} — live label/archive "
              f"application for digest items lands in v0.2; marked reviewed.")
    else:
        print(f"Approved suggestion for {args.id} ({action}"
              + (f": {label}" if label else "")
              + ") [fixture mode — nothing sent anywhere]")
    store.mark_reviewed(args.id, approved=True)
    store.close()
    return 0


def cmd_undo(args):
    """Undo an auto-action. Archive never deletes, labels are removable."""
    store = Store()
    d = store.get_decision(args.id)
    if not d or d["action"] not in ("auto_label", "auto_archive"):
        print(f"Nothing to undo for {args.id} (no auto-action recorded).")
        store.close()
        return 1
    gmail = GmailClient(
        fixture_path=str(FIXTURE) if not args.live else None,
        enable_write=True,
    )
    if d["action"] == "auto_label":
        gmail.remove_label(args.id, d["label"])
        print(f"Removed label {d['label']} from {args.id}.")
    else:
        gmail.set_archived(args.id, False)
        print(f"Restored {args.id} to the inbox.")
    store.close()
    return 0


def cmd_correct(args):
    if args.category not in CATEGORIES:
        print(f"Unknown category. Choose from: {', '.join(CATEGORIES)}")
        return 1
    urgent = True if args.urgent else (False if args.not_urgent else None)
    store = Store()
    if not store.get_decision(args.id):
        print(f"No triaged email {args.id} in the store.")
        return 1
    store.record_correction(args.id, args.category, urgent)
    n = store.correction_count()
    print(f"Correction recorded ({n} total). Run `inboxpilot tune` to refit.")
    store.close()
    return 0


def cmd_tune(args):
    store = Store()
    report = tune(store, get_contacts(args))
    print(format_report(report))
    store.close()
    return 0


def cmd_serve(args):
    store_holder = {}

    class Handler(BaseHTTPRequestHandler):
        def _store(self):
            if "s" not in store_holder:
                store_holder["s"] = Store()
            return store_holder["s"]

        def do_GET(self):
            body = digest_mod.render_html(self._store()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            params = urllib.parse.parse_qs(self.rfile.read(length).decode())
            mid = (params.get("id") or [""])[0]
            if mid:
                self._store().mark_reviewed(mid, approved=True)
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", args.port), Handler)
    print(f"InboxPilot digest at http://127.0.0.1:{args.port}  (Ctrl-C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def main(argv=None):
    ap = argparse.ArgumentParser(prog="inboxpilot",
                                 description="Confidence-gated email triage on Jev.")
    ap.add_argument("--contacts",
                    help="comma-separated contact emails (never-archive guardrail)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("demo", help="5-minute keyless demo on a fixture inbox")
    r = sub.add_parser("run", help="triage real unread mail")
    r.add_argument("--live", action="store_true",
                   help="use the real Jev API + Gmail (needs key + OAuth)")
    r.add_argument("--auto-label", action="store_true",
                   help="apply Gmail labels for auto actions (needs gmail.modify)")
    r.add_argument("--max", type=int, default=50)
    sub.add_parser("digest", help="show the pending morning digest")
    a = sub.add_parser("approve", help="approve a digest suggestion")
    a.add_argument("id")
    a.add_argument("--live", action="store_true")
    u = sub.add_parser("undo", help="undo an auto-label / unarchive a message")
    u.add_argument("id")
    u.add_argument("--live", action="store_true")
    c = sub.add_parser("correct", help="correct a triage decision (feeds the tuner)")
    c.add_argument("id")
    c.add_argument("category")
    c.add_argument("--urgent", action="store_true")
    c.add_argument("--not-urgent", action="store_true")
    sub.add_parser("tune", help="refit thresholds from your corrections")
    s = sub.add_parser("serve", help="minimal local web UI")
    s.add_argument("--port", type=int, default=8734)

    args = ap.parse_args(argv)
    return {
        "demo": cmd_demo, "run": cmd_run, "digest": cmd_digest,
        "approve": cmd_approve, "undo": cmd_undo, "correct": cmd_correct,
        "tune": cmd_tune, "serve": cmd_serve,
    }[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
