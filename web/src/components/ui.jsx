import { useEffect, useState } from 'react';
import { pct } from '../api';

// Confidence bar with optional threshold marker.
export function ConfBar({ value, color = '#2dd4bf', label, threshold, showPct = true }) {
  return (
    <div className="confbar">
      {(label || showPct) && (
        <div className="confbar-top">
          <span>{label}</span>
          {showPct && <span className="num">{pct(value)}</span>}
        </div>
      )}
      <div className="confbar-track">
        <div className="confbar-fill" style={{ width: `${Math.max(0, Math.min(1, value || 0)) * 100}%`, background: `linear-gradient(90deg, ${color}88, ${color})` }} />
        {threshold != null && (
          <div className="thr-marker" style={{ left: `${threshold * 100}%` }} title={`threshold ${threshold}`} />
        )}
      </div>
    </div>
  );
}

// Urgency pin meter: gradient track, white pin at urgency_p.
export function UrgencyMeter({ value }) {
  const v = Math.max(0, Math.min(1, value ?? 0));
  const label = v >= 0.75 ? 'P0 — drop everything' : v >= 0.5 ? 'high' : v >= 0.25 ? 'medium' : 'low';
  const color = v >= 0.75 ? 'var(--rose)' : v >= 0.5 ? 'var(--amber)' : v >= 0.25 ? 'var(--amber)' : 'var(--teal)';
  return (
    <div className="urg-meter">
      <div className="urg-track">
        <div className="urg-pin" style={{ left: `${v * 100}%` }} />
      </div>
      <span className="num" style={{ fontSize: 12, color, minWidth: 110, textAlign: 'right' }}>{pct(v)} · {label}</span>
    </div>
  );
}

export function Stat({ value, label, accent }) {
  return (
    <div className={`stat accent-${accent || ''}`}>
      <div className="sv num">{value}</div>
      <div className="sl">{label}</div>
    </div>
  );
}

export function Loading({ msg }) {
  return (
    <div className="loader">
      <div className="spinner" />
      <div>{msg || 'Waking the demo API…'}</div>
      <div className="note">cold starts can take a few seconds</div>
    </div>
  );
}

export function ErrorBox({ error, onRetry }) {
  return (
    <div className="errbox">
      <div style={{ fontSize: 30, marginBottom: 8 }}>🛰️</div>
      <div style={{ fontWeight: 700, color: 'var(--txt)', marginBottom: 6 }}>The demo API didn't answer</div>
      <div className="note" style={{ marginBottom: 14 }}>{String(error?.message || error)}</div>
      {onRetry && <button className="btn" onClick={onRetry}>↻ Retry</button>}
    </div>
  );
}

// Fetch-once-per-deps hook returning {data, loading, error, reload}.
export function useApi(fn, deps) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    setLoading(true); setError(null);
    fn()
      .then((d) => { if (live) { setData(d); setLoading(false); } })
      .catch((e) => { if (live) { setError(e); setLoading(false); } });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { data, loading, error, reload: () => setTick((t) => t + 1) };
}
