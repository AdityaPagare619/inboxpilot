"""Golden tests for the triage engine: every gating branch in ARCHITECTURE.md §3."""

import tempfile
import unittest
from pathlib import Path

from inboxpilot.jev_client import MockSystemOneClient
from inboxpilot.store import Store
from inboxpilot.triage import (
    CATEGORIES,
    build_questions,
    shape_state,
    triage_email,
)


def mock_for(urgency_p, category, conf, probs, needs_reply_p=0.1):
    return MockSystemOneClient(
        {
            "urgency": {"type": "noul", "p": urgency_p},
            "category": {
                "type": "choice",
                "choice": category,
                "probabilities": probs,
                "confidence": conf,
            },
            "needs_reply": {"type": "noul", "p": needs_reply_p},
        }
    )


def email(**kw):
    base = {
        "id": "m1",
        "thread_id": "t1",
        "from": "promo@spam.example",
        "subject": "50% off today",
        "date": "2026-10-02",
        "snippet": "sale",
        "body": "sale body",
        "labels": ["UNREAD"],
    }
    base.update(kw)
    return base


def probs_for(winner, p_win, runnerup=None, p_run=0.03):
    if runnerup is None:
        runnerup = "noise" if winner == "fyi" else "fyi"
    d = {c: 0.01 for c in CATEGORIES}
    d[winner] = p_win
    d[runnerup] = p_run
    return d


class TestQuestionDesign(unittest.TestCase):
    def test_three_atomic_questions(self):
        qs = build_questions()
        self.assertEqual(set(qs), {"urgency", "category", "needs_reply"})
        self.assertEqual(qs["urgency"]["type"], "noul")
        self.assertEqual(qs["category"]["type"], "choice")
        # Inbox-Zero law: small, described, mutually exclusive
        self.assertLessEqual(len(qs["category"]["criteria"]), 6)
        for opt, desc in qs["category"]["criteria"].items():
            self.assertTrue(desc and len(desc) > 20, f"bare label: {opt}")

    def test_state_bounded_and_factual(self):
        e = email(body="x" * 20000, **{"from": "Aarav Sharma <aarav@northloop.io>"})
        s = shape_state(e, contacts=["aarav@northloop.io"])
        self.assertLessEqual(len(s), 6000)
        self.assertIn("contacts: yes", s)
        s2 = shape_state(e, contacts=[])
        self.assertIn("contacts: no", s2)


class TestGating(unittest.TestCase):
    def test_clear_noise_auto_archives(self):
        jev = mock_for(0.05, "noise", 0.97, probs_for("noise", 0.97))
        d = triage_email(jev, email())
        self.assertEqual(d["action"], "auto_archive")
        self.assertIsNone(d["label"])

    def test_noise_from_contact_is_contradiction(self):
        jev = mock_for(0.05, "noise", 0.97, probs_for("noise", 0.97))
        d = triage_email(jev, email(**{"from": "Rahul <rahul@gmail.com>"}), contacts=["rahul@gmail.com"])
        self.assertEqual(d["action"], "digest")
        self.assertTrue(any("contradiction" in r for r in d["reasons"]))

    def test_noise_below_archive_bar_goes_to_digest(self):
        jev = mock_for(0.05, "noise", 0.90, probs_for("noise", 0.90))
        d = triage_email(jev, email())
        self.assertEqual(d["action"], "digest")
        self.assertEqual(d["suggested"]["action"], "archive")

    def test_urgent_action_gets_p0(self):
        jev = mock_for(0.92, "needs_action", 0.93, probs_for("needs_action", 0.93))
        d = triage_email(jev, email(**{"from": "Acme Corp <ops@acme.co>"}))
        self.assertEqual(d["action"], "auto_label")
        self.assertEqual(d["label"], "InboxPilot/P0")

    def test_calm_fyi_gets_label(self):
        jev = mock_for(0.10, "fyi", 0.90, probs_for("fyi", 0.90))
        d = triage_email(jev, email())
        self.assertEqual(d["action"], "auto_label")
        self.assertEqual(d["label"], "InboxPilot/FYI")

    def test_ambiguous_top_two_escalates(self):
        p = probs_for("needs_action", 0.55, runnerup="fyi", p_run=0.45)
        jev = mock_for(0.80, "needs_action", 0.60, p)
        d = triage_email(jev, email())
        self.assertEqual(d["action"], "digest")
        self.assertTrue(any("too close" in r for r in d["reasons"]))

    def test_urgent_fyi_mismatch_escalates(self):
        jev = mock_for(0.88, "fyi", 0.90, probs_for("fyi", 0.90))
        d = triage_email(jev, email())
        self.assertEqual(d["action"], "digest")
        self.assertTrue(any("mismatch" in r for r in d["reasons"]))

    def test_low_confidence_escalates(self):
        jev = mock_for(0.10, "receipt", 0.60, probs_for("receipt", 0.60))
        d = triage_email(jev, email())
        self.assertEqual(d["action"], "digest")
        self.assertTrue(any("below the auto-label bar" in r for r in d["reasons"]))

    def test_uncertain_urgency_escalates(self):
        jev = mock_for(0.50, "needs_action", 0.90, probs_for("needs_action", 0.90))
        d = triage_email(jev, email())
        self.assertEqual(d["action"], "digest")
        self.assertTrue(any("Urgency uncertain" in r for r in d["reasons"]))

    def test_never_archives_possibly_urgent(self):
        # Even at 0.99 noise confidence, urgency 0.5 blocks auto-archive.
        jev = mock_for(0.50, "noise", 0.99, probs_for("noise", 0.99))
        d = triage_email(jev, email())
        self.assertNotEqual(d["action"], "auto_archive")

    def test_decision_carries_audit_fields(self):
        jev = mock_for(0.10, "fyi", 0.90, probs_for("fyi", 0.90))
        d = triage_email(jev, email(id="m9"))
        self.assertEqual(d["email_id"], "m9")
        self.assertIn("model", d)
        self.assertIn("reasons", d)
        self.assertTrue(len(jev.calls) == 1)


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(path=Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_round_trip(self):
        e = email(id="m1")
        self.store.save_email(e)
        jev = mock_for(0.10, "fyi", 0.90, probs_for("fyi", 0.90))
        d = triage_email(jev, e)
        self.store.save_decision("m1", d)
        got = self.store.get_decision("m1")
        self.assertEqual(got["action"], "auto_label")
        self.assertEqual(got["category"], "fyi")

    def test_digest_queue_and_review(self):
        jev = mock_for(0.50, "needs_action", 0.90, probs_for("needs_action", 0.90))
        d = triage_email(jev, email(id="m2"))
        self.store.save_email(email(id="m2"))
        self.store.save_decision("m2", d)
        pending = self.store.pending_digest()
        self.assertEqual(len(pending), 1)
        self.store.mark_reviewed("m2", approved=True)
        self.assertEqual(self.store.pending_digest(), [])

    def test_corrections_and_threshold_override(self):
        self.assertEqual(self.store.correction_count(), 0)
        self.store.record_correction("m1", "noise", False)
        self.assertEqual(self.store.correction_count(), 1)
        t = self.store.get_thresholds()
        self.assertAlmostEqual(t["tau_cat"], 0.85)
        self.store.set_threshold("tau_cat", 0.9)
        self.assertAlmostEqual(self.store.get_thresholds()["tau_cat"], 0.9)
        with self.assertRaises(KeyError):
            self.store.set_threshold("nope", 0.5)


if __name__ == "__main__":
    unittest.main()
