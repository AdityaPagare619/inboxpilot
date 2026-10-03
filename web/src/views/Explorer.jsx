import { useEffect, useState } from 'react';
import { api, catBadge, actionBadge, pct } from '../api';
import { ConfBar, Loading, ErrorBox, useApi } from '../components/ui';

const BAR_COLORS = ['#2dd4bf', '#38bdf8', '#a78bfa', '#f5a524', '#a1a1aa', '#fb7185'];

function QuestionBlock({ q, i }) {
  const probs = q.probabilities || q.category_probs || q.distribution;
  return (
    <div className="panel" style={{ marginBottom: 14 }}>
      <h3 className="panel-title">Q{i + 1} · {q.title || q.id || 'question'}</h3>
      {q.question && <div style={{ fontSize: 13.5, marginBottom: 10, color: 'var(--txt-dim)' }}>{q.question}</div>}
      {probs ? (
        <div>
          {Object.entries(probs).sort((a, b) => b[1] - a[1]).map(([cat, p], j) => (
            <ConfBar key={cat} label={cat} value={p} color={BAR_COLORS[j % BAR_COLORS.length]} />
          ))}
        </div>
      ) : q.p != null ? (
        <ConfBar label={q.label || 'probability'} value={q.p} color="#f5a524" />
      ) : (
        <div className="codebox">{JSON.stringify(q, null, 2)}</div>
      )}
    </div>
  );
}

function ExplainDetail({ id, seed }) {
  const { data, loading, error, reload } = useApi(() => api.explain(id, seed), [id, seed]);
  if (loading) return <Loading msg="Asking Jev why…" />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;

  const d = data.decision || {};
  const th = data.thresholds || {};
  const branch = d.branch_rule || {};
  const contacts = data.contacts || [];
  const honesty = data.honesty || [];
  const ans = data.answers || {};

  // The static snapshot stores question definitions as an object keyed by id
  // ({urgency, category, needs_reply}); the old server returned an array.
  // Normalize defensively, then merge this mail's ACTUAL answers in so the
  // panel shows what Jev said about THIS mail, not just the question text.
  const qlist = (Array.isArray(data.questions)
    ? data.questions
    : Object.entries(data.questions || {}).map(([qid, q]) => ({ id: qid, ...q }))
  ).map((q) => {
    if (q.id === 'urgency') return { ...q, p: ans.urgency_p ?? d.urgency_p };
    if (q.id === 'needs_reply') return { ...q, p: ans.needs_reply_p ?? d.needs_reply_p };
    if (q.id === 'category') return { ...q, probabilities: ans.probs };
    return q;
  });

  const thRow = (name, val, desc) => (
    <div className="kv"><span className="k">{name} — {desc}</span><span className="v">{val}</span></div>
  );

  return (
    <div>
      <div className="card">
        <div className="mail-from">{data.email?.from}</div>
        <div className="mail-subj">{data.email?.subject}</div>
        <div className="tag-row">
          <span className={`badge ${actionBadge(d.action)}`}>{d.action}</span>
          <span className={`badge ${catBadge(d.category)}`}>{d.category}</span>
          <span className="badge b-dim">cat conf <span className="num">{pct(d.category_confidence)}</span></span>
          <span className="badge b-dim">urgency <span className="num">{pct(d.urgency_p)}</span></span>
          <span className="badge b-dim">needs-reply <span className="num">{pct(d.needs_reply_p)}</span></span>
        </div>
      </div>

      <div className="panel">
        <h3 className="panel-title">🧠 The 3 Jev answers — for this mail</h3>
        {qlist.map((q, i) => <QuestionBlock key={q.id || i} q={q} i={i} />)}
        {qlist.length === 0 && <div className="note">No question detail returned by the API.</div>}
      </div>

      <div className="panel">
        <h3 className="panel-title">🚦 Thresholds applied</h3>
        {thRow('τ_cat', th.tau_cat ?? '—', 'min category confidence to auto-act')}
        {thRow('τ_noise', th.tau_noise ?? '—', 'min confidence to auto-archive noise')}
        {thRow('δ (delta)', th.delta ?? '—', 'min top-1 − top-2 margin to call it decisive')}
        {thRow('urgent band', th.urgent_high != null ? `${th.urgent_low}–${th.urgent_high}` : '—', 'urgency decisive band')}
        {thRow('archive cap', th.urgency_archive_max ?? '—', 'never auto-archive at/above this urgency')}
        <div className="note" style={{ marginTop: 10 }}>If confidence clears τ and the margin clears δ, Jev acts. Otherwise it humbles itself into the digest. Tune these live in the Tuner Playground.</div>
      </div>

      <div className="panel">
        <h3 className="panel-title">🌿 Escalation-policy branch that fired</h3>
        {branch.title ? (
          <>
            <div style={{ fontWeight: 800, fontSize: 16, color: 'var(--violet)' }}>{branch.id ? <span className="mono" style={{ fontSize: 12, color: 'var(--txt-faint)' }}>[{branch.id}] </span> : null}{branch.title}</div>
            {branch.quote && <div className="quote">“{branch.quote}”</div>}
          </>
        ) : <div className="note">No branch info returned.</div>}
      </div>

      <div className="panel">
        <h3 className="panel-title">📝 Reasons</h3>
        {d.reasons?.length ? (
          <ul className="reasons">{d.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
        ) : <div className="note">No reasons returned.</div>}
      </div>

      {contacts.length > 0 && (
        <div className="panel">
          <h3 className="panel-title">👥 Contacts recognized</h3>
          {contacts.map((c, i) => (
            <div className="kv" key={i}><span className="k">{c.name || c.email || `contact ${i + 1}`}</span><span className="v">{c.role || c.relationship || ''}</span></div>
          ))}
        </div>
      )}

      {honesty.length > 0 && (
        <div className="panel">
          <h3 className="panel-title">🙏 Honesty ledger</h3>
          <ul className="reasons">{honesty.map((h, i) => <li key={i}>{typeof h === 'string' ? h : JSON.stringify(h)}</li>)}</ul>
        </div>
      )}
    </div>
  );
}

export default function Explorer({ seed }) {
  const { data, loading, error, reload } = useApi(() => api.inbox(seed), [seed]);
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    if (data?.emails?.length && !selected) setSelected(data.emails[0].id);
  }, [data, selected]);

  if (loading) return <Loading msg="Loading the inbox…" />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;

  return (
    <div>
      <div className="view-head">
        <div>
          <h1 className="view-title">Confidence explorer</h1>
          <p className="view-sub">Click any mail. See exactly what Jev answered, what the gate did with it, and why — the trust layer, in full.</p>
        </div>
      </div>
      <div className="expl-grid">
        <div>
          {(data.emails || []).map((e) => (
            <div key={e.id} className={`card hoverable mail-list-item ${selected === e.id ? 'selected' : ''}`} onClick={() => setSelected(e.id)} style={{ padding: '12px 14px' }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <span className={`badge ${catBadge(e.decision?.category)}`}>{e.decision?.category}</span>
                <span className="num" style={{ fontSize: 12, color: 'var(--txt-dim)', marginLeft: 'auto' }}>{pct(e.decision?.category_confidence)}</span>
              </div>
              <div className="mail-subj" style={{ margin: '6px 0 2px', fontSize: 13.5 }}>{e.subject}</div>
              <div className="note">{e.from}</div>
            </div>
          ))}
        </div>
        <div>
          {selected ? <ExplainDetail key={selected + ':' + seed} id={selected} seed={seed} /> : <div className="empty">Pick a mail ←</div>}
        </div>
      </div>
    </div>
  );
}
