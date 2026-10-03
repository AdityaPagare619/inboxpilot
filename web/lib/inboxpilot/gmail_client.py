"""Gmail ingestion for InboxPilot.

One interface, two backends:

- **Fixture mode** (``fixture_path`` given): serves tests and ``inboxpilot
  demo`` from a local JSON inbox. ALL network paths are disabled — no HTTP,
  no OAuth, nothing leaves the machine.
- **Real mode**: Gmail API access via the OAuth2 installed-app flow, using
  only the standard library (``urllib`` + ``http.server``).

Scopes are minimal by default: ``gmail.readonly`` only. ``gmail.modify`` is
requested ONLY when the caller passes ``enable_write=True`` (i.e. the user
explicitly enabled auto-label), and a plain-language explanation is logged
at that point. Label application always checks the granted scopes and raises
a clear error when ``gmail.modify`` is missing.

Setup for the real path (10 minutes, done once by the human):
see ``docs/gmail-setup.md``. The OAuth client credentials come from a
``client_secret.json`` the user downloads from their own Google Cloud
project (Desktop client ID) and places at
``~/.config/inboxpilot/client_secret.json``.

Secrets handling: the OAuth refresh token lives in the token file
(``~/.config/inboxpilot/token.json``) written with 0600 permissions. The
client secret itself is never logged, never stored in the token file, and
never leaves the OAuth token exchange.
"""

from __future__ import annotations

import base64
import html as html_module
import json
import logging
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

log = logging.getLogger(__name__)

READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"

GMAIL_API_BASE = "https://www.googleapis.com/gmail/v1"
GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"

# Snippet length: the triage layer truncates further; this is just the
# ingestion-side cap so downstream code never sees unbounded text.
SNIPPET_MAX_CHARS = 2000

USER_AGENT = "InboxPilot/0.1"

DEFAULT_TOKEN_PATH = "~/.config/inboxpilot/token.json"
DEFAULT_CLIENT_SECRET_PATH = "~/.config/inboxpilot/client_secret.json"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class GmailError(Exception):
    """Base error for the Gmail client."""


class GmailAuthError(GmailError):
    """OAuth failed or the stored token is unusable."""


class GmailScopeError(GmailError, PermissionError):
    """A write was attempted without the gmail.modify scope."""


class GmailMessageNotFoundError(GmailError, LookupError):
    """Requested message id does not exist."""


# ---------------------------------------------------------------------------
# Body extraction (pure function — used by both backends)
# ---------------------------------------------------------------------------

def _b64url_decode(data: str) -> str:
    """Decode Gmail's base64url payload data (padding is usually stripped)."""
    data = data.strip().replace("-", "+").replace("_", "/")
    data += "=" * (-len(data) % 4)
    return base64.b64decode(data).decode("utf-8", errors="replace")


_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(html_text: str) -> str:
    """Best-effort HTML -> text for the html-fallback path (stdlib only)."""
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html_text)
    text = _TAG_RE.sub(" ", text)
    text = html_module.unescape(text)
    return re.sub(r"[ \t\xa0]+", " ", text).strip()


def extract_body(payload: dict) -> str:
    """Extract readable text from a Gmail ``messages.get(format=full)`` payload.

    Walks multipart payloads depth-first, prefers the first ``text/plain``
    part, falls back to ``text/html`` (tags stripped), and skips attachments
    (v0.1 does not do attachment text extraction — see ARCHITECTURE.md §10).
    Returns "" when nothing usable is found rather than raising.
    """
    plain: str | None = None
    html_text: str | None = None

    def walk(part: dict) -> None:
        nonlocal plain, html_text
        for sub in part.get("parts") or []:
            walk(sub)
        body = part.get("body") or {}
        data = body.get("data")
        if not data or body.get("attachmentId"):
            return
        try:
            text = _b64url_decode(data)
        except Exception:  # corrupt part: skip, don't kill the whole message
            log.warning("Skipping undecodable payload part")
            return
        mime = (part.get("mimeType") or "").lower()
        if mime == "text/plain" and plain is None:
            plain = text
        elif mime == "text/html" and html_text is None:
            html_text = text

    walk(payload or {})
    if plain:
        return plain.strip()
    if html_text:
        return _strip_html(html_text)
    return ""


def _header(payload: dict, name: str) -> str:
    for h in payload.get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


# ---------------------------------------------------------------------------
# Token storage (0600 perms, always)
# ---------------------------------------------------------------------------

def _save_token(path: str, token: dict) -> None:
    """Write the OAuth token JSON; the file always ends up mode 0600."""
    path = os.path.expanduser(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = json.dumps(token, indent=2)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
    except BaseException:
        os.close(fd)
        raise
    os.chmod(path, 0o600)  # enforce even if the file already existed


def _load_token(path: str) -> dict | None:
    path = os.path.expanduser(path)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# OAuth2 installed-app flow (stdlib only)
# ---------------------------------------------------------------------------

def _load_client_secrets(path: str) -> tuple[str, str]:
    """Read client_id/client_secret from a Google Desktop-client JSON file.

    Accepts the standard download format ({"installed": {...}}), the
    {"web": {...}} variant, and a flat {"client_id": ..., "client_secret": ...}
    file.
    """
    path = os.path.expanduser(path)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise GmailAuthError(
            f"OAuth client secrets not found at {path}.\n"
            "Download client_secret.json from your Google Cloud project "
            "(APIs & Services > Credentials > OAuth client ID > Desktop app) "
            "and save it there. See docs/gmail-setup.md for the full "
            "step-by-step."
        )
    section = data.get("installed") or data.get("web") or data
    client_id = section.get("client_id")
    client_secret = section.get("client_secret")
    if not client_id or not client_secret:
        raise GmailAuthError(
            f"{path} does not contain client_id/client_secret. Re-download "
            "the Desktop-app OAuth client JSON from Google Cloud Console."
        )
    return client_id, client_secret


class _CallbackHandler(BaseHTTPRequestHandler):
    """Single-shot OAuth callback handler. Captures ?code= then stops."""

    code: str | None = None
    state: str | None = None
    expected_state: str = ""

    def do_GET(self) -> None:  # noqa: N802 (http.server naming)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        type(self).code = query.get("code", [None])[0]
        type(self).state = query.get("state", [None])[0]
        ok = bool(type(self).code) and type(self).state == type(self).expected_state
        body = (
            b"<html><body style='font-family:sans-serif'>"
            + (b"<h2>Signed in - you can close this tab.</h2>"
               b"<p>Return to your terminal; InboxPilot will continue.</p>"
               if ok else
               b"<h2>Something went wrong.</h2>"
               b"<p>No authorization code received. Return to the terminal.</p>")
            + b"</body></html>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep the callback quiet
        pass


def _run_oauth_flow(client_secret_path: str, scopes: list[str],
                    token_path: str) -> dict:
    """Run the installed-app OAuth flow and persist the resulting token."""
    client_id, client_secret = _load_client_secrets(client_secret_path)

    state = secrets.token_urlsafe(16)
    _CallbackHandler.code = None
    _CallbackHandler.state = None
    _CallbackHandler.expected_state = state

    server = HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    server.timeout = 300
    port = server.server_address[1]
    redirect_uri = f"http://127.0.0.1:{port}/callback"

    auth_url = GOOGLE_AUTH_URI + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",   # we need a refresh token
        "prompt": "consent",        # force re-grant so scopes can't go stale
        "state": state,
    })

    print("Opening your browser for Google sign-in...", file=sys.stderr)
    print(f"If no browser opens, visit this URL manually:\n\n{auth_url}\n",
          file=sys.stderr)
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass  # URL is printed above; manual copy-paste still works

    server.handle_request()  # blocks until the callback arrives (or timeout)
    server.server_close()

    code = _CallbackHandler.code
    if not code or _CallbackHandler.state != state:
        raise GmailAuthError(
            "Did not receive a valid OAuth authorization code "
            "(browser callback timed out or was denied)."
        )

    token = _exchange_code(client_id, client_secret, code, redirect_uri,
                           token_path)
    return token


def _exchange_code(client_id: str, client_secret: str, code: str,
                   redirect_uri: str, token_path: str) -> dict:
    req = urllib.request.Request(
        GOOGLE_TOKEN_URI,
        data=urllib.parse.urlencode({
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        raise GmailAuthError(f"Token exchange failed (HTTP {e.code}): {detail}")
    token = {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token"),
        "expires_at": time.time() + int(data.get("expires_in", 3600)),
        "scope": data.get("scope", ""),
        "token_type": data.get("token_type", "Bearer"),
    }
    _save_token(token_path, token)
    return token


def _refresh_access_token(client_id: str, client_secret: str,
                          token: dict, token_path: str) -> dict:
    req = urllib.request.Request(
        GOOGLE_TOKEN_URI,
        data=urllib.parse.urlencode({
            "refresh_token": token["refresh_token"],
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
        }).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        raise GmailAuthError(
            f"Token refresh failed (HTTP {e.code}): {detail}. "
            "Delete the token file and re-authenticate."
        )
    token["access_token"] = data["access_token"]
    token["expires_at"] = time.time() + int(data.get("expires_in", 3600))
    if data.get("refresh_token"):
        token["refresh_token"] = data["refresh_token"]
    _save_token(token_path, token)
    return token


# ---------------------------------------------------------------------------
# Fixture backend — zero network, in-memory label applications
# ---------------------------------------------------------------------------

class _FixtureBackend:
    """Serves a local JSON inbox. No network is ever touched."""

    def __init__(self, fixture_path: str):
        path = os.path.expanduser(fixture_path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self._order: list[str] = []
        self._messages: dict[str, dict] = {}
        for m in data["messages"]:
            mid = m["id"]
            body = m.get("body")
            if body is None and m.get("payload"):
                # Multipart fixture entries exercise the real extraction path.
                body = extract_body(m["payload"])
            body = body or ""
            snippet = m.get("snippet") or body[:SNIPPET_MAX_CHARS]
            self._order.append(mid)
            self._messages[mid] = {
                "id": mid,
                "thread_id": m.get("thread_id", ""),
                "from": m.get("from", ""),
                "subject": m.get("subject", ""),
                "date": m.get("date", ""),
                "snippet": snippet,
                "body": body,
                "labels": list(m.get("labels", [])),
            }
        # (message_id, label_name) in application order — for test assertions.
        self.applied_labels: list[tuple[str, str]] = []

    def list_unread(self, max_n: int = 50) -> list[str]:
        return [mid for mid in self._order
                if "UNREAD" in self._messages[mid]["labels"]][:max_n]

    def get_message(self, mid: str) -> dict:
        try:
            m = self._messages[mid]
        except KeyError:
            raise GmailMessageNotFoundError(f"Unknown message id: {mid!r}")
        return dict(m, labels=list(m["labels"]))

    def apply_label(self, mid: str, label_name: str) -> None:
        if mid not in self._messages:
            raise GmailMessageNotFoundError(f"Unknown message id: {mid!r}")
        self.applied_labels.append((mid, label_name))
        if label_name not in self._messages[mid]["labels"]:
            self._messages[mid]["labels"].append(label_name)

    def remove_label(self, mid: str, label_name: str) -> None:
        if mid not in self._messages:
            raise GmailMessageNotFoundError(f"Unknown message id: {mid!r}")
        labels = self._messages[mid]["labels"]
        self._messages[mid]["labels"] = [l for l in labels if l != label_name]
        self.applied_labels.append((mid, f"-{label_name}"))

    def set_archived(self, mid: str, archived: bool) -> None:
        """Archive = remove INBOX; unarchive = restore it."""
        if archived:
            self.remove_label(mid, "INBOX")
        elif "INBOX" not in self._messages[mid]["labels"]:
            self.apply_label(mid, "INBOX")


# ---------------------------------------------------------------------------
# Real Gmail API backend
# ---------------------------------------------------------------------------

class _GmailApiBackend:
    """Thin Gmail API wrapper over urllib. OAuth tokens auto-refresh."""

    def __init__(self, token_path: str, client_secret_path: str,
                 requested_scopes: list[str]):
        self._token_path = os.path.expanduser(token_path)
        self._client_secret_path = os.path.expanduser(client_secret_path)
        self._requested_scopes = list(requested_scopes)
        self._token = self._ensure_token()
        self._granted_scopes = set(self._token.get("scope", "").split())

    @property
    def granted_scopes(self) -> set[str]:
        return set(self._granted_scopes)

    # -- auth -----------------------------------------------------------

    def _ensure_token(self) -> dict:
        token = _load_token(self._token_path)
        if token and set(self._requested_scopes) <= set(
                token.get("scope", "").split()) and token.get("access_token"):
            return self._maybe_refresh(token)
        if token:
            print("Stored Gmail credentials don't cover the requested scopes; "
                  "re-authenticating...", file=sys.stderr)
        return self._maybe_refresh(
            _run_oauth_flow(self._client_secret_path,
                            self._requested_scopes, self._token_path))

    def _maybe_refresh(self, token: dict) -> dict:
        if token.get("expires_at", 0) <= time.time() + 60:
            if not token.get("refresh_token"):
                raise GmailAuthError(
                    "Stored token is expired and has no refresh token. "
                    f"Delete {self._token_path} and re-authenticate."
                )
            client_id, client_secret = _load_client_secrets(
                self._client_secret_path)
            token = _refresh_access_token(client_id, client_secret, token,
                                          self._token_path)
        return token

    # -- http -----------------------------------------------------------

    def _request(self, method: str, path: str,
                 payload: dict | None = None) -> dict:
        url = GMAIL_API_BASE + path
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={"Authorization": f"Bearer {self._token['access_token']}",
                     "Content-Type": "application/json",
                     "User-Agent": USER_AGENT},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            if e.code == 401:
                # One refresh + retry; then give up honestly.
                self._token = self._maybe_refresh(self._token)
                req = urllib.request.Request(
                    url, data=data, method=method,
                    headers={"Authorization":
                             f"Bearer {self._token['access_token']}",
                             "Content-Type": "application/json",
                             "User-Agent": USER_AGENT},
                )
                try:
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        raw = resp.read().decode("utf-8")
                        return json.loads(raw) if raw else {}
                except urllib.error.HTTPError as e2:
                    detail = e2.read().decode("utf-8", "replace")[:500]
                    raise GmailAuthError(
                        f"Gmail API rejected the token (HTTP 401): {detail}. "
                        f"Delete {self._token_path} and re-authenticate.")
            detail = e.read().decode("utf-8", "replace")[:500]
            raise GmailError(f"Gmail API {method} {path} failed "
                             f"(HTTP {e.code}): {detail}")

    # -- interface ------------------------------------------------------

    def list_unread(self, max_n: int = 50) -> list[str]:
        params = urllib.parse.urlencode({"q": "is:unread",
                                         "maxResults": max(1, min(max_n, 500))})
        data = self._request("GET", f"/users/me/messages?{params}")
        return [m["id"] for m in data.get("messages", [])]

    def get_message(self, mid: str) -> dict:
        try:
            data = self._request("GET", f"/users/me/messages/{mid}?format=full")
        except GmailError as e:
            if "HTTP 404" in str(e):
                raise GmailMessageNotFoundError(f"Unknown message id: {mid!r}")
            raise
        payload = data.get("payload", {})
        body = extract_body(payload)
        return {
            "id": data.get("id", mid),
            "thread_id": data.get("threadId", ""),
            "from": _header(payload, "From"),
            "subject": _header(payload, "Subject"),
            "date": _header(payload, "Date"),
            "snippet": (data.get("snippet", "") or body)[:SNIPPET_MAX_CHARS],
            "body": body,
            "labels": list(data.get("labelIds", [])),
        }

    def _label_id(self, label_name: str) -> str:
        """Resolve a label name to its Gmail id, creating it if missing."""
        data = self._request("GET", "/users/me/labels")
        for label in data.get("labels", []):
            if label.get("name", "").lower() == label_name.lower():
                return label["id"]
        created = self._request("POST", "/users/me/labels", {
            "name": label_name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        })
        return created["id"]

    def apply_label(self, mid: str, label_name: str) -> None:
        label_id = self._label_id(label_name)
        self._request("POST", f"/users/me/messages/{mid}/modify",
                      {"addLabelIds": [label_id]})

    def remove_label(self, mid: str, label_name: str) -> None:
        label_id = self._label_id(label_name)
        self._request("POST", f"/users/me/messages/{mid}/modify",
                      {"removeLabelIds": [label_id]})

    def set_archived(self, mid: str, archived: bool) -> None:
        """Archive = remove the INBOX label; unarchive = restore it."""
        if archived:
            self._request("POST", f"/users/me/messages/{mid}/modify",
                          {"removeLabelIds": ["INBOX"]})
        else:
            self._request("POST", f"/users/me/messages/{mid}/modify",
                          {"addLabelIds": ["INBOX"]})


# ---------------------------------------------------------------------------
# Public client
# ---------------------------------------------------------------------------

class GmailClient:
    """InboxPilot's Gmail client — identical interface for real and fixture.

    Args:
        credentials_path: where the OAuth token JSON lives (real mode only).
        scopes: requested OAuth scopes. Defaults to read-only.
        fixture_path: when given, ALL network paths are disabled and the
            client serves from this JSON fixture (tests and ``inboxpilot
            demo``).
        enable_write: when True, ``gmail.modify`` is added to the requested
            scopes so auto-label can apply Gmail labels. A plain-language
            explanation of why is logged.
        client_secret_path: the user-provided Desktop-client
            ``client_secret.json`` (real mode only).
    """

    def __init__(
        self,
        credentials_path: str = DEFAULT_TOKEN_PATH,
        scopes: tuple[str, ...] = (READONLY_SCOPE,),
        fixture_path: str | None = None,
        *,
        enable_write: bool = False,
        client_secret_path: str = DEFAULT_CLIENT_SECRET_PATH,
    ):
        requested = list(scopes)
        if enable_write and MODIFY_SCOPE not in requested:
            requested.append(MODIFY_SCOPE)
            print(
                "InboxPilot: requesting Gmail 'modify' permission because you "
                "enabled auto-label. This lets InboxPilot ADD labels (e.g. "
                "'p0', 'needs-action') to your messages. It will never "
                "delete, send, or trash mail — applying labels is the only "
                "write operation this code performs.",
                file=sys.stderr,
            )
        self._requested_scopes = tuple(requested)
        self._fixture_mode = fixture_path is not None

        if self._fixture_mode:
            # Fixture: no credentials, no OAuth, no network — ever.
            self._granted_scopes = set(requested)
            self._backend: _FixtureBackend | _GmailApiBackend = \
                _FixtureBackend(fixture_path)
        else:
            backend = _GmailApiBackend(credentials_path, client_secret_path,
                                       requested)
            self._granted_scopes = backend.granted_scopes
            self._backend = backend

    @property
    def fixture_mode(self) -> bool:
        """True when serving from a local fixture (no network possible)."""
        return self._fixture_mode

    @property
    def granted_scopes(self) -> set[str]:
        return set(self._granted_scopes)

    @property
    def applied_labels(self) -> list[tuple[str, str]]:
        """In-memory record of label applications — fixture mode only."""
        if not self._fixture_mode:
            raise GmailError("applied_labels is only available in fixture mode")
        backend = self._backend
        assert isinstance(backend, _FixtureBackend)
        return list(backend.applied_labels)

    def list_unread(self, max_n: int = 50) -> list[str]:
        """Return up to ``max_n`` unread message ids (newest first)."""
        return self._backend.list_unread(max_n)

    def get_message(self, mid: str) -> dict:
        """Return a normalized message dict.

        Keys: id, thread_id, from, subject, date, snippet (<=2000 chars),
        body (full extracted text), labels.
        """
        return self._backend.get_message(mid)

    def apply_label(self, mid: str, label_name: str) -> None:
        """Apply a Gmail label. Requires the gmail.modify scope.

        Raises:
            GmailScopeError: when the granted scopes lack gmail.modify, with
                instructions on how to enable it.
        """
        if MODIFY_SCOPE not in self._granted_scopes:
            raise GmailScopeError(
                "Cannot apply labels: the gmail.modify scope was not granted.\n"
                "Auto-label is disabled until you opt in. To enable it, "
                "construct GmailClient with enable_write=True (you'll be "
                "asked to re-consent in the browser), e.g.:\n"
                "    GmailClient(enable_write=True)\n"
                "Read-only triage and the morning digest work fine without it."
            )
        self._backend.apply_label(mid, label_name)

    def remove_label(self, mid: str, label_name: str) -> None:
        """Remove a Gmail label. Requires the gmail.modify scope."""
        if MODIFY_SCOPE not in self._granted_scopes:
            raise GmailScopeError(
                "Cannot remove labels: the gmail.modify scope was not granted."
            )
        self._backend.remove_label(mid, label_name)

    def set_archived(self, mid: str, archived: bool) -> None:
        """Archive (remove from inbox) or unarchive a message.

        Requires the gmail.modify scope. Archiving never deletes.
        """
        if MODIFY_SCOPE not in self._granted_scopes:
            raise GmailScopeError(
                "Cannot archive: the gmail.modify scope was not granted."
            )
        self._backend.set_archived(mid, archived)
