#!/usr/bin/env python3
"""Build tests/fixtures/fixture_inbox.json — a realistic founder inbox (~25 messages).

Run from the inboxpilot root:
    python3 tests/fixtures/make_fixture.py

The generated JSON is committed; this script exists so the fixture stays
maintainable. Multipart Gmail-API-style payloads are constructed here (with
real base64url encoding, padding stripped like the real API) so encoding is
always valid.

Coverage (per the build brief):
  investor update, customer escalation, invoice receipt, newsletter,
  promo blast, obvious spam, thread where the founder was asked a question,
  thread where the founder already replied, an AMBIGUOUS "per my last email"
  thread (escalation test), and a message from a contact that looks like noise
  (contradiction test for the never-archive guardrail).
"""

import base64
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "fixture_inbox.json")


def b64url(text: str) -> str:
    """base64url-encode like the Gmail API does (padding stripped)."""
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def plain_part(text: str) -> dict:
    return {"mimeType": "text/plain", "body": {"data": b64url(text)}}


def html_part(html: str) -> dict:
    return {"mimeType": "text/html", "body": {"data": b64url(html)}}


def headers(frm: str, subject: str, date: str) -> list:
    return [
        {"name": "From", "value": frm},
        {"name": "Subject", "value": subject},
        {"name": "Date", "value": date},
    ]


def msg(mid, thread, frm, subject, date, body=None, labels=("INBOX", "UNREAD"),
        payload=None, snippet=None):
    m = {
        "id": mid,
        "thread_id": thread,
        "from": frm,
        "subject": subject,
        "date": date,
        "labels": list(labels),
    }
    if body is not None:
        m["body"] = body
    if payload is not None:
        m["payload"] = payload
    if snippet is not None:
        m["snippet"] = snippet
    return m


# ---------------------------------------------------------------------------
# Message bodies
# ---------------------------------------------------------------------------

BANK_PLAIN = """Hi Aarav,

We blocked a sign-in attempt to your Northloop Google Workspace account from
an unrecognized device (Chrome on Windows, Lagos, Nigeria) at 09:02 IST.

If this was you, no action is needed. If it wasn't, please review your
account activity immediately:
https://myaccount.google.com/security

- The Google Accounts team"""

BANK_HTML = """<html><body><p>Hi Aarav,</p><p>We <b>blocked a sign-in attempt</b> to your
Northloop Google Workspace account from an unrecognized device (Chrome on
Windows, Lagos, Nigeria) at 09:02 IST.</p><p>If this was you, no action is
needed. If it wasn't, please review your account activity immediately.</p>
<p>- The Google Accounts team</p></body></html>"""

AWS_PLAIN = """Hello,

Your AWS invoice for September 2026 is ready.

  Total due:            $312.44
  Compute (EC2):        $198.10
  Storage (S3):          $64.20
  Data transfer:         $50.14

Payment method: Visa ending 4412. No action required - this invoice will be
charged automatically on Oct 5.

View invoice: https://console.aws.amazon.com/billing

- AWS Billing"""

SPAM_HTML = """<html><body><h1>ELON MUSK CRYPTO GIVEAWAY!!!</h1><p>Send <b>0.1 BTC</b>
to <b>1MuskGiveawayX9f2kL</b> and receive <b>0.2 BTC</b> back INSTANTLY!
Verified by Tesla &amp; SpaceX!!!</p><p><a href="http://totally-legit-giveaway.xyz">
CLAIM YOUR DOUBLE BITCOIN NOW</a></p><p><i>Limited time offer!!! Act fast!!!</i>
</p></body></html>"""

# Long body on purpose: exercises the ~2000-char snippet truncation path.
PER_MY_LAST_EMAIL = """Hi Aarav,

Per my last email (and the one before that), we're still waiting on the
updated API docs for the v2 webhook payloads. Our team has now missed two
sprint milestones because the field mappings we built against the January
spec no longer match what your staging endpoint returns.

To be clear, I'm not asking for anything new - just documentation for what
you already shipped. I've attached our integration test failures for
reference; happy to walk through them whenever works for you.

Could you please confirm by EOD whether the docs will be ready this week?
If not, we'll need to revisit the partnership timeline, which I would
genuinely rather not do. DataSync has three enterprise customers waiting on
this integration, and I am running out of ways to explain the delay on
our side.

Appreciate your help here.

Best,
Sarah
--
Sarah Kim | Head of Partnerships, DataSync Inc.

---
On Mon, Sep 28, 2026 at 11:04 AM, Aarav Sharma <aarav@northloop.io> wrote:
> Hi Sarah - docs are coming, just finalizing the webhook retry semantics
> with Priya. Should have something for you soon. Sorry for the delay!

On Mon, Sep 28, 2026 at 2:31 PM, Sarah Kim <sarah@datasync.io> wrote:
> Thanks Aarav. "Soon" was also the answer on Sep 14 and Sep 21, so I
> hope you'll understand if I need something firmer this time. Even a
> draft of the payload schema would unblock us.

On Tue, Sep 29, 2026 at 9:12 AM, Aarav Sharma <aarav@northloop.io> wrote:
> Fair point. Let me check with Priya today and get back to you.

On Wed, Sep 30, 2026 at 4:47 PM, Sarah Kim <sarah@datasync.io> wrote:
> Circling back on this - any update? Our sprint planning is tomorrow
> morning and I'd love to give the team a date.

On Thu, Oct 1, 2026 at 10:15 AM, Aarav Sharma <aarav@northloop.io> wrote:
> Still chasing this internally, will update you shortly.

On Fri, Oct 2, 2026 at 8:58 AM, Sarah Kim <sarah@datasync.io> wrote:
> See above. EOD confirmation, please.

P.S. Looping in my CTO (cc'd) so we're all on the same page. He asked me
this morning whether we should pause the joint GTM announcement scheduled
for Oct 20 - I told him I'd have an answer after I hear from you. No
pressure, but the announcement draft is already with both our PR teams,
so a slip here gets visible fast. Really hoping we can keep Oct 20."""

messages = [
    # --- Oct 2 (newest first) ---
    msg("msg-025", "thread-025",
        "Vikram Rao <ops@acmecorp.com>",
        "Re: Northloop dashboard down for our entire team - P0",
        "2026-10-02T09:41:00+05:30",
        body="Aarav - following up on my 6am note.\n\nOur entire analytics "
             "team (14 people) still cannot load a single dashboard. This is "
             "blocking our board prep for Monday. We pay for the Scale plan "
             "specifically for the 99.9% uptime SLA, and this is now hour "
             "four.\n\nPlease escalate this personally. I need a status "
             "update and an ETA within the hour.\n\n- Vikram"),
    msg("msg-024", "thread-024",
        "Google Accounts <no-reply@accounts.google.com>",
        "Security alert: sign-in attempt blocked",
        "2026-10-02T09:12:00+05:30",
        labels=("INBOX", "UNREAD"),
        payload={
            "mimeType": "multipart/alternative",
            "headers": headers("Google Accounts <no-reply@accounts.google.com>",
                               "Security alert: sign-in attempt blocked",
                               "2026-10-02T09:12:00+05:30"),
            "parts": [plain_part(BANK_PLAIN), html_part(BANK_HTML)],
        }),
    msg("msg-023", "thread-023",
        "Sarah Kim <sarah@datasync.io>",
        "Re: v2 webhook docs - still waiting",
        "2026-10-02T08:58:00+05:30",
        body=PER_MY_LAST_EMAIL),
    msg("msg-022", "thread-022",
        "Rahul Verma <rahul.verma@gmail.com>",
        "lol you HAVE to see this",
        "2026-10-02T08:30:00+05:30",
        body="lol you HAVE to see this 😂\n\n"
             "https://www.youtube.com/watch?v=dQw4w9WgXcQ\n\n"
             "this is literally us at the last hackathon. we never did fix "
             "that demo, did we\n\n- Rahul"),
    msg("msg-021", "thread-021",
        "Stripe <receipts@stripe.com>",
        "Your payout of ₹84,210.00 is on the way",
        "2026-10-02T07:15:00+05:30",
        body="Hi Northloop,\n\nA payout of ₹84,210.00 is on the way to your "
             "HDFC account ending 8821. It should arrive within 2 business "
             "days.\n\n- The Stripe team"),
    msg("msg-020", "thread-020",
        "AWS Billing <aws-billing@amazon.com>",
        "Your AWS invoice for September 2026 is ready",
        "2026-10-02T06:40:00+05:30",
        payload={
            "mimeType": "multipart/mixed",
            "headers": headers("AWS Billing <aws-billing@amazon.com>",
                               "Your AWS invoice for September 2026 is ready",
                               "2026-10-02T06:40:00+05:30"),
            "parts": [
                plain_part(AWS_PLAIN),
                {"mimeType": "application/pdf",
                 "filename": "invoice-sep-2026.pdf",
                 "body": {"attachmentId": "ANGjd_J_attachment_1",
                          "size": 48210}},
            ],
        }),

    # --- Oct 1 ---
    msg("msg-019", "thread-019",
        "Rohan Mehta <rohan@peakxv.com>",
        "Monthly update - quick ask",
        "2026-10-01T22:05:00+05:30",
        body="Hi Aarav,\n\nEnjoyed the September update - the NRR number "
             "caught my eye. Quick ask: could you share the split of new vs "
             "expansion MRR by Friday? We're putting together the portfolio "
             "review deck and I'd love to feature Northloop's expansion "
             "motion.\n\nNo rush beyond Friday. And congrats on the Acme "
             "logo.\n\nBest,\nRohan"),
    msg("msg-018", "thread-018",
        "Dana Whitfield <dana@brightcart.com>",
        "Question about your pricing tiers",
        "2026-10-01T20:33:00+05:30",
        body="Hi!\n\nWe're evaluating Northloop vs Mixpanel for our app "
             "(~2M MAU). Quick question: does the Scale plan include SSO and "
             "EU data residency? I need to brief our security team on "
             "Thursday, so anything you can share before then helps.\n\n"
             "Thanks!\nDana\nBrightcart"),
    msg("msg-017", "thread-017",
        "GitHub <notifications@github.com>",
        "[northloop/api] Priya Nair requested your review: PR #482",
        "2026-10-01T19:48:00+05:30",
        body="Priya Nair requested your review on northloop/api pull "
             "request #482: \"fix(webhooks): retry with exponential "
             "backoff + jitter\".\n\n2 files changed, 84 additions. CI is "
             "green.\n\nhttps://github.com/northloop/api/pull/482"),
    msg("msg-016", "thread-016",
        "Priya Nair <priya@northloop.io>",
        "Re: Launch checklist - migration confirmed",
        "2026-10-01T18:20:00+05:30",
        labels=("INBOX",),  # read: founder already replied, Priya confirmed
        body="Confirming the migration script ran clean on staging - all "
             "14k workspaces migrated, zero errors. We're good for "
             "Thursday.\n\n(And yes, to your question: the rollback plan "
             "was tested twice. We're covered.)\n\n- P"),
    msg("msg-015", "thread-015",
        "Northloop Support <support@northloop.io>",
        "Ticket #3109: Can't reset my password - locked out",
        "2026-10-01T17:02:00+05:30",
        body="New high-priority ticket from a Scale-plan admin "
             "(meera@finlytics.com):\n\n\"I've tried the password reset "
             "link 4 times and it keeps saying expired. I'm the only admin "
             "and my team can't log in. Please help ASAP.\"\n\nTicket "
             "auto-assigned to the on-call queue."),
    msg("msg-014", "thread-014",
        "Google Accounts <no-reply@accounts.google.com>",
        "New sign-in from Chrome on Mac",
        "2026-10-01T16:44:00+05:30",
        body="Hi Aarav,\n\nYour Google Account was just signed in to from a "
             "new device:\n  Chrome on Mac · Mumbai, India · Oct 1, 4:44 PM "
             "IST\n\nIf this was you, you can ignore this. Wasn't you? "
             "Secure your account: https://myaccount.google.com/security"),
    msg("msg-013", "thread-013",
        "Northloop Billing <billing@northloop.io>",
        "Payment failed for Northloop Pro (Figma)",
        "2026-10-01T15:30:00+05:30",
        body="Hi Aarav,\n\nWe tried to charge ₹4,590.00 to your Visa ending "
             "4412 for Figma (Northloop Pro, annual) but the payment "
             "failed.\n\nPlease update your payment method within 7 days to "
             "avoid interruption: https://billing.northloop.io\n\n- "
             "Northloop Billing (via Figma)"),
    msg("msg-012", "thread-012",
        "Priya Nair <priya@northloop.io>",
        "Standup notes - Oct 1",
        "2026-10-01T14:12:00+05:30",
        labels=("INBOX",),  # read
        body="Standup notes:\n- Webhook retry PR (#482) merged, deploying "
             "to staging today\n- Acme onboarding call moved to Monday\n"
             "- Design intern shortlist: 3 candidates, loom links in "
             "Notion\n- Reminder: metrics for Rohan by Friday"),
    msg("msg-011", "thread-011",
        "Figma <notifications@figma.com>",
        "Your Northloop Pro subscription renews in 7 days",
        "2026-10-01T13:05:00+05:30",
        body="Hi there,\n\nYour Figma Northloop Pro subscription renews on "
             "Oct 8, 2026 for ₹4,590.00/year. We'll charge the Visa ending "
             "4412 on file.\n\nManage subscription: https://figma.com/"
             "settings/billing"),
    msg("msg-010", "thread-010",
        "TechCrunch <newsletters@techcrunch.com>",
        "TechCrunch Daily: AI agents raise $2B in Q3",
        "2026-10-01T11:26:00+05:30",
        body="Today's top stories:\n1. AI agent startups raised $2B in Q3, "
             "up 3x YoY\n2. Peak XV closes $1.2B new fund\n3. The quiet "
             "boom in vertical analytics tools\n\nRead more: "
             "https://techcrunch.com/daily"),
    msg("msg-009", "thread-009",
        "Notion <notify@mail.notion.so>",
        "Last chance: 50% off Notion annual plans ends today",
        "2026-10-01T10:15:00+05:30",
        body="Don't miss out! Get 50% off Notion Plus annual plans - offer "
             "ends tonight at midnight.\n\nUpgrade: https://notion.so/"
             "upgrade\n\nYou're receiving this because you have a Notion "
             "account."),
    msg("msg-008", "thread-008",
        "LinkedIn <notifications-noreply@linkedin.com>",
        "12 people viewed your profile this week",
        "2026-10-01T09:40:00+05:30",
        body="Hi Aarav,\n\n12 people viewed your profile in the last 7 "
             "days, including 3 founders and 2 investors.\n\nSee who's "
             "been checking you out: https://linkedin.com/me"),

    # --- Sep 30 ---
    msg("msg-007", "thread-007",
        "Y Combinator <events@ycombinator.com>",
        "You're invited: How to price your seed round (Oct 9)",
        "2026-09-30T18:22:00+05:30",
        body="Join YC partners for a live session on seed-round pricing, "
             "Oct 9 at 9pm IST.\n\nAgenda: valuation benchmarks, SAFE vs "
             "priced rounds, what actually matters to investors.\n\nRSVP: "
             "https://ycombinator.com/events"),
    msg("msg-006", "thread-006",
        "Crypto Promo <promo@totally-legit-giveaway.xyz>",
        "ELON MUSK CRYPTO GIVEAWAY - DOUBLE YOUR BTC!!!",
        "2026-09-30T17:50:00+05:30",
        payload={
            "mimeType": "text/html",
            "headers": headers(
                "Crypto Promo <promo@totally-legit-giveaway.xyz>",
                "ELON MUSK CRYPTO GIVEAWAY - DOUBLE YOUR BTC!!!",
                "2026-09-30T17:50:00+05:30"),
            "body": {"data": b64url(SPAM_HTML)},
        }),
    msg("msg-005", "thread-005",
        "Ananya Rao <ananya.rao@talentbridge.in>",
        "Staff Engineer roles at FAANG - 15 min chat?",
        "2026-09-30T16:30:00+05:30",
        body="Hi Aarav,\n\nI came across your profile and was impressed by "
             "your background! I have several Staff Engineer openings at "
             "top product companies with 80L+ packages.\n\nAre you open to "
             "a 15-min chat this week?\n\nBest,\nAnanya\nTalentBridge"),
    msg("msg-004", "thread-004",
        "IndiGo <bookings@goindigo.in>",
        "Booking confirmed: BOM to BLR, Oct 18 (PNR XJ8K2Q)",
        "2026-09-30T15:12:00+05:30",
        labels=("INBOX",),  # read
        body="Hi Aarav Sharma,\n\nYour booking is confirmed.\n  6E-6143 · "
             "BOM → BLR · Oct 18, 07:10 - 08:55\n  PNR: XJ8K2Q · Seat 14A\n\n"
             "Manage booking: https://goindigo.in"),
    msg("msg-003", "thread-003",
        "Segment <updates@segment.com>",
        "We've updated our Terms of Service",
        "2026-09-30T14:05:00+05:30",
        body="Hi there,\n\nWe've updated our Terms of Service, effective "
             "Nov 1, 2026. Key changes: updated data processing addendum "
             "for the EU, clarified SLA credits.\n\nNo action is required. "
             "Read the updated terms: https://segment.com/legal"),
    msg("msg-002", "thread-002",
        "Google Calendar <calendar-noreply@google.com>",
        "Invitation: Board meeting - Q4 planning @ Mon Oct 5, 10am",
        "2026-09-30T12:30:00+05:30",
        labels=("INBOX",),  # read
        body="You have been invited to:\n  Board meeting - Q4 planning\n"
             "  Monday, Oct 5, 2026, 10:00 AM - 12:00 PM IST\n"
             "  Organizer: Priya Nair\n\nPlease RSVP in Google Calendar."),
    msg("msg-001", "thread-001",
        "Kabir Singh <kabir.singh.design@gmail.com>",
        "Application: Design Intern, Winter 2026",
        "2026-09-30T09:15:00+05:30",
        body="Hi Aarav,\n\nI'm a 3rd-year design student applying for the "
             "Winter design intern role. Portfolio: https://kabirsingh."
             "design\n\nI've been using Northloop for a class project and "
             "have a few ideas for the onboarding flow I'd love to share.\n\n"
             "Thanks for considering!\nKabir"),
]

fixture = {
    "_comment": (
        "Fixture founder inbox for InboxPilot tests/demo. No network is ever "
        "touched when this fixture is loaded. Messages are ordered newest "
        "first. Bodies may be given directly OR as a Gmail-API-style "
        "'payload' (multipart) - the loader extracts text via the same "
        "extract_body() the real client uses."
    ),
    "generated_by": "tests/fixtures/make_fixture.py",
    "messages": messages,
}

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(fixture, f, indent=2, ensure_ascii=False)
    f.write("\n")

print(f"wrote {OUT} ({len(messages)} messages)")
