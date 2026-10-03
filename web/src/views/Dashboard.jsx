import { useEffect, useMemo, useRef, useState } from 'react';
import { api, actionBadge, catBadge, pct } from '../api';
import { ConfBar, UrgencyMeter, Stat, Loading, ErrorBox, useApi } from '../components/ui';

const ACTION_COLOR = { auto_label: '#2dd4bf', auto_archive: '#38bdf8', digest: '#a78bfa' };
const ACTION_LABEL = { auto_label: 'auto-label', auto_archive: 'auto-archive', digest: 'digest' };

function DecisionCard({ email }) {
  const [open, setOpen] = useState(false);
  const d = email.decision || {};
  const confColor = (d.category_confidence ?? 0) >= 0.85 ? '#2dd4bf' : (d.category_confidence ?? 0) >= 0.7 ? '#f5a524' : '#fb7185';
  return (
    <div className="card hoverable">
      <div className="mail-head">
        <div style={{ minWidth: 0 }}>
          <div className="mail-from">{email.from}</div>
          <div className="mail-subj">{email.subject}</div>
        </div>
        <div className="mail-date">{email.date}{email.thread_n ? ` · ${email.thread_n} msgs` : ''}</div>
      </div>
      <div className="mail-snip">{email.snippet}</div>
      <div className="tag-row">
        <span className={`badge ${actionBadge(d.action)}`}><span className="dot" />{ACTION_LABEL[d.action] || d.action}</span>
        <span className={`badge ${catBadge(d.category)}`}>{d.category}</span>
        {d.label && <span className="badge b-dim">🏷 {d.label}</span>}
        {d.suggested && d.suggested.action !== d.action && (
          <span className="badge b-dim" title="The model suggested a different action">suggested: {ACTION_LABEL[d.suggested.action] || d.suggested.action}</span>
        )}
      </div>
      <div className="grid grid-2" style={{ marginTop: 12 }}>
        <div>
          <div className="vs-tag">category confidence</div>
          <ConfBar value={d.category_confidence} color={confColor} showPct={true} />
        </div>
        <div>
          <div className="vs-tag">urgency</div>
          <UrgencyMeter value={d.urgency_p} />
        </div>
      </div>
      <div className="mail-actions">
        <button className="expand-btn" onClick={() => setOpen((o) => !o)}>
          {open ? '▾ hide reasoning' : '▸ why this decision'}
        </button>
        {d.branch_rule?.title && <span className="note">via <b style={{ color: 'var(--violet)' }}>{d.branch_rule.title}</b></span>}
      </div>
      {open && (
        <div style={{ marginTop: 8 }}>
          {d.branch_rule?.quote && <div className="quote">“{d.branch_rule.quote}”</div>}
          {d.reasons?.length > 0 && (
            <ul className="reasons">
              {d.reasons.map((r, i) => <li key={i}>{r}</li>)}
            </ul>
          )}
          {d.model && <div className="note" style={{ marginTop: 8 }}>model: <span className="mono">{d.model}</span></div>}
        </div>
      )}
    </div>
  );
}

export default function Dashboard({ seed, onRerun, notify }) {
  const [filter, setFilter] = useState('all');
  const { data, loading, error, reload } = useApi(() => api.inbox(seed), [seed]);
  const rerunArmed = useRef(false);
  const prevCounts = useRef(null);

  // After a re-run lands, compare counts and toast the flip.
  useEffect(() => {
    if (!data?.counts) return;
    if (rerunArmed.current && prevCounts.current) {
      const b = prevCounts.current, a = data.counts;
      const parts = [];
      for (const k of ['auto_label', 'auto_archive', 'digest']) {
        if (a[k] !== b[k]) parts.push(`${k.replace(/_/g, '-')} ${b[k]}→${a[k]}`);
      }
      notify(
        parts.length
          ? { type: 'warn', msg: `🎲 Jev flip! ${parts.join(' · ')} (seed ${data.seed}) — that 1–2% non-determinism is real.` }
          : { type: 'ok', msg: `🎲 Re-ran triage (seed ${data.seed}) — no flips this time. Jev held its nerve.` }
      );
    }
    prevCounts.current = data.counts;
    rerunArmed.current = false;
  }, [data, notify]);

  function handleRerun() {
    rerunArmed.current = true;
    onRerun();
  }

  const filtered = useMemo(() => {
    if (!data?.emails) return [];
    return filter === 'all' ? data.emails : data.emails.filter((e) => e.decision?.action === filter);
  }, [data, filter]);

  if (loading) return <Loading msg="Triaging the fixture inbox…" />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  const counts = data.counts || {};

  const actions = ['all', 'auto_label', 'auto_archive', 'digest'];
  const actionCount = (a) => (a === 'all' ? data.emails.length : data.emails.filter((e) => e.decision?.action === a).length);

  return (
    <div>
      <div className="view-head">
        <div>
          <h1 className="view-title">Triage dashboard</h1>
          <p className="view-sub">{data.greeting || 'The pipeline, made visible — every mail, every decision, every confidence.'}</p>
        </div>
        <div className="spacer" />
        <button className="btn btn-primary" onClick={handleRerun}>🎲 Re-run triage</button>
      </div>

      {/* pipeline */}
      <div className="panel">
        <h3 className="panel-title">The pipeline</h3>
        <div className="pipeline">
          <div className="pstage"><div className="pnum num">{counts.total ?? '—'}</div><div className="plab">📥 inbox<br />fixture mail</div></div>
          <div className="parrow">→</div>
          <div className="pstage"><div className="pnum num" style={{ color: 'var(--sky)' }}>3</div><div className="plab">🧠 Jev classify<br />urgency · category · needs-reply</div></div>
          <div className="parrow">→</div>
          <div className="pstage"><div className="pnum num" style={{ color: 'var(--amber)' }}>τ</div><div className="plab">🚦 confidence gate<br />thresholds + escalation policy</div></div>
          <div className="parrow">→</div>
          <div className="pstage"><div className="pnum num" style={{ color: ACTION_COLOR.auto_label }}>{counts.auto_label ?? '—'}</div><div className="plab">🏷 auto-label<br />confident category</div></div>
          <div className="parrow">→</div>
          <div className="pstage"><div className="pnum num" style={{ color: ACTION_COLOR.auto_archive }}>{counts.auto_archive ?? '—'}</div><div className="plab">🗄 auto-archive<br />confident noise</div></div>
          <div className="parrow">→</div>
          <div className="pstage"><div className="pnum num" style={{ color: ACTION_COLOR.digest }}>{counts.digest ?? '—'}</div><div className="plab">📋 digest<br />humble queue</div></div>
        </div>
      </div>

      {data.demo_notes?.length > 0 && (
        <div className="callout amber">🔬 <b>Simulated Jev flips.</b> {data.demo_notes[0]} <span className="mono">{`seed=${data.seed}`}</span> — hit <b>Re-run triage</b> to roll the dice and watch the ~2% non-determinism move counts.</div>
      )}
      {data.seed_notice && (
        <div className="callout">🔁 {data.seed_notice}</div>
      )}

      {/* stats */}
      <div className="grid grid-4" style={{ marginBottom: 18 }}>
        <Stat value={counts.total ?? '—'} label="total mail" />
        <Stat value={counts.auto_label ?? '—'} label="auto-labeled" accent="teal" />
        <Stat value={counts.auto_archive ?? '—'} label="auto-archived" accent="sky" />
        <Stat value={counts.digest ?? '—'} label="in digest" accent="violet" />
      </div>

      {/* filter */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        {actions.map((a) => (
          <button key={a} className={`chip ${filter === a ? 'active' : ''}`} onClick={() => setFilter(a)}>
            {a === 'all' ? 'all mail' : ACTION_LABEL[a]} <span className="num">· {actionCount(a)}</span>
          </button>
        ))}
      </div>

      {filtered.length === 0 && (
        <div className="empty"><div className="big">📭</div>No mail under this filter. The gate is honest — nothing forced through.</div>
      )}
      {filtered.map((e) => <DecisionCard key={e.id} email={e} />)}
      <div className="footer-note">mode: <span className="mono">{data.mode}</span> · thresholds τ_cat <span className="mono">{data.thresholds?.tau_cat}</span> τ_noise <span className="mono">{data.thresholds?.tau_noise}</span> δ <span className="mono">{data.thresholds?.delta}</span></div>
    </div>
  );
}
