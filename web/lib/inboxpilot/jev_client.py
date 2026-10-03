"""TypeSafe System-One wire client for InboxPilot.

One Jev call per email, three parallel atomic questions (see ARCHITECTURE.md §2).
Ground truth (verified from TypeSafe docs 2026-10-02):

* ``POST https://api.typesafe.ai/v1/systemone``
* Headers: ``Authorization: Bearer <TYPESAFE_API_KEY>``,
  ``Content-Type: application/json``, and a **real** User-Agent
  (Python urllib's default UA gets a firewall 403).
* Body: ``{"state": ..., "model": "jev-latest", "questions": {qid: {...}}}``.
  Question ids are client-side only — never sent to the model.
* Response: ``{"model": "jev-1.13.0", "answers": {qid: {...}},
  "usage": {"input_tokens": n, "output_tokens": m}}``.
* Pricing: $0.042 / million *input* tokens; output tokens free but reported.
* Errors: 401 bad key, 422 validation, 429 rate limit (honor Retry-After),
  529 overloaded. No streaming, no seed/temperature — responses are
  non-deterministic (1.3–2.2% flips), so we never cache across
  logically-distinct decisions.

Stdlib only (``urllib``) — the demo stays dependency-free.
"""

from __future__ import annotations

import json
import math
import os
import random
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

API_URL = "https://api.typesafe.ai/v1/systemone"
ENV_API_KEY = "TYPESAFE_API_KEY"
INPUT_USD_PER_MILLION_TOKENS = 0.042

# urllib's default UA ("Python-urllib/x.y") is blocked by TypeSafe's firewall.
USER_AGENT = "InboxPilot/0.1 (+https://github.com/AdityaPagare619/petu-labs)"

_VALID_QUESTION_TYPES = ("noul", "choice", "score")
_MAX_CHOICE_OPTIONS = 255          # per TypeSafe docs
_MIN_SCORE_LEVELS, _MAX_SCORE_LEVELS = 2, 10


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class JevError(Exception):
    """Base class for all System-One client errors."""


class JevConfigError(JevError):
    """Client misconfiguration (e.g. missing API key, malformed questions)."""


class JevAuthError(JevError):
    """HTTP 401 — the API key was rejected."""


class JevValidationError(JevError):
    """HTTP 422 — the server rejected the request (or the request was
    malformed client-side). Carries the server's message when available."""


class JevRateLimitError(JevError):
    """HTTP 429 — still rate-limited after exhausting retries."""


class JevOverloadedError(JevError):
    """HTTP 529 — the service stayed overloaded after exhausting retries."""


class JevConnectionError(JevError):
    """Transport-level failure (DNS, refused, TLS, timeout). Not retried."""


class JevResponseError(JevError):
    """The response was not valid JSON or did not match the answer schema."""


# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------

def estimate_cost_usd(input_tokens: int | float) -> float:
    """Cost of a request in USD: $0.042 per million *input* tokens.

    Output tokens are free (but still reported in ``usage``).
    """
    return float(input_tokens) / 1_000_000 * INPUT_USD_PER_MILLION_TOKENS


# ---------------------------------------------------------------------------
# Answer normalization
# ---------------------------------------------------------------------------

def normalize_answer(qid: str, raw: Mapping[str, Any]) -> Dict[str, Any]:
    """Convert one raw System-One answer to InboxPilot's normalized shape.

    Raw schemas (from TypeSafe docs):
      noul:   {"type": "noul", "noul": 0.91}                      # no confidence
      choice: {"type": "choice", "choice": "x",
               "probabilities": {...}, "confidence": 0.81}
      score:  {"type": "score", "score": 1.99, "legend": {...},
               "probabilities": {...}, "confidence": 0.99}

    Normalized shapes:
      {"type": "noul", "p": float}
      {"type": "choice", "choice": str, "probabilities": dict, "confidence": float}
      {"type": "score", "value": float, "probabilities": dict, "confidence": float}

    The score ``legend`` is presentation-only and is intentionally dropped:
    the normalized value is what the gating policy consumes.
    """
    if not isinstance(raw, Mapping):
        raise JevResponseError(f"answer {qid!r}: expected an object, got {type(raw).__name__}")
    atype = raw.get("type")
    if atype == "noul":
        return {"type": "noul", "p": _as_prob(qid, raw.get("noul"))}
    if atype == "choice":
        return {
            "type": "choice",
            "choice": _as_str(qid, "choice", raw.get("choice")),
            "probabilities": _as_prob_map(qid, raw.get("probabilities")),
            "confidence": _as_prob(qid, raw.get("confidence")),
        }
    if atype == "score":
        return {
            "type": "score",
            "value": _as_number(qid, "score", raw.get("score")),
            "probabilities": _as_prob_map(qid, raw.get("probabilities")),
            "confidence": _as_prob(qid, raw.get("confidence")),
        }
    raise JevResponseError(f"answer {qid!r}: unknown type {atype!r}")


def _as_prob(qid: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise JevResponseError(f"answer {qid!r}: expected a probability, got {value!r}")
    if not 0.0 <= float(value) <= 1.0:
        raise JevResponseError(f"answer {qid!r}: probability out of range: {value!r}")
    return float(value)


def _as_number(qid: str, field: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise JevResponseError(f"answer {qid!r}: expected a number for {field!r}, got {value!r}")
    return float(value)


def _as_str(qid: str, field: str, value: Any) -> str:
    if not isinstance(value, str):
        raise JevResponseError(f"answer {qid!r}: expected a string for {field!r}, got {value!r}")
    return value


def _as_prob_map(qid: str, value: Any) -> Dict[str, float]:
    if not isinstance(value, Mapping) or not value:
        raise JevResponseError(f"answer {qid!r}: expected a non-empty probabilities map")
    out: Dict[str, float] = {}
    for k, v in value.items():
        out[str(k)] = _as_prob(qid, v)
    return out


# ---------------------------------------------------------------------------
# The wire client
# ---------------------------------------------------------------------------

class SystemOneClient:
    """Thin client for ``POST /v1/systemone``.

    Args:
        api_key: TypeSafe API key. Defaults to the ``TYPESAFE_API_KEY``
            environment variable; raises :class:`JevConfigError` naming the
            variable if neither is available.
        model: Model tag sent in the request body. Pinned to ``"jev-1.13.0"``
            (the verified build from the ground-truth docs).
        timeout_s: Per-request socket timeout.
        max_retries: Number of *retries* after the first attempt on 429/529
            (so ``max_retries=4`` allows 5 attempts total).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "jev-1.13.0",
        timeout_s: float = 30,
        max_retries: int = 4,
        base_backoff_s: float = 1.0,
        max_backoff_s: float = 60.0,
        jitter_s: float = 1.0,
    ) -> None:
        key = api_key or os.environ.get(ENV_API_KEY)
        if not key:
            raise JevConfigError(
                f"No TypeSafe API key: pass api_key= explicitly or set the "
                f"{ENV_API_KEY} environment variable."
            )
        self.api_key = key
        self.model = model
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.base_backoff_s = base_backoff_s
        self.max_backoff_s = max_backoff_s
        self.jitter_s = jitter_s

    # -- public API --------------------------------------------------------

    def decide(
        self, state: Any, questions: Mapping[str, Mapping[str, Any]]
    ) -> Dict[str, Any]:
        """Ask Jev the triage questions for one email.

        Returns ``{"answers": {qid: normalized}, "usage": {"input_tokens": int,
        "output_tokens": int}, "model": str}``.
        """
        self._validate_questions(questions)
        payload = {"state": state, "model": self.model, "questions": dict(questions)}
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            API_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )
        raw = self._post_with_retries(request)
        return self._parse_response(raw)

    # -- transport ----------------------------------------------------------

    def _post_with_retries(self, request: urllib.request.Request) -> Dict[str, Any]:
        last_delay = 0.0
        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_s) as resp:
                    return self._read_json(resp)
            except urllib.error.HTTPError as exc:
                if exc.code == 401:
                    raise JevAuthError(
                        "TypeSafe rejected the API key (HTTP 401). "
                        "Check TYPESAFE_API_KEY."
                    ) from exc
                if exc.code == 422:
                    raise JevValidationError(
                        f"TypeSafe rejected the request (HTTP 422): {self._server_message(exc)}"
                    ) from exc
                if exc.code in (429, 529) and attempt < self.max_retries:
                    last_delay = self._retry_delay(exc, attempt)
                    time.sleep(last_delay)
                    continue
                if exc.code == 429:
                    raise JevRateLimitError(
                        f"Still rate-limited after {attempt + 1} attempts "
                        f"(last wait {last_delay:.1f}s). Honor the backoff and retry later."
                    ) from exc
                if exc.code == 529:
                    raise JevOverloadedError(
                        f"TypeSafe still overloaded after {attempt + 1} attempts. "
                        f"Degrade to digest-everything (fail-safe)."
                    ) from exc
                raise JevError(f"TypeSafe returned unexpected HTTP {exc.code}") from exc
            except urllib.error.URLError as exc:  # DNS / refused / TLS / timeout
                raise JevConnectionError(f"Could not reach {API_URL}: {exc.reason}") from exc
        # Unreachable: the loop either returns or raises on its final attempt.
        raise JevError("unreachable")  # pragma: no cover

    def _retry_delay(self, exc: urllib.error.HTTPError, attempt: int) -> float:
        """Backoff honoring Retry-After when the server sends one.

        Retry-After (delta-seconds) takes precedence; otherwise exponential
        ``base * 2**attempt`` capped at ``max_backoff_s``. A small uniform
        jitter is added in both cases to avoid thundering herds.
        """
        jitter = random.uniform(0, self.jitter_s)
        retry_after = self._parse_retry_after(exc)
        if retry_after is not None:
            return min(retry_after, self.max_backoff_s) + jitter
        return min(self.base_backoff_s * (2 ** attempt), self.max_backoff_s) + jitter

    @staticmethod
    def _parse_retry_after(exc: urllib.error.HTTPError) -> Optional[float]:
        raw = exc.headers.get("Retry-After") if exc.headers else None
        if raw is None:
            return None
        try:
            value = float(str(raw).strip())
        except ValueError:
            return None  # HTTP-date form or garbage: fall back to backoff
        return value if value >= 0 else None

    @staticmethod
    def _server_message(exc: urllib.error.HTTPError) -> str:
        """Extract the server's 422 explanation from the response body."""
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - best effort on an error path
            return "(unreadable response body)"
        if not body.strip():
            return "(empty response body)"
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return body[:500]
        if isinstance(data, Mapping):
            for key in ("message", "error", "detail", "msg"):
                if isinstance(data.get(key), str) and data[key].strip():
                    return data[key].strip()
        return body[:500]

    @staticmethod
    def _read_json(resp: Any) -> Dict[str, Any]:
        try:
            data = json.loads(resp.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise JevResponseError(f"TypeSafe returned a non-JSON response: {exc}") from exc
        if not isinstance(data, Mapping):
            raise JevResponseError("TypeSafe response was not a JSON object")
        return dict(data)

    # -- request validation --------------------------------------------------

    @staticmethod
    def _validate_questions(questions: Mapping[str, Mapping[str, Any]]) -> None:
        """Fail fast on question shapes TypeSafe would 422 anyway.

        Enforces the doc constraints: valid ``type``, non-empty
        ``instructions``, Choice criteria = option->description map with at
        most 255 options, Score criteria = ordered array of 2–10 levels.
        """
        if not isinstance(questions, Mapping) or not questions:
            raise JevConfigError("questions must be a non-empty mapping of qid -> question")
        for qid, q in questions.items():
            if not isinstance(q, Mapping):
                raise JevConfigError(f"question {qid!r}: expected a mapping")
            qtype = q.get("type")
            if qtype not in _VALID_QUESTION_TYPES:
                raise JevConfigError(
                    f"question {qid!r}: type must be one of {_VALID_QUESTION_TYPES}, got {qtype!r}"
                )
            if not isinstance(q.get("instructions"), str) or not q["instructions"].strip():
                raise JevConfigError(f"question {qid!r}: 'instructions' must be a non-empty string")
            criteria = q.get("criteria")
            if qtype == "choice":
                if not isinstance(criteria, Mapping) or not criteria:
                    raise JevConfigError(f"question {qid!r}: choice 'criteria' must be a non-empty option->description map")
                if len(criteria) > _MAX_CHOICE_OPTIONS:
                    raise JevConfigError(
                        f"question {qid!r}: choice has {len(criteria)} options; max is {_MAX_CHOICE_OPTIONS}"
                    )
                for opt, desc in criteria.items():
                    if not isinstance(desc, str) or not desc.strip():
                        raise JevConfigError(f"question {qid!r}: option {opt!r} needs a one-line description (bare labels fail)")
            elif qtype == "score":
                if not isinstance(criteria, Sequence) or isinstance(criteria, (str, bytes)):
                    raise JevConfigError(f"question {qid!r}: score 'criteria' must be an ordered array of level descriptions")
                if not (_MIN_SCORE_LEVELS <= len(criteria) <= _MAX_SCORE_LEVELS):
                    raise JevConfigError(
                        f"question {qid!r}: score needs {_MIN_SCORE_LEVELS}–{_MAX_SCORE_LEVELS} levels, got {len(criteria)}"
                    )
                for level in criteria:
                    if not isinstance(level, str) or not level.strip():
                        raise JevConfigError(f"question {qid!r}: every score level needs a description string")

    # -- response parsing -----------------------------------------------------

    def _parse_response(self, data: Mapping[str, Any]) -> Dict[str, Any]:
        answers_raw = data.get("answers")
        if not isinstance(answers_raw, Mapping):
            raise JevResponseError("TypeSafe response has no 'answers' object")
        answers = {qid: normalize_answer(qid, raw) for qid, raw in answers_raw.items()}
        usage_raw = data.get("usage") or {}
        usage = {
            "input_tokens": int(usage_raw.get("input_tokens") or 0),
            "output_tokens": int(usage_raw.get("output_tokens") or 0),
        }
        return {
            "answers": answers,
            "usage": usage,
            "model": str(data.get("model") or self.model),
        }


# ---------------------------------------------------------------------------
# Mock client (tests + keyless demo)
# ---------------------------------------------------------------------------

#: A scripted answer: either a *normalized* answer dict, or a callable
#: ``(state, questions) -> normalized answer dict``.
ScriptEntry = Any


class MockSystemOneClient:
    """Drop-in stand-in for :class:`SystemOneClient` with scripted answers.

    ``script`` maps qid -> canned normalized answer OR
    ``callable(state, questions) -> answer``. Every :meth:`decide` call is
    recorded in :attr:`calls` as ``{"state": ..., "questions": ...}`` for
    assertions. No network, no key — used by tests and the keyless demo.
    """

    def __init__(self, script: Mapping[str, ScriptEntry], model: str = "mock") -> None:
        self.script = dict(script)
        self.model = model
        self.calls: list[Dict[str, Any]] = []

    def decide(
        self, state: Any, questions: Mapping[str, Mapping[str, Any]]
    ) -> Dict[str, Any]:
        self.calls.append({"state": state, "questions": dict(questions)})
        answers: Dict[str, Any] = {}
        for qid in questions:
            if qid not in self.script:
                raise AssertionError(f"mock has no scripted answer for qid {qid!r}")
            entry = self.script[qid]
            answers[qid] = entry(state, questions) if callable(entry) else entry
        return {
            "answers": answers,
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "model": self.model,
        }

    def estimate_cost_usd(self, input_tokens: int | float) -> float:  # noqa: D102
        return estimate_cost_usd(input_tokens)
