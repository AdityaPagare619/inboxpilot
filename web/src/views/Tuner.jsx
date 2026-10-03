import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { Loading, ErrorBox, useApi } from '../components/ui';

const DEFAULTS = { tau_cat: 0.85, tau_noise: 0.95, delta: 0.15 };

function Slider({ label, value, min, max, step, onChange, format, hint }) {
  return (
    <div className="slider-row">
      <div className="slider-top">
        <label>{label}</label>
        <span className="val">{format ? format(value) : value}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(parseFloat(e.target.value))} />
      {hint && <div className="slider-hint">{hint}</div>}
    </div>
  );
}

function WhatIfTable({ before, after }) {
  const keys = ['auto_label', 'auto_archive', 'digest'];
  const labels = { auto_label: '🏷 auto-label', auto_archive: '🗄 auto-archive', digest: '📋 digest' };
  const colors = { auto_label: '#2dd4bf', auto_archive: '#38bdf8', digest: '#a78bfa' };
  return (
    <div>
      <div className="vs-tag">before → after · your sliders vs current thresholds</div>
      <div className="whatif-head">
        <span />
        <span className="num">before</span>
        <span className="num">after</span>
        <span className="num">Δ</span>
      </div>
      {keys.map((k) => {
        const b = before?.[k] ?? '—';
        const a = after?.[k] ?? '—';
        const d = (typeof b === 'number' && typeof a === 'number') ? a - b : null;
        const dCls = d == null || d === 0 ? 'delta-zero' : d > 0 ? 'delta-pos' : 'delta-neg';
        const dTxt = d == null ? '—' : d === 0 ? '=' : `${d > 0 ? '+' : ''}${d}`;
        return (
          <div key={k} className="whatif-row">
            <span style={{ color: 'var(--txt-dim)', fontSize: 12.5 }}>{labels[k]}</span>
            <span className="num" style={{ color: 'var(--txt-faint)' }}>{b}</span>
            <span className="num" style={{ color: colors[k], fontWeight: 700 }}>{a}</span>
            <span className={`num ${dCls}`} style={{ fontWeight: 700 }}>{dTxt}</span>
          </div>
        );
      })}
      <div className="note" style={{ marginTop: 8 }}>Δ is after − before. No arrows-to-self: each cell compares the two runs.</div>
    </div>
  );
}

function CountBars({ before, after, title }) {
  const keys = ['auto_label', 'auto_archive', 'digest'];
  const labels = { auto_label: '🏷 auto-label', auto_archive: '🗄 auto-archive', digest: '📋 digest' };
  const colors = { auto_label: '#2dd4bf', auto_archive: '#38bdf8', digest: '#a78bfa' };
  const max = Math.max(1, ...keys.flatMap((k) => [before?.[k] || 0, after?.[k] || 0]));
  return (
    <div>
      <div className="vs-tag">{title}</div>
      {keys.map((k) => (
        <div key={k} style={{ marginBottom: 10 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, marginBottom: 4 }}>
            <span style={{ color: 'var(--txt-dim)' }}>{labels[k]}</span>
            <span className="num"><span style={{ color: 'var(--txt-faint)' }}>{before?.[k] ?? '—'}</span> → <b style={{ color: colors[k] }}>{after?.[k] ?? '—'}</b></span>
          </div>
          <div className="confbar-track" style={{ height: 8 }}>
            <div className="confbar-fill" style={{ width: `${((after?.[k] || 0) / max) * 100}%`, background: colors[k] }} />
          </div>
        </div>
      ))}
    </div>
  );
}

export default function Tuner({ seed, notify }) {
  const [fnCost, setFnCost] = useState(400);
  const [tauCat, setTauCat] = useState(DEFAULTS.tau_cat);
  const [tauNoise, setTauNoise] = useState(DEFAULTS.tau_noise);
  const [delta, setDelta] = useState(DEFAULTS.delta);
  const [preview, setPreview] = useState(null); // {before, after}
  const [previewing, setPreviewing] = useState(false);
  const [report, setReport] = useState(null);
  const [applying, setApplying] = useState(false);
  const debRef = useRef(null);

  const { data: inbox, loading: iLoading, error: iError, reload: iReload } = useApi(() => api.inbox(seed), [seed]);

  const baseline = inbox?.thresholds || DEFAULTS;

  // Debounced what-if preview: before = baseline thresholds, after = slider thresholds, same fn cost.
  useEffect(() => {
    setPreviewing(true);
    clearTimeout(debRef.current);
    debRef.current = setTimeout(async () => {
      try {
        const [b, a] = await Promise.all([
          api.tune({ seed, fn_cost: fnCost, preview: true, thresholds: baseline }),
          api.tune({ seed, fn_cost: fnCost, preview: true, thresholds: { tau_cat: tauCat, tau_noise: tauNoise, delta } }),
        ]);
        setPreview({ before: b.counts || b.counts_after || b, after: a.counts || a.counts_after || a });
      } catch (e) {
        setPreview({ error: e.message });
      } finally { setPreviewing(false); }
    }, 550);
    return () => clearTimeout(debRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fnCost, tauCat, tauNoise, delta, seed, inbox]);

  async function applyTune() {
    setApplying(true); setReport(null);
    try {
      const r = await api.tune({ seed, fn_cost: fnCost, apply: true, thresholds: { tau_cat: tauCat, tau_noise: tauNoise, delta } });
      setReport(r);
      if (r.applied) {
        notify({ type: 'ok', msg: `🎛️ Tune applied${r.provisional ? ' (provisional)' : ''} — utility ${r.utility_before} → ${r.utility_after}.` });
        iReload();
      } else {
        notify({ type: 'warn', msg: '🛑 The tuner refused. It needs more fuel (see below).' });
      }
    } catch (e) {
      notify({ type: 'bad', msg: `Tune failed: ${e.message}` });
      setReport({ applied: false, error: e.message });
    } finally { setApplying(false); }
  }

  const reset = () => { setTauCat(DEFAULTS.tau_cat); setTauNoise(DEFAULTS.tau_noise); setDelta(DEFAULTS.delta); setFnCost(400); };

  if (iLoading) return <Loading msg="Loading tuner playground…" />;
  if (iError) return <ErrorBox error={iError} onRetry={iReload} />;

  const utilDelta = report && report.utility_before != null && report.utility_after != null
    ? report.utility_after - report.utility_before : null;

  return (
    <div>
      <div className="view-head">
        <div>
          <h1 className="view-title">Tuner playground</h1>
          <p className="view-sub">Move the sliders. Watch what the gate <i>would</i> do — then ask the tuner to commit.</p>
        </div>
        <div className="spacer" />
        <button className="btn btn-ghost btn-sm" onClick={reset}>↺ reset sliders</button>
      </div>

      <div className="callout">
        💰 <b>Asymmetric cost, stated plainly.</b> Missing an urgent founder email (false negative) hurts far more than a false alarm.
        The <b>FN cost</b> slider says how many times worse — 100× to 1000×. The tuner optimizes expected utility, not accuracy.
      </div>

      <div className="grid grid-2">
        <div className="panel">
          <h3 className="panel-title">⚖️ What-if controls</h3>
          <Slider label="False-negative cost" value={fnCost} min={100} max={1000} step={25} onChange={setFnCost}
            format={(v) => `${v}×`} hint="Missing one urgent mail = this many false alarms. Founder math." />
          <Slider label="τ_cat — category confidence to auto-act" value={tauCat} min={0.70} max={0.95} step={0.01} onChange={setTauCat}
            format={(v) => v.toFixed(2)} hint="Below this → the digest, not the labeler." />
          <Slider label="τ_noise — confidence to auto-archive" value={tauNoise} min={0.90} max={0.99} step={0.005} onChange={setTauNoise}
            format={(v) => v.toFixed(3)} hint="Archive is destructive — the bar is high on purpose." />
          <Slider label="δ — top-1 minus top-2 margin" value={delta} min={0.05} max={0.25} step={0.01} onChange={setDelta}
            format={(v) => v.toFixed(2)} hint="Ambiguous races go to the digest even if the winner is confident." />
          <div className="btn-row" style={{ marginTop: 16 }}>
            <button className="btn btn-amber" onClick={applyTune} disabled={applying}>
              {applying ? 'Tuning…' : '🎛️ Apply tune (local tuner)'}
            </button>
          </div>
          <div className="note" style={{ marginTop: 8 }}>Apply runs the real tuner logic locally in this demo — no server, no keys, no email access. It will refuse honestly if it lacks the labels, and tell you why.</div>
        </div>

        <div className="panel">
          <h3 className="panel-title">🔮 Live what-if {previewing && <span className="note">(updating…)</span>}</h3>
          {preview?.error && <div className="note" style={{ color: 'var(--rose)' }}>Preview failed: {preview.error}</div>}
          <WhatIfTable before={preview?.before} after={preview?.after} />
          <div className="divider" />
          <div className="note">
            Live thresholds: <span className="mono">τ_cat {baseline.tau_cat} · τ_noise {baseline.tau_noise} · δ {baseline.delta}</span><br />
            Counts are computed by the real triage logic against the fixture inbox with simulated Jev probabilities (seed {seed}).
          </div>
        </div>
      </div>

      {/* honesty floors */}
      <div className="panel">
        <h3 className="panel-title">🛡️ Honesty floors — the tuner will not bluff</h3>
        <div className="grid grid-3">
          <div className="stat"><div className="sv num" style={{ color: 'var(--rose)' }}>&lt;10</div><div className="sl">labels → refuse</div><div className="note" style={{ marginTop: 8 }}>Not enough signal. The tuner says no and shows its work.</div></div>
          <div className="stat"><div className="sv num" style={{ color: 'var(--amber)' }}>10–49</div><div className="sl">labels → provisional</div><div className="note" style={{ marginTop: 8 }}>Real thresholds, labeled fragile. Trust, but verify.</div></div>
          <div className="stat"><div className="sv num" style={{ color: 'var(--lime)' }}>50+</div><div className="sl">labels → stable</div><div className="note" style={{ marginTop: 8 }}>Enough corrections to commit. Ship it.</div></div>
        </div>
        <div className="note" style={{ marginTop: 10 }}>Fuel up in the Digest Queue — every correction is a label the tuner drinks.</div>
      </div>

      {/* apply report */}
      {report && (
        <div className="panel" style={{ borderColor: report.applied ? 'rgba(163,230,53,.4)' : 'rgba(251,113,133,.4)' }}>
          <h3 className="panel-title">{report.applied ? '✅ Tune report — applied' : '🛑 Tune report — refused'}</h3>
          {report.error && <div className="note" style={{ color: 'var(--rose)' }}>{report.error}</div>}
          <div className="grid grid-4" style={{ marginBottom: 12 }}>
            <div className="stat"><div className="sv num" style={{ fontSize: 24 }}>{report.n_labels ?? '—'}</div><div className="sl">labels seen</div></div>
            <div className="stat"><div className="sv num" style={{ fontSize: 24 }}>{report.provisional ? '⚠️ yes' : 'no'}</div><div className="sl">provisional</div></div>
            <div className="stat"><div className="sv num" style={{ fontSize: 24 }}>{report.utility_before ?? '—'}</div><div className="sl">utility before</div></div>
            <div className="stat"><div className={`sv num ${utilDelta == null ? '' : utilDelta > 0 ? 'delta-pos' : utilDelta < 0 ? 'delta-neg' : 'delta-zero'}`} style={{ fontSize: 24 }}>{report.utility_after ?? '—'}</div><div className="sl">utility after {utilDelta != null && <span className={utilDelta > 0 ? 'delta-pos' : utilDelta < 0 ? 'delta-neg' : 'delta-zero'}>({utilDelta > 0 ? '+' : ''}{utilDelta.toFixed(3)})</span>}</div></div>
          </div>
          {report.notes?.length > 0 && (
            <><div className="vs-tag">the tuner's own words</div>
            <ul className="reasons">{report.notes.map((n, i) => <li key={i}>{n}</li>)}</ul></>
          )}
          {(report.counts_before || report.counts_after) && (
            <div style={{ marginTop: 14 }}><CountBars before={report.counts_before} after={report.counts_after} title="counts: before → after" /></div>
          )}
          {!report.applied && (
            <div className="callout amber" style={{ marginTop: 12 }}>
              🙏 <b>This is the refuse path, working as designed.</b> The tuner didn't guess — it told you it needs more corrections. Head to the Digest Queue, correct a few mails, come back.
            </div>
          )}
          <details style={{ marginTop: 10 }}>
            <summary>Raw response</summary>
            <div className="codebox" style={{ marginTop: 8 }}>{JSON.stringify(report, null, 2)}</div>
          </details>
        </div>
      )}
    </div>
  );
}
