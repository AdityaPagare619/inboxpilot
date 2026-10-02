"""Unit tests for inboxpilot.jev_client — no network, no keys.

Run from the repo root:  python3 -m unittest discover -s tests -v
Stdlib only.
"""

import io
import json
import os
import sys
import unittest
from email.message import Message
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from inboxpilot import jev_client
from inboxpilot.jev_client import (
    JevAuthError,
    JevConfigError,
    JevOverloadedError,
    JevRateLimitError,
    JevResponseError,
    JevValidationError,
    MockSystemOneClient,
    SystemOneClient,
    estimate_cost_usd,
)

# Question set from ARCHITECTURE.md §2 (the real triage questions).
QUESTIONS = {
    "urgency": {
        "type": "noul",
        "instructions": "Does this email need the founder's attention within 24h?",
    },
    "category": {
        "type": "choice",
        "instructions": "Classify this email into exactly one bucket.",
        "criteria": {
            "needs_action": "Requires the recipient to do something: reply, decide, approve, pay, or sign.",
            "fyi": "Informational only. No action needed, but worth knowing.",
            "receipt": "Transactional record: receipts, order confirmations, notifications of already-completed actions.",
            "newsletter": "Bulk or marketing content: newsletters, promotions, announcements.",
            "noise": "Spam-like, irrelevant, or safe to ignore entirely.",
        },
    },
    "needs_reply": {
        "type": "noul",
        "instructions": "Is this thread awaiting the recipient's response?",
    },
}

STATE = {
    "subject": "Invoice #4821 overdue",
    "from": "billing@acmewidgets.com",
    "body": "Your invoice of $4,200 is 30 days overdue. Please remit payment.",
    "sender_in_contacts": True,
}

RAW_NOUL = {"type": "noul", "noul": 0.91}
RAW_CHOICE = {
    "type": "choice",
    "choice": "needs_action",
    "probabilities": {
        "needs_action": 0.70,
        "fyi": 0.20,
        "receipt": 0.05,
        "newsletter": 0.03,
        "noise": 0.02,
    },
    "confidence": 0.81,
}
RAW_SCORE = {
    "type": "score",
    "score": 1.99,
    "legend": {"0": "Low", "1": "Medium", "2": "High"},
    "probabilities": {"0": 0.10, "1": 0.72, "2": 0.18},
    "confidence": 0.99,
}


def make_response(answers, usage=None, model="jev-1.13.0"):
    payload = {
        "model": model,
        "answers": answers,
        "usage": usage or {"input_tokens": 1234, "output_tokens": 7},
    }
    return json.dumps(payload).encode("utf-8")


class FakeHTTPResponse:
    """Minimal stand-in for the object returned by urllib.request.urlopen."""

    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code, headers=None, body=b""):
    import urllib.error

    hdrs = Message()
    for k, v in (headers or {}).items():
        hdrs[k] = v
    return urllib.error.HTTPError(
        jev_client.API_URL, code, f"HTTP {code}", hdrs, io.BytesIO(body)
    )


class ClientTestCase(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-key-123"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def client(self, **kwargs):
        kwargs.setdefault("max_retries", 4)
        return SystemOneClient(**kwargs)

    def run_decide(self, fake_urlopen, **kwargs):
        with mock.patch("urllib.request.urlopen", fake_urlopen):
            return self.client(**kwargs).decide(STATE, QUESTIONS)


# ---------------------------------------------------------------------------
# Answer parsing
# ---------------------------------------------------------------------------

class ParsingTests(ClientTestCase):
    def test_noul_answer_normalizes_to_p(self):
        result = self.run_decide(
            lambda *a, **k: FakeHTTPResponse(
                make_response({"urgency": RAW_NOUL, "category": RAW_CHOICE, "needs_reply": RAW_NOUL})
            )
        )
        self.assertEqual(
            result["answers"]["urgency"], {"type": "noul", "p": 0.91}
        )

    def test_choice_answer_keeps_choice_probabilities_confidence(self):
        result = self.run_decide(
            lambda *a, **k: FakeHTTPResponse(
                make_response({"urgency": RAW_NOUL, "category": RAW_CHOICE, "needs_reply": RAW_NOUL})
            )
        )
        ans = result["answers"]["category"]
        self.assertEqual(ans["type"], "choice")
        self.assertEqual(ans["choice"], "needs_action")
        self.assertAlmostEqual(ans["confidence"], 0.81)
        self.assertAlmostEqual(ans["probabilities"]["needs_action"], 0.70)
        self.assertEqual(len(ans["probabilities"]), 5)

    def test_score_answer_normalizes_to_value_and_drops_legend(self):
        questions = {
            "priority": {
                "type": "score",
                "instructions": "How important is this?",
                "criteria": ["Low", "Medium", "High"],
            }
        }
        with mock.patch(
            "urllib.request.urlopen",
            lambda *a, **k: FakeHTTPResponse(make_response({"priority": RAW_SCORE})),
        ):
            result = self.client().decide(STATE, questions)
        ans = result["answers"]["priority"]
        self.assertEqual(
            ans,
            {
                "type": "score",
                "value": 1.99,
                "probabilities": {"0": 0.10, "1": 0.72, "2": 0.18},
                "confidence": 0.99,
            },
        )

    def test_usage_and_model_pass_through(self):
        result = self.run_decide(
            lambda *a, **k: FakeHTTPResponse(
                make_response(
                    {"urgency": RAW_NOUL, "category": RAW_CHOICE, "needs_reply": RAW_NOUL},
                    usage={"input_tokens": 1500, "output_tokens": 12},
                    model="jev-1.13.0",
                )
            )
        )
        self.assertEqual(result["usage"], {"input_tokens": 1500, "output_tokens": 12})
        self.assertEqual(result["model"], "jev-1.13.0")

    def test_unknown_answer_type_raises(self):
        with mock.patch(
            "urllib.request.urlopen",
            lambda *a, **k: FakeHTTPResponse(
                make_response({"urgency": {"type": "mystery", "x": 1},
                               "category": RAW_CHOICE, "needs_reply": RAW_NOUL})
            ),
        ):
            with self.assertRaises(JevResponseError):
                self.client().decide(STATE, QUESTIONS)

    def test_missing_answers_object_raises(self):
        body = json.dumps({"model": "jev-1.13.0"}).encode()
        with mock.patch(
            "urllib.request.urlopen", lambda *a, **k: FakeHTTPResponse(body)
        ):
            with self.assertRaises(JevResponseError):
                self.client().decide(STATE, QUESTIONS)

    def test_non_json_response_raises(self):
        with mock.patch(
            "urllib.request.urlopen", lambda *a, **k: FakeHTTPResponse(b"<html>nope</html>")
        ):
            with self.assertRaises(JevResponseError):
                self.client().decide(STATE, QUESTIONS)


# ---------------------------------------------------------------------------
# Wire format
# ---------------------------------------------------------------------------

class WireFormatTests(ClientTestCase):
    def test_request_headers_body_and_ua(self):
        seen = {}

        def fake(req, timeout=None):
            seen["url"] = req.full_url
            seen["auth"] = req.get_header("Authorization")
            seen["content_type"] = req.get_header("Content-type")
            seen["ua"] = req.get_header("User-agent")
            seen["body"] = json.loads(req.data.decode("utf-8"))
            return FakeHTTPResponse(
                make_response({"urgency": RAW_NOUL, "category": RAW_CHOICE, "needs_reply": RAW_NOUL})
            )

        with mock.patch("urllib.request.urlopen", fake):
            self.client().decide(STATE, QUESTIONS)

        self.assertEqual(seen["url"], jev_client.API_URL)
        self.assertEqual(seen["auth"], "Bearer test-key-123")
        self.assertEqual(seen["content_type"], "application/json")
        # urllib's default UA ("Python-urllib/...") gets a firewall 403 — must not be sent.
        self.assertNotIn("Python-urllib", seen["ua"])
        self.assertTrue(seen["ua"], "User-Agent must be set")
        body = seen["body"]
        self.assertEqual(body["state"], STATE)
        self.assertEqual(body["model"], "jev-1.13.0")
        self.assertEqual(set(body["questions"]), {"urgency", "category", "needs_reply"})

    def test_custom_model_tag_is_sent(self):
        seen = {}

        def fake(req, timeout=None):
            seen["body"] = json.loads(req.data.decode("utf-8"))
            return FakeHTTPResponse(
                make_response({"urgency": RAW_NOUL, "category": RAW_CHOICE, "needs_reply": RAW_NOUL})
            )

        with mock.patch("urllib.request.urlopen", fake):
            self.client(model="jev-latest").decide(STATE, QUESTIONS)
        self.assertEqual(seen["body"]["model"], "jev-latest")


# ---------------------------------------------------------------------------
# Retry behavior
# ---------------------------------------------------------------------------

class RetryTests(ClientTestCase):
    def _answers(self):
        return {"urgency": RAW_NOUL, "category": RAW_CHOICE, "needs_reply": RAW_NOUL}

    def test_429_then_200_honors_retry_after(self):
        calls = {"n": 0}
        sleeps = []

        def fake(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise http_error(429, headers={"Retry-After": "2"})
            return FakeHTTPResponse(make_response(self._answers()))

        with mock.patch("urllib.request.urlopen", fake), mock.patch(
            "time.sleep", sleeps.append
        ):
            result = self.client(max_retries=4).decide(STATE, QUESTIONS)

        self.assertEqual(calls["n"], 2, "should retry exactly once after the 429")
        self.assertEqual(len(sleeps), 1)
        # Retry-After: 2 honored, plus small uniform jitter (0..1s).
        self.assertGreaterEqual(sleeps[0], 2.0)
        self.assertLess(sleeps[0], 3.5)
        self.assertEqual(result["answers"]["urgency"]["p"], 0.91)

    def test_529_backoff_is_exponential_without_retry_after(self):
        sleeps = []

        def fake(*a, **k):
            raise http_error(529)

        with mock.patch("urllib.request.urlopen", fake), mock.patch(
            "time.sleep", sleeps.append
        ):
            with self.assertRaises(JevOverloadedError):
                self.client(max_retries=3, base_backoff_s=1.0, jitter_s=0.0).decide(
                    STATE, QUESTIONS
                )
        # attempts at t=0, then waits ~1, ~2, ~4 before attempts 2,3,4
        self.assertEqual(len(sleeps), 3)
        self.assertAlmostEqual(sleeps[0], 1.0)
        self.assertAlmostEqual(sleeps[1], 2.0)
        self.assertAlmostEqual(sleeps[2], 4.0)

    def test_429_exhausted_raises_rate_limit_error(self):
        calls = {"n": 0}

        def fake(*a, **k):
            calls["n"] += 1
            raise http_error(429)

        with mock.patch("urllib.request.urlopen", fake), mock.patch("time.sleep"):
            with self.assertRaises(JevRateLimitError):
                self.client(max_retries=2, jitter_s=0.0).decide(STATE, QUESTIONS)
        self.assertEqual(calls["n"], 3, "1 initial attempt + 2 retries")

    def test_401_raises_auth_error_without_retry(self):
        calls = {"n": 0}

        def fake(*a, **k):
            calls["n"] += 1
            raise http_error(401)

        with mock.patch("urllib.request.urlopen", fake):
            with self.assertRaises(JevAuthError):
                self.client().decide(STATE, QUESTIONS)
        self.assertEqual(calls["n"], 1, "401 must not be retried")

    def test_422_raises_validation_error_with_server_message(self):
        body = json.dumps({"message": "questions.category.criteria: too many options"}).encode()

        def fake(*a, **k):
            raise http_error(422, body=body)

        with mock.patch("urllib.request.urlopen", fake):
            with self.assertRaises(JevValidationError) as ctx:
                self.client().decide(STATE, QUESTIONS)
        self.assertIn("too many options", str(ctx.exception))
        self.assertIn("422", str(ctx.exception))

    def test_500_raises_generic_jev_error(self):
        def fake(*a, **k):
            raise http_error(500)

        with mock.patch("urllib.request.urlopen", fake):
            with self.assertRaises(jev_client.JevError):
                self.client().decide(STATE, QUESTIONS)


# ---------------------------------------------------------------------------
# Configuration & validation
# ---------------------------------------------------------------------------

class ConfigTests(unittest.TestCase):
    def test_missing_env_var_raises_naming_the_var(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(JevConfigError) as ctx:
                SystemOneClient()
        self.assertIn("TYPESAFE_API_KEY", str(ctx.exception))

    def test_env_var_is_used_when_no_explicit_key(self):
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "env-key"}):
            self.assertEqual(SystemOneClient().api_key, "env-key")

    def test_explicit_key_beats_env(self):
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "env-key"}):
            self.assertEqual(SystemOneClient(api_key="explicit").api_key, "explicit")

    def test_bad_question_type_rejected_client_side(self):
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "k"}):
            client = SystemOneClient()
        with self.assertRaises(JevConfigError):
            client.decide(STATE, {"q": {"type": "vibes", "instructions": "??"}})

    def test_empty_instructions_rejected_client_side(self):
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "k"}):
            client = SystemOneClient()
        with self.assertRaises(JevConfigError):
            client.decide(STATE, {"q": {"type": "noul", "instructions": "  "}})

    def test_choice_with_256_options_rejected_client_side(self):
        criteria = {f"opt{i}": f"description {i}" for i in range(256)}
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "k"}):
            client = SystemOneClient()
        with self.assertRaises(JevConfigError) as ctx:
            client.decide(STATE, {"q": {"type": "choice", "instructions": "x", "criteria": criteria}})
        self.assertIn("255", str(ctx.exception))

    def test_choice_with_bare_label_rejected_client_side(self):
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "k"}):
            client = SystemOneClient()
        with self.assertRaises(JevConfigError):
            client.decide(
                STATE,
                {"q": {"type": "choice", "instructions": "x", "criteria": {"a": ""}}},
            )

    def test_score_with_one_level_rejected_client_side(self):
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "k"}):
            client = SystemOneClient()
        with self.assertRaises(JevConfigError):
            client.decide(
                STATE,
                {"q": {"type": "score", "instructions": "x", "criteria": ["only"]}},
            )


# ---------------------------------------------------------------------------
# Mock client
# ---------------------------------------------------------------------------

class MockClientTests(unittest.TestCase):
    SCRIPT = {
        "urgency": {"type": "noul", "p": 0.12},
        "category": {
            "type": "choice",
            "choice": "newsletter",
            "probabilities": {"newsletter": 0.9, "noise": 0.1},
            "confidence": 0.93,
        },
        "needs_reply": lambda state, questions: {"type": "noul", "p": 0.02},
    }

    def test_canned_answers_returned_verbatim(self):
        mock_client = MockSystemOneClient(self.SCRIPT)
        result = mock_client.decide(STATE, QUESTIONS)
        self.assertEqual(result["answers"]["urgency"], {"type": "noul", "p": 0.12})
        self.assertEqual(result["answers"]["category"]["choice"], "newsletter")
        self.assertEqual(result["usage"], {"input_tokens": 0, "output_tokens": 0})

    def test_callable_receives_state_and_questions(self):
        seen = {}

        def answer(state, questions):
            seen["state"] = state
            seen["questions"] = questions
            return {"type": "noul", "p": 0.5}

        mock_client = MockSystemOneClient({"q": answer})
        result = mock_client.decide(STATE, {"q": {"type": "noul", "instructions": "x"}})
        self.assertEqual(seen["state"], STATE)
        self.assertEqual(set(seen["questions"]), {"q"})
        self.assertEqual(result["answers"]["q"]["p"], 0.5)

    def test_calls_are_recorded(self):
        mock_client = MockSystemOneClient(self.SCRIPT)
        mock_client.decide(STATE, QUESTIONS)
        mock_client.decide(STATE, {"urgency": QUESTIONS["urgency"]})
        self.assertEqual(len(mock_client.calls), 2)
        self.assertEqual(mock_client.calls[0]["state"], STATE)
        self.assertEqual(set(mock_client.calls[1]["questions"]), {"urgency"})

    def test_unscripted_qid_raises(self):
        mock_client = MockSystemOneClient({"urgency": {"type": "noul", "p": 0.1}})
        with self.assertRaises(AssertionError):
            mock_client.decide(STATE, QUESTIONS)


# ---------------------------------------------------------------------------
# Cost math
# ---------------------------------------------------------------------------

class CostTests(unittest.TestCase):
    def test_one_million_input_tokens_costs_4_2_cents(self):
        self.assertAlmostEqual(estimate_cost_usd(1_000_000), 0.042)

    def test_typical_email_cost(self):
        # 1,500 tokens/email (ARCHITECTURE.md §2, §9): 1500/1e6 * 0.042
        self.assertAlmostEqual(estimate_cost_usd(1500), 0.000063)

    def test_zero_tokens_is_free(self):
        self.assertEqual(estimate_cost_usd(0), 0.0)


if __name__ == "__main__":
    unittest.main()
