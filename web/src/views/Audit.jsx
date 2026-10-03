import { useMemo, useState } from 'react';
import { api } from '../api';
import { Loading, ErrorBox, useApi } from '../components/ui';

const KIND_META = {
  decision: { emoji: '🧠', label: 'decision', cls: 'k-decision' },
  correction: { emoji: '✏️', label: 'correction', cls: 'k-correction' },
  tune: { emoji: '🎛️', label: 'tune', cls: 'k-tune' },
};

export default function Audit({ seed }) {
  const [filter, setFilter] = useState('all');
  const [openId, setOpenId] = useState(null);
  const { data, loading, error, reload } = useApi(() => api.audit(seed), [seed]);

  const entries = useMemo(() => {
    const list = data?.entries || [];
    return filter === 'all' ? list : list.filter((e) => e.kind === filter);
  }, [data, filter]);

  if (loading) return <Loading msg="Opening the audit log…" />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;

  const counts = { decision: 0, correction: 0, tune: 0 };
  (data.entries || []).forEach((e) => { if (counts[e.kind] != null) counts[e.kind]++; });

  return (
    <div>
      <div className="view-head">
        <div>
          <h1 className="view-title">Audit timeline</h1>
          <p className="view-sub">Every decision traceable. Nothing the machine did is a mystery — expand any entry for the full trace.</p>
        </div>
        <div className="spacer" />
        <button className="btn btn-ghost btn-sm" onClick={reload}>↻ Refresh</button>
      </div>

      {data.note && <div className="callout">{data.note}</div>}

      <div style={{ display: 'flex', gap: 8, marginBottom: 18, flexWrap: 'wrap' }}>
        <button className={`chip ${filter === 'all' ? 'active' : ''}`} onClick={() => setFilter('all')}>all <span className="num">· {(data.entries || []).length}</span></button>
        {Object.entries(KIND_META).map(([k, m]) => (
          <button key={k} className={`chip ${filter === k ? 'active' : ''}`} onClick={() => setFilter(k)}>
            {m.emoji} {m.label}s <span className="num">· {counts[k]}</span>
          </button>
        ))}
      </div>

      {entries.length === 0 && (
        <div className="empty"><div className="big">📜</div>No entries under this filter yet. Correct a mail or run the tuner and the log will grow.</div>
      )}

      <div className="panel">
        {entries.map((e, i) => {
          const m = KIND_META[e.kind] || { emoji: '•', label: e.kind, cls: '' };
          const id = `${e.ts}-${i}`;
          const open = openId === id;
          return (
            <div key={id} className={`audit-entry ${m.cls}`}>
              <div className="audit-head" onClick={() => setOpen(open ? null : id)}>
                <span style={{ fontSize: 16 }}>{m.emoji}</span>
                <span className="audit-subj">{e.subject}</span>
                <span className={`badge ${e.kind === 'decision' ? 'b-dim' : e.kind === 'correction' ? 'b-warn' : 'b-digest'}`}>{m.label}</span>
                <span className="audit-ts">{e.ts}</span>
              </div>
              {e.summary && !open && <div className="note" style={{ margin: '0 0 8px 26px' }}>{e.summary}</div>}
              {open && (
                <div className="audit-detail">
                  {e.summary ? e.summary + '\n\n' : ''}{typeof e.detail === 'string' ? e.detail : JSON.stringify(e.detail, null, 2)}
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div className="footer-note">newest first · seed <span className="mono">{data.seed ?? seed}</span></div>
    </div>
  );
}
