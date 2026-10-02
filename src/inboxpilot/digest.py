"""Morning digest rendering — the part of InboxPilot the founder actually reads.

Confident about what was handled, humble about what wasn't. Every
auto-action is listed with an undo path; every digest item shows why the
model wasn't sure enough to act alone.
"""

from __future__ import annotations


def _short(sender: str | None, n: int = 34) -> str:
    s = sender or "?"
    return s if len(s) <= n else s[: n - 1] + "…"


def render_text(store) -> str:
    """Plain-text digest for the terminal (and the demo)."""
    items = store.digest_items()
    handled = store.auto_handled_summary()

    urgent = [i for i in items if (i.get("urgency_p") or 0) >= 0.5]
    rest = [i for i in items if (i.get("urgency_p") or 0) < 0.5]

    lines = ["☕ InboxPilot — morning digest"]
    lines.append(
        f"{len(items) + sum(handled.values())} emails triaged · "
        f"{len(items)} need you · {sum(handled.values())} handled"
    )
    lines.append("")

    if urgent:
        lines.append(f"🔴 NEEDS YOU ({len(urgent)})")
        for i, it in enumerate(urgent, 1):
            lines.append(
                f"  {i}. \"{it['subject']}\" — {_short(it.get('sender'))}"
            )
            lines.append(
                f"     {it['category']} ({it['category_confidence']:.2f}), "
                f"urgency {it['urgency_p']:.2f}"
            )
            reasons = (it.get("reasons_json") or "[]")
            import json as _json

            for r in _json.loads(reasons)[:1]:
                lines.append(f"     ↳ {r}")
            lines.append(f"     approve: inboxpilot approve {it['email_id']}")
        lines.append("")

    if rest:
        lines.append(f"🟡 WORTH A GLANCE ({len(rest)})")
        for i, it in enumerate(rest, 1):
            lines.append(
                f"  {i}. \"{it['subject']}\" — {_short(it.get('sender'))} "
                f"[{it['category']} {it['category_confidence']:.2f}]"
            )
        lines.append("")

    auto_n = sum(handled.values())
    if auto_n:
        lines.append(f"✅ AUTO-HANDLED ({auto_n})")
        archived = sum(n for (a, _), n in handled.items() if a == "auto_archive")
        if archived:
            lines.append(f"  Archived {archived} noise (undo: inboxpilot undo <id>)")
        for (a, label), n in sorted(handled.items()):
            if a == "auto_label":
                lines.append(f"  Labeled {n} → {label}")
        lines.append("")

    if not items and not auto_n:
        lines.append("All quiet. Inbox zero energy. ✨")
    return "\n".join(lines)


def render_html(store) -> str:
    """Minimal HTML digest for `inboxpilot serve`."""
    items = store.digest_items()
    cards = []
    for it in items:
        cards.append(
            "<div class='card'>"
            f"<div class='subj'>{it['subject']}</div>"
            f"<div class='meta'>{it.get('sender') or ''} · {it['category']} "
            f"{it['category_confidence']:.2f} · urgency {it['urgency_p']:.2f}</div>"
            f"<form method='post' action='/approve'>"
            f"<input type='hidden' name='id' value='{it['email_id']}'>"
            "<button type='submit'>Approve suggestion</button>"
            "</form></div>"
        )
    body = "\n".join(cards) if cards else "<p>All quiet. ✨</p>"
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>InboxPilot digest</title>"
        "<style>body{font-family:system-ui;max-width:720px;margin:2em auto;padding:0 1em}"
        ".card{border:1px solid #ddd;border-radius:8px;padding:1em;margin-bottom:1em}"
        ".subj{font-weight:600}.meta{color:#666;font-size:.9em;margin:.4em 0}"
        "button{background:#111;color:#fff;border:0;border-radius:6px;padding:.5em 1em}</style>"
        "</head><body><h1>☕ InboxPilot — digest</h1>" + body + "</body></html>"
    )
