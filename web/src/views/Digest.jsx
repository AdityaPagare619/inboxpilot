import { useEffect, useState } from 'react';
import { api, catBadge, pct } from '../api';
import { ConfBar, UrgencyMeter, Loading, ErrorBox, useApi } from '../components/ui';

const CATS = ['needs_action', 'fyi', 'receipt', 'newsletter', 'noise'];
const CAT_EMOJI = { needs_action: '🔥', fyi: '💡', receipt: '🧾', newsletter: '📰', noise: '🗑' };

function CorrectModal({ email, seed, onClose, onDone, notify }) {
  const [category, setCategory] = useState(email.decision?.category || 'needs_action');
  const [urgent, setUrgent] = useState((email.decision?.urgency_p ?? 0) >= 0.5);
  const [sending, setSending] = useState(false);

  async function submit() {
    setSending(true);
    try {
      const r = await api.correct({ id: email.id, category, urgent, seed });
      notify({ type: 'ok', msg: `✅ Correction logged — "${email.subject.slice(0, 40)}…" → ${category} · ${urgent ? 'urgent' : 'not urgent'}. Tuner fuel: ${r.tuner_status?.n_labels ?? '?'} label${r.tuner_status?.n_labels === 1 ? '' : 's'}.` });
      onDone(r);
    } catch (e) {
      notify({ type: 'bad', msg: `❌ Correction failed: ${e.message}` });
    } finally { setSending(false); }
  }

  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>✏️ Correct the model</h3>
        <p className="sub">“{email.subject}” — tell it what it should have decided. This is the fuel the tuner drinks.</p>
        <div className="vs-tag">true category</div>
        <div className="opt-grid">
          {CATS.map((c) => (
            <button key={c} className={`opt ${category === c ? 'sel' : ''}`} onClick={() => setCategory(c)}>
              {CAT_EMOJI[c]} {c}
            </button>
          ))}
        </div>
        <div className="toggle-row">
          <div className={`switch ${urgent ? 'on' : ''}`} onClick={() => setUrgent((u) => !u)} />
          <span style={{ fontWeight: 700 }}>{urgent ? '🔥 urgent' : '😌 not urgent'}</span>
        </div>
        <div className="btn-row" style={{ marginTop: 18 }}>
          <button className="btn btn-primary" onClick={submit} disabled={sending}>{sending ? 'Logging…' : 'Log correction'}</button>
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}

export default function Digest({ seed, notify }) {
  const { data, loading, error, reload } = useApi(() => api.inbox(seed), [seed]);
  // Handled state lives in the api layer (persisted to localStorage) so the
  // dashboard greeting, digest counts, and tuner fuel all stay live — and
  // survive a reload. `data.handled` is the source of truth after each fetch.
  const [correcting, setCorrecting] = useState(null);
  const [fuel, setFuel] = useState({ n_labels: 0, status: 'locked', message: 'Log corrections to fuel the tuner.' });

  useEffect(() => {
    if (data?.tuner_status) setFuel(data.tuner_status);
  }, [data]);

  if (loading) return <Loading msg="Brewing your morning digest…" />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;

  const handled = data.handled || {};
  const digestMails = (data.emails || []).filter((e) => e.decision?.action === 'digest');
  const pending = digestMails.filter((e) => !handled[e.id]);
  const finished = digestMails.filter((e) => handled[e.id]);

  async function approve(email) {
    await api.markHandled(email.id, 'approved');
    const s = email.decision?.suggested || {};
    notify({ type: 'ok', msg: `👍 Approved: “${(s.label || s.action || 'suggestion').replace(/_/g, ' ')}” applied to “${email.subject.slice(0, 36)}…”` });
    reload();
  }
  async function undo(email) {
    await api.unhandle(email.id);
    notify({ type: 'info', msg: `↩️ Undone — “${email.subject.slice(0, 36)}…” is back in the queue.` });
    reload();
  }
  async function handleCorrected(resp) {
    setFuel(resp.tuner_status || fuel);
    await api.markHandled(resp.email_id, 'corrected');
    setCorrecting(null);
    reload(); // corrections retriage the inbox server-side; refresh
  }

  const fuelPct = Math.min(100, (fuel.n_labels / 50) * 100);

  return (
    <div>
      <div className="view-head">
        <div>
          <h1 className="view-title">☀️ Good morning, founder</h1>
          <p className="view-sub">{pending.length} mail the model wasn't sure about — it stayed humble so you don't have to guess. {finished.length > 0 && `${finished.length} handled.`}</p>
        </div>
        <div className="spacer" />
        <span className="badge b-digest">{pending.length} pending</span>
      </div>

      {/* tuner fuel */}
      <div className="panel">
        <h3 className="panel-title">⛽ Tuner fuel — your corrections train the thresholds</h3>
        <div className="fuel-track"><div className="fuel-fill" style={{ width: `${fuelPct}%` }} /></div>
        <div className="fuel-marks">
          <span><span className="num" style={{ color: 'var(--txt)', fontWeight: 700 }}>{fuel.n_labels}</span>/10 unlock tuning</span>
          <span>{fuel.n_labels}/50 stable tuner</span>
        </div>
        <div className="note" style={{ marginTop: 8 }}>
          {fuel.status === 'locked' && '🔒 Under 10 labels the tuner refuses to tune — not enough signal. (Try correcting anyway; watch it refuse.)'}
          {fuel.status === 'provisional' && '⚠️ Provisional tuner: 10+ labels, real but fragile. 50 for stable.'}
          {fuel.status === 'stable' && '✅ Stable tuner unlocked — 50+ labels. Thresholds can now be trusted.'}
          {fuel.message && ` ${fuel.message}`}
        </div>
      </div>

      {pending.length === 0 && (
        <div className="empty"><div className="big">🎉</div>Inbox zero on the digest. The humble queue is empty — go build something.</div>
      )}

      {pending.map((email) => {
        const d = email.decision || {};
        const sug = d.suggested || {};
        return (
          <div className="card hoverable" key={email.id}>
            <div className="mail-head">
              <div style={{ minWidth: 0 }}>
                <div className="mail-from">{email.from}</div>
                <div className="mail-subj">{email.subject}</div>
              </div>
              <div className="mail-date">{email.date}</div>
            </div>
            <div className="mail-snip">{email.snippet}</div>
            <div className="tag-row">
              <span className={`badge ${catBadge(d.category)}`}>{d.category}</span>
              <span className="badge b-dim">confidence <span className="num">{pct(d.category_confidence)}</span></span>
              <span className="badge b-warn">🔥 {pct(d.urgency_p)} urgent</span>
            </div>
            <div className="callout violet" style={{ marginTop: 12 }}>
              🤖 <b>Jev suggests:</b> {(sug.label || sug.action || 'review').replace(/_/g, ' ')}
              {d.reasons?.[0] && <span className="note" style={{ display: 'block', marginTop: 4 }}>“{d.reasons[0]}”</span>}
            </div>
            <div className="mail-actions">
              <button className="btn btn-primary btn-sm" onClick={() => approve(email)}>👍 Approve</button>
              <button className="btn btn-sm" onClick={() => setCorrecting(email)}>✏️ Correct</button>
            </div>
          </div>
        );
      })}

      {finished.length > 0 && (
        <>
          <div className="divider" />
          <h3 className="panel-title">Handled this session ({finished.length})</h3>
          {finished.map((email) => (
            <div className="card done-card" key={email.id}>
              <div className="mail-head">
                <div>
                  <span className="mail-from">{email.from}</span>
                  <span className="done-stamp">{handled[email.id] === 'approved' ? '✓ approved' : '✏ corrected'}</span>
                  <div className="mail-subj">{email.subject}</div>
                </div>
                <div className="mail-date">{email.date}</div>
              </div>
              <div className="mail-actions">
                <button className="btn btn-ghost btn-sm" onClick={() => undo(email)}>↩️ Undo</button>
              </div>
            </div>
          ))}
        </>
      )}

      {correcting && (
        <CorrectModal email={correcting} seed={seed} onClose={() => setCorrecting(null)} onDone={handleCorrected} notify={notify} />
      )}
    </div>
  );
}
