# Connecting InboxPilot to Gmail (one-time setup, ~10 minutes)

InboxPilot reads your Gmail through Google's official API using an OAuth
client **you** create in **your own** Google Cloud project. That means your
emails go to Google (obviously) and to TypeSafe AI for triage — and nowhere
else. There is no InboxPilot server, no middleman, no one else's project.

Cost: ₹0. The Gmail API is free at this volume.

---

## Step 1 — Create a Google Cloud project

1. Go to <https://console.cloud.google.com/> and sign in with the Google
   account whose inbox you want triaged.
2. Click the project picker (top-left) → **New Project**.
3. Name it `inboxpilot` (the name only shows on your own consent screen).
4. Click **Create** and wait for it to finish, then select it.

## Step 2 — Enable the Gmail API

1. In the left menu: **APIs & Services → Library**.
2. Search for **Gmail API** → click it → **Enable**.

## Step 3 — Configure the OAuth consent screen

1. Go to **APIs & Services → OAuth consent screen**.
2. User type: **External** → **Create**. (External is correct even for
   personal use — "Internal" is only for Google Workspace organizations.)
3. Fill in:
   - App name: `InboxPilot`
   - User support email: your email
   - Developer contact email: your email
4. Click **Save and Continue** through Scopes and Test users for now.
5. Back on the consent screen, under **Test users**, click **Add users** and
   add your own Gmail address. In test mode, only listed users can sign in —
   and that's all you need.

> **Honest caveat — the 7-day token:** while the app stays in *Testing*
> publishing status, Google expires refresh tokens after **7 days**. So
> roughly once a week you'll re-confirm the consent screen (one click).
> Publishing the app would remove this, but publishing triggers the
> verification process described in "The honest scopes section" below —
> not worth it for personal use.

## Step 4 — Create the OAuth client ID and download `client_secret.json`

1. Go to **APIs & Services → Credentials → Create Credentials →
   OAuth client ID**.
2. Application type: **Desktop app**. Name it `inboxpilot-desktop`.
3. Click **Create**, then **Download JSON**.
4. Save the downloaded file as:

   ```
   ~/.config/inboxpilot/client_secret.json
   ```

   ```bash
   mkdir -p ~/.config/inboxpilot
   mv ~/Downloads/client_secret_*.json ~/.config/inboxpilot/client_secret.json
   chmod 600 ~/.config/inboxpilot/client_secret.json
   ```

   This file contains your app's client ID and secret. InboxPilot reads it
   only to perform the OAuth exchange; it is never logged, never stored in
   the repo, never sent anywhere except Google's token endpoint.

## Step 5 — First run (browser sign-in)

Run any InboxPilot command that touches Gmail (e.g. `inboxpilot demo`
uses the offline fixture; `inboxpilot run` uses real Gmail):

1. Your browser opens to Google's consent screen. If it doesn't, the
   terminal prints a URL — open it manually.
2. Google will show an **"unverified app"** warning. That's expected: it's
   *your* app, in test mode, and Google hasn't reviewed it (see below for
   why we don't bother). Click **Advanced → Go to InboxPilot (unsafe)**.
   "Unsafe" here means "Google hasn't reviewed this" — you wrote the
   config, you know what it does.
3. Grant the requested permissions (read-only by default — see below).
4. The tab shows "Signed in — you can close this tab." Done.

InboxPilot stores the resulting token at `~/.config/inboxpilot/token.json`
with `0600` permissions (readable only by you). It refreshes automatically
and never asks you to sign in again unless scopes change.

## Enabling auto-label later (optional)

By default InboxPilot is **read-only**: triage suggestions and the morning
digest work fully without write access.

If you want InboxPilot to actually apply Gmail labels (e.g. `p0`,
`needs-action`) on high-confidence triage, opt in explicitly:

```python
GmailClient(enable_write=True)
```

The first time you do this, the terminal prints a plain-language
explanation of why the extra permission is requested, and the browser
re-consent asks for the additional scope. Label application is the *only*
write this code performs — it never deletes, sends, archives, or trashes
mail. (Applying or removing a label is what the `gmail.modify` scope
covers.)

---

## The honest scopes section

| Scope | What it technically allows | What InboxPilot uses it for |
|---|---|---|
| `gmail.readonly` | Read messages, threads, labels, and metadata. Cannot change anything. | Ingestion: listing unread mail, fetching bodies for triage. Requested by default. |
| `gmail.modify` | Read + apply/remove labels, archive, trash, mark read/unread. Cannot delete permanently or send mail. | **Only** applying triage labels, and **only** when you pass `enable_write=True`. The code has no path that archives, trashes, marks-read, or sends. |

**Why minimal scopes:** scopes are the blast radius. A read-only token that
leaks can expose mail, but it can't *do* anything to your inbox. We keep
the default at read-only so the dangerous half of the product (auto-action)
is impossible until you deliberately switch it on — and the switch logs
exactly why it's asking, in plain language, at the moment it asks.

**The restricted-scope truth:** Google classifies `gmail.readonly` and
`gmail.modify` as **restricted scopes** — the strictest tier. If InboxPilot
were ever shipped as a public multi-tenant SaaS (other people's inboxes,
our OAuth client), Google would require:

- **OAuth verification** — a security review of the app, privacy policy,
  homepage, and data-handling disclosures (weeks of back-and-forth), plus
- **an annual CASA assessment** (Cloud Application Security Assessment) by
  an authorized lab — typically **five figures (USD) per year**, recurring.

That's a genuine moat against fast followers *and* a genuine future cost.
v0.1 sidesteps both: it's **self-hosted BYOK** — you create the OAuth
client in your own project, for your own inbox. Google requires **no
verification for personal/internal use** of your own client in test mode.
This document would need a rewrite the day we go multi-tenant; until then,
this is the whole story.

**Privacy note (also in the README):** email text sent for triage goes to
TypeSafe AI — US-only hosting, vague retention ("as long as reasonably
necessary"), no training on your inputs per their policy, zero-retention
only on enterprise tiers. Labels, thresholds, corrections, and the audit
log stay in local SQLite. Nothing else leaves your machine.

---

## Revoking access

- **Stop InboxPilot from reading mail:** delete
  `~/.config/inboxpilot/token.json`, or go to
  <https://myaccount.google.com/permissions> → InboxPilot → **Remove access**.
- **Full teardown:** delete `~/.config/inboxpilot/` entirely.

## Troubleshooting

- **"Redirect URI mismatch" / callback never arrives:** the localhost
  callback server binds `127.0.0.1` on a random free port. Corporate VPNs
  or firewalls that block loopback connections break it — disconnect the
  VPN for the 30-second sign-in, then reconnect.
- **Browser doesn't open:** copy the URL printed in the terminal.
- **`client_secret.json` not found:** re-do Step 4; the file must be valid
  JSON containing `client_id` and `client_secret` (the standard Google
  download has them under `"installed"`).
- **Token expired / 401 errors:** delete `~/.config/inboxpilot/token.json`
  and run again — you'll re-consent once.
- **"This app is blocked" instead of the unverified-app warning:** you
  skipped the Test users step — add your address under OAuth consent
  screen → Test users (Step 3.5).
