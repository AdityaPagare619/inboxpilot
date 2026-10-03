import { api } from '../api';
import { Loading, ErrorBox, useApi } from '../components/ui';

function PlaceholderCard({ emoji, title, desc, cta }) {
  return (
    <div className="card" style={{ opacity: 0.92 }}>
      <div style={{ fontSize: 26, marginBottom: 8 }}>{emoji}</div>
      <div style={{ fontWeight: 800, fontSize: 15, marginBottom: 6 }}>{title}</div>
      <div className="note" style={{ marginBottom: 14, lineHeight: 1.6 }}>{desc}</div>
      <button className="btn" disabled title="Available once you connect your own key">🔒 {cta}</button>
      <div className="note" style={{ marginTop: 8 }}>coming with <b>your</b> key — your later step, not today's demo</div>
    </div>
  );
}

export default function CostPrivacy() {
  const { data, loading, error, reload } = useApi(() => api.cost(), []);

  if (loading) return <Loading msg="Doing the honest math…" />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;

  const scopes = data.scopes || {};

  return (
    <div>
      <div className="view-head">
        <div>
          <h1 className="view-title">Cost &amp; privacy</h1>
          <p className="view-sub">The honest math, the scopes, and what this demo is and isn't. No fine print — just print.</p>
        </div>
      </div>

      <div className="panel" style={{ borderColor: 'rgba(45,212,191,.35)' }}>
        <h3 className="panel-title">💸 The honest math</h3>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
          <span className="num" style={{ fontSize: 44, fontWeight: 800, color: 'var(--teal)' }}>${data.cost ?? '—'}</span>
          <span className="note">per user per year — estimated Jev classification cost for a founder-scale inbox</span>
        </div>
        <div className="callout" style={{ marginTop: 14 }}>
          Why so cheap? Jev answers <b>typed questions with calibrated probabilities</b> — no giant LLM prompt per mail, no output tokens billed.
          Three tiny decisions per email, 70–500ms each. You're paying for answers, not eloquence.
        </div>
      </div>

      <div className="panel">
        <h3 className="panel-title">🔑 Gmail scopes — the CASA moat</h3>
        <div className="kv"><span className="k">📖 Read-only — <span className="mono">gmail.readonly</span></span><span className="v" style={{ color: 'var(--lime)' }}>{scopes.readonly ?? 'triage + digest'}</span></div>
        <div className="kv"><span className="k">✏️ Modify — <span className="mono">gmail.modify</span></span><span className="v" style={{ color: 'var(--amber)' }}>{scopes.modify ?? 'label + archive actions'}</span></div>
        <div className="note" style={{ marginTop: 12, lineHeight: 1.7 }}>
          CASA (Google's Cloud Application Security Assessment) is the moat: restricted scopes require annual third-party security review.
          InboxPilot earns <b>modify</b> only after passing — which is exactly why the confidence gate exists.
          Auto-actions never fire without the probabilities to back them. Least privilege, always.
        </div>
      </div>

      {data.privacy?.length > 0 && (
        <div className="panel">
          <h3 className="panel-title">🛡️ Privacy, in plain language</h3>
          <ul className="reasons">
            {data.privacy.map((p, i) => <li key={i}>{p}</li>)}
          </ul>
        </div>
      )}

      {data.demo_caveats?.length > 0 && (
        <div className="panel" style={{ borderColor: 'rgba(245,165,36,.35)' }}>
          <h3 className="panel-title">⚠️ Demo caveats — read these</h3>
          <ul className="reasons">
            {data.demo_caveats.map((c, i) => <li key={i}>{c}</li>)}
          </ul>
        </div>
      )}

      <h3 className="panel-title" style={{ marginTop: 22 }}>🚀 Connect your own — your later steps</h3>
      <div className="grid grid-2">
        <PlaceholderCard
          emoji="🧠"
          title="Your TypeSafe API key"
          desc="Bring your own Jev key and the scripted mock answers get replaced by real typed classifications — same questions, same gates, real probabilities."
          cta="Add API key — coming with your key"
        />
        <PlaceholderCard
          emoji="📬"
          title="Your Gmail (OAuth)"
          desc="Connect your real inbox via Google OAuth with least-privilege scopes. Read-only first; modify only after you watch the gate earn your trust."
          cta="Connect Gmail — coming with your key"
        />
      </div>
      <div className="footer-note">These buttons are honestly disabled. No fake "connected" states here — humility is the product.</div>
    </div>
  );
}
