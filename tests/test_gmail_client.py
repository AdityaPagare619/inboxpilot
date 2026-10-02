"""Tests for inboxpilot.gmail_client — fixture backend, body extraction,
write-scope gating, and token file permissions.

No network is touched by any test: everything runs against
tests/fixtures/fixture_inbox.json. Run from the inboxpilot root:

    python3 -m unittest discover -s tests -v
"""

import json
import os
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from inboxpilot.gmail_client import (  # noqa: E402
    SNIPPET_MAX_CHARS,
    GmailClient,
    GmailMessageNotFoundError,
    GmailScopeError,
    MODIFY_SCOPE,
    READONLY_SCOPE,
    _load_token,
    _save_token,
    extract_body,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                       "fixture_inbox.json")


def b64url_nopad(text: str) -> str:
    import base64
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def make_client(**kwargs) -> GmailClient:
    kwargs.setdefault("fixture_path", FIXTURE)
    return GmailClient(**kwargs)


class TestFixtureListGet(unittest.TestCase):
    def setUp(self):
        self.client = make_client()

    def test_fixture_mode_flag(self):
        self.assertTrue(self.client.fixture_mode)

    def test_list_unread_returns_ids(self):
        ids = self.client.list_unread()
        self.assertEqual(len(ids), 21)  # 21 of 25 fixture messages are UNREAD
        self.assertTrue(all(isinstance(i, str) for i in ids))
        self.assertEqual(len(set(ids)), len(ids))  # no duplicates

    def test_list_unread_respects_max_n(self):
        ids = self.client.list_unread(max_n=5)
        self.assertEqual(len(ids), 5)

    def test_list_unread_only_returns_unread(self):
        for mid in self.client.list_unread(max_n=50):
            m = self.client.get_message(mid)
            self.assertIn("UNREAD", m["labels"], mid)

    def test_get_message_round_trip_keys(self):
        mid = self.client.list_unread(max_n=1)[0]
        m = self.client.get_message(mid)
        self.assertEqual(
            set(m.keys()),
            {"id", "thread_id", "from", "subject", "date",
             "snippet", "body", "labels"},
        )
        self.assertEqual(m["id"], mid)
        self.assertTrue(m["from"] and m["subject"] and m["date"])
        self.assertTrue(m["body"])
        self.assertLessEqual(len(m["snippet"]), SNIPPET_MAX_CHARS)

    def test_get_message_unknown_id_raises(self):
        with self.assertRaises(GmailMessageNotFoundError):
            self.client.get_message("no-such-message")


class TestBodyExtraction(unittest.TestCase):
    def test_prefers_text_plain_over_html(self):
        payload = {
            "mimeType": "multipart/alternative",
            "parts": [
                {"mimeType": "text/html",
                 "body": {"data": b64url_nopad("<p>HTML version</p>")}},
                {"mimeType": "text/plain",
                 "body": {"data": b64url_nopad("plain version")}},
            ],
        }
        self.assertEqual(extract_body(payload), "plain version")

    def test_walks_nested_multipart(self):
        payload = {
            "mimeType": "multipart/mixed",
            "parts": [
                {"mimeType": "multipart/alternative",
                 "parts": [
                     {"mimeType": "text/plain",
                      "body": {"data": b64url_nopad("nested plain")}},
                 ]},
                {"mimeType": "application/pdf", "filename": "a.pdf",
                 "body": {"attachmentId": "att1", "size": 10}},
            ],
        }
        self.assertEqual(extract_body(payload), "nested plain")

    def test_html_fallback_strips_tags(self):
        payload = {
            "mimeType": "text/html",
            "body": {"data": b64url_nopad(
                "<html><body><h1>Hi</h1><p>Click <a href='x'>here</a></p>"
                "<script>evil()</script></body></html>")},
        }
        text = extract_body(payload)
        self.assertIn("Hi", text)
        self.assertIn("here", text)
        self.assertNotIn("<", text)
        self.assertNotIn("evil()", text)

    def test_base64url_without_padding(self):
        # "hello world" -> padding stripped, as the real API does
        payload = {"mimeType": "text/plain",
                   "body": {"data": "aGVsbG8gd29ybGQ"}}
        self.assertEqual(extract_body(payload), "hello world")

    def test_attachments_skipped(self):
        payload = {
            "mimeType": "multipart/mixed",
            "parts": [
                {"mimeType": "application/pdf",
                 "body": {"attachmentId": "att1"}},
            ],
        }
        self.assertEqual(extract_body(payload), "")

    def test_fixture_multipart_message_extracted(self):
        # msg-020 (AWS invoice) is multipart in the fixture; the loader must
        # have run the real extraction path.
        client = make_client()
        m = client.get_message("msg-020")
        self.assertIn("$312.44", m["body"])
        self.assertNotIn("attachmentId", m["body"])

    def test_fixture_html_only_message_extracted(self):
        # msg-006 (spam) is HTML-only in the fixture.
        client = make_client()
        m = client.get_message("msg-006")
        self.assertIn("ELON MUSK CRYPTO GIVEAWAY", m["body"])
        self.assertNotIn("<h1>", m["body"])


class TestSnippetTruncation(unittest.TestCase):
    def test_long_body_snippet_capped(self):
        client = make_client()
        m = client.get_message("msg-023")  # the long "per my last email"
        self.assertGreater(len(m["body"]), SNIPPET_MAX_CHARS)
        self.assertLessEqual(len(m["snippet"]), SNIPPET_MAX_CHARS)
        self.assertTrue(m["body"].startswith(m["snippet"]))


class TestApplyLabelFixture(unittest.TestCase):
    def test_apply_label_recorded_in_memory(self):
        client = make_client(scopes=(READONLY_SCOPE, MODIFY_SCOPE))
        mid = client.list_unread(max_n=1)[0]
        client.apply_label(mid, "p0")
        client.apply_label(mid, "needs-action")
        self.assertEqual(client.applied_labels,
                         [(mid, "p0"), (mid, "needs-action")])
        # ...and reflected on the message itself
        self.assertIn("p0", client.get_message(mid)["labels"])

    def test_enable_write_adds_modify_scope(self):
        client = make_client(enable_write=True)
        self.assertIn(MODIFY_SCOPE, client.granted_scopes)
        mid = client.list_unread(max_n=1)[0]
        client.apply_label(mid, "p0")  # must not raise
        self.assertEqual(client.applied_labels, [(mid, "p0")])

    def test_apply_label_unknown_message_raises(self):
        client = make_client(scopes=(READONLY_SCOPE, MODIFY_SCOPE))
        with self.assertRaises(GmailMessageNotFoundError):
            client.apply_label("no-such-message", "p0")


class TestWriteScopeGate(unittest.TestCase):
    def test_readonly_client_apply_label_raises_clearly(self):
        client = make_client()  # default scopes: gmail.readonly only
        self.assertNotIn(MODIFY_SCOPE, client.granted_scopes)
        mid = client.list_unread(max_n=1)[0]
        with self.assertRaises(GmailScopeError) as ctx:
            client.apply_label(mid, "p0")
        message = str(ctx.exception)
        self.assertIn("gmail.modify", message)
        self.assertIn("enable_write=True", message)
        # Nothing must have been recorded.
        self.assertEqual(client.applied_labels, [])

    def test_explicit_modify_scope_allows_label(self):
        client = make_client(scopes=(MODIFY_SCOPE,))
        mid = client.list_unread(max_n=1)[0]
        client.apply_label(mid, "fyi")
        self.assertEqual(client.applied_labels, [(mid, "fyi")])


class TestTokenFilePerms(unittest.TestCase):
    def test_save_token_writes_0600(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "token.json")
            _save_token(path, {"access_token": "x", "refresh_token": "y"})
            mode = stat.S_IMODE(os.stat(path).st_mode)
            self.assertEqual(mode, 0o600, f"mode was {oct(mode)}")

    def test_save_token_fixes_existing_perms(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "token.json")
            with open(path, "w") as f:
                f.write("{}")
            os.chmod(path, 0o644)
            _save_token(path, {"access_token": "x"})
            mode = stat.S_IMODE(os.stat(path).st_mode)
            self.assertEqual(mode, 0o600, f"mode was {oct(mode)}")

    def test_token_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "token.json")
            token = {"access_token": "abc", "refresh_token": "def",
                     "expires_at": 123.0, "scope": READONLY_SCOPE}
            _save_token(path, token)
            self.assertEqual(_load_token(path), token)

    def test_load_missing_token_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(
                _load_token(os.path.join(d, "does-not-exist.json")))


class TestFixtureCoverage(unittest.TestCase):
    """The fixture must contain every scenario the brief requires."""

    def setUp(self):
        with open(FIXTURE, encoding="utf-8") as f:
            self.fixture = json.load(f)
        self.by_id = {m["id"]: m for m in self.fixture["messages"]}

    def test_message_count(self):
        self.assertGreaterEqual(len(self.fixture["messages"]), 25)

    def test_required_scenarios_present(self):
        subjects = " ".join(m["subject"] for m in
                            self.fixture["messages"]).lower()
        bodies = " ".join(m.get("body", "") for m in self.fixture["messages"])
        self.assertIn("monthly update", subjects)          # investor update
        self.assertIn("dashboard down", subjects)          # customer escalation
        self.assertIn("invoice", subjects)                 # invoice receipt
        self.assertIn("techcrunch", subjects)              # newsletter
        self.assertIn("50% off", subjects)                 # promo blast
        self.assertIn("giveaway", subjects)                # obvious spam
        self.assertIn("pricing tiers", subjects)           # asked a question
        self.assertIn("launch checklist", subjects)        # founder replied
        self.assertIn("per my last email", bodies.lower())  # ambiguous
        # contact-that-looks-like-noise: Rahul's meme from a personal address
        meme = self.by_id["msg-022"]
        self.assertIn("gmail.com", meme["from"])
        self.assertIn("youtube.com", meme["body"])

    def test_thread_where_founder_replied_is_read(self):
        # msg-016: Priya confirming after the founder replied — already read,
        # so it must NOT appear in list_unread.
        self.assertNotIn("UNREAD", self.by_id["msg-016"]["labels"])
        client = make_client()
        self.assertNotIn("msg-016", client.list_unread(max_n=50))


class TestWritePrimitives(unittest.TestCase):
    def test_remove_label_needs_modify_scope(self):
        client = make_client()  # readonly by default
        with self.assertRaises(GmailScopeError):
            client.remove_label("msg-001", "InboxPilot/FYI")
        with self.assertRaises(GmailScopeError):
            client.set_archived("msg-001", True)

    def test_remove_label_fixture(self):
        client = make_client(enable_write=True)
        client.apply_label("msg-001", "InboxPilot/FYI")
        client.remove_label("msg-001", "InboxPilot/FYI")
        labels = client.get_message("msg-001")["labels"]
        self.assertNotIn("InboxPilot/FYI", labels)

    def test_archive_is_inbox_removal_not_delete(self):
        client = make_client(enable_write=True)
        self.assertIn("INBOX", client.get_message("msg-006")["labels"])
        client.set_archived("msg-006", True)
        labels = client.get_message("msg-006")["labels"]
        self.assertNotIn("INBOX", labels)
        # …and unarchive restores it. Nothing is ever deleted.
        client.set_archived("msg-006", False)
        self.assertIn("INBOX", client.get_message("msg-006")["labels"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
