"""Tests for the threshold tuner: asymmetric-cost grid search on corrections."""

import tempfile
import unittest
from pathlib import Path

from inboxpilot.jev_client import MockSystemOneClient
from inboxpilot.store import Store
from inboxpilot.triage import CATEGORIES, triage_email
from inboxpilot.tuner import (
    COST_DIGEST,
    COST_WRONG_ARCHIVE,
    COST_WRONG_LABEL,
    REWARD_CORRECT_AUTO,
    format_report,
    tune,
    utility,
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


def probs_for(winner, p_win, runnerup=None, p_run=0.02):
    if runnerup is None:
        runnerup = "noise" if winner == "fyi" else "fyi"
    d = {c: 0.01 for c in CATEGORIES}
    d[winner] = p_win
    d[runnerup] = p_run
    return d


def email(eid, **kw):
    base = {
        "id": eid,
        "thread_id": "t-" + eid,
        "from": "promo@spam.example",
        "subject": "sale",
        "date": "2026-10-02",
        "snippet": "x",
        "body": "x",
        "labels": ["UNREAD"],
    }
    base.update(kw)
    return base


class TestUtility(unittest.TestCase):
    def test_digest_is_safe(self):
        self.assertEqual(
            utility({"action": "digest"}, "noise", False), COST_DIGEST
        )

    def test_correct_auto_label_rewarded(self):
        d = {"action": "auto_label", "label": "InboxPilot/P0"}
        self.assertEqual(
            utility(d, "needs_action", True), REWARD_CORRECT_AUTO
        )

    def test_wrong_label_penalized(self):
        d = {"action": "auto_label", "label": "InboxPilot/FYI"}
        self.assertEqual(utility(d, "newsletter", False), COST_WRONG_LABEL)

    def test_wrong_archive_is_catastrophic(self):
        d = {"action": "auto_archive"}
        self.assertEqual(utility(d, "fyi", False), COST_WRONG_ARCHIVE)
        self.assertEqual(
            utility({"action": "auto_archive"}, "noise", False),
            REWARD_CORRECT_AUTO,
        )


class TestTune(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(path=Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def _label_case(self, eid, urgency_p, category, conf, correct_category,
                    correct_urgent, sender="promo@spam.example"):
        e = email(eid, **{"from": sender})
        jev = mock_for(urgency_p, category, conf, probs_for(category, conf))
        d = triage_email(jev, e)
        self.store.save_email(e)
        self.store.save_decision(eid, d)
        self.store.record_correction(eid, correct_category, correct_urgent)
        return d

    def test_refuses_with_too_few_labels(self):
        self._label_case("a1", 0.05, "noise", 0.97, "noise", False)
        report = tune(self.store)
        self.assertFalse(report["applied"])
        self.assertEqual(report["after"]["tau_cat"], 0.85)  # unchanged
        self.assertTrue(any("at least 10" in n for n in report["notes"]))

    def test_grid_search_avoids_expensive_mistakes(self):
        # 3 correct archives, 3 correct P0s, 3 wrong labels, 3 wrong archives.
        for i in range(3):
            self._label_case(f"ok-a{i}", 0.05, "noise", 0.97, "noise", False)
            self._label_case(
                f"ok-b{i}", 0.85, "needs_action", 0.92, "needs_action", True,
                sender="customer@acme.co",
            )
            self._label_case(f"bad-c{i}", 0.10, "fyi", 0.87, "newsletter", False)
            self._label_case(f"bad-d{i}", 0.10, "noise", 0.96, "fyi", False)
        report = tune(self.store)
        self.assertTrue(report["applied"])
        self.assertTrue(report["provisional"])  # 12 < 50
        # Must raise the archive bar above the 0.96 wrong-archive confidence…
        self.assertGreater(report["after"]["tau_noise"], 0.96)
        # …and the label bar above the 0.87 wrong-label confidence.
        self.assertGreater(report["after"]["tau_cat"], 0.87)
        self.assertGreater(
            report["utility_after"], report["utility_before"]
        )
        # Closest-to-current tie-break: 0.90 not 0.95, 0.97 not 0.99.
        self.assertEqual(report["after"]["tau_cat"], 0.90)
        self.assertEqual(report["after"]["tau_noise"], 0.97)
        # Thresholds actually persisted.
        self.assertEqual(self.store.get_thresholds()["tau_noise"], 0.97)

    def test_format_report_readable(self):
        self._label_case("a1", 0.05, "noise", 0.97, "noise", False)
        text = format_report(tune(self.store))
        self.assertIn("Corrections used: 1", text)
        self.assertIn("tau_cat", text)


if __name__ == "__main__":
    unittest.main()
