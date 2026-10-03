import { Component, useCallback, useEffect, useState } from 'react';
import './styles.css';
import { api, nextSeed } from './api';
import Dashboard from './views/Dashboard';
import Digest from './views/Digest';
import Explorer from './views/Explorer';
import Tuner from './views/Tuner';
import Audit from './views/Audit';
import CostPrivacy from './views/CostPrivacy';

// A crashed view must never nuke the whole app (React unmounts the entire
// tree on an uncaught render error). This boundary contains the blast radius
// to the view router and offers a way back.
class ViewErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error) {
    return { error };
  }
  componentDidCatch(error) {
    // eslint-disable-next-line no-console
    console.error('InboxPilot view crashed:', error);
  }
  render() {
    if (this.state.error) {
      return (
        <div className="errbox" style={{ marginTop: 24 }}>
          <div style={{ fontSize: 30, marginBottom: 8 }}>🧯</div>
          <div style={{ fontWeight: 700, color: 'var(--txt)', marginBottom: 6 }}>This view hit a render bug</div>
          <div className="note" style={{ marginBottom: 14 }}>
            The app itself is fine — the crash was contained here. {String(this.state.error?.message || this.state.error)}
          </div>
          <div className="btn-row" style={{ justifyContent: 'center' }}>
            <button className="btn btn-primary btn-sm" onClick={() => { this.setState({ error: null }); this.props.onReset?.(); }}>↩ Back to Triage</button>
            <button className="btn btn-ghost btn-sm" onClick={() => window.location.reload()}>↻ Reload app</button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

const VIEWS = [
  { id: 'triage', label: 'Triage', icon: '📊' },
  { id: 'digest', label: 'Digest', icon: '☀️' },
  { id: 'explorer', label: 'Confidence', icon: '🔍' },
  { id: 'tuner', label: 'Tuner', icon: '🎛️' },
  { id: 'audit', label: 'Audit', icon: '📜' },
  { id: 'cost', label: 'Cost & Privacy', icon: '💸' },
];

export default function App() {
  const [view, setView] = useState('triage');
  const [seed, setSeed] = useState(() => {
    const s = parseInt(localStorage.getItem('inboxpilot:seed') || '0', 10);
    return Number.isFinite(s) ? s : 0;
  });
  const [toasts, setToasts] = useState([]);

  useEffect(() => { localStorage.setItem('inboxpilot:seed', String(seed)); }, [seed]);

  // Recovery path: a persisted seed from a bricked/older session may not exist
  // in the snapshot — reset to 0 instead of bricking every view on load.
  useEffect(() => {
    let cancelled = false;
    api.getAvailableSeeds().then((seeds) => {
      if (!cancelled) setSeed((s) => (seeds.includes(s) ? s : 0));
    }).catch(() => {});
    return () => { cancelled = true; };
  }, []);

  const notify = useCallback((t) => {
    const id = Math.random().toString(36).slice(2);
    const toast = { id, type: t.type || 'info', msg: t.msg };
    setToasts((ts) => [...ts.slice(-2), toast]);
    setTimeout(() => setToasts((ts) => ts.filter((x) => x.id !== id)), 5200);
  }, []);

  // Re-run cycles through the snapshot's available seeds — never past the end.
  const bumpSeed = useCallback(() => setSeed((s) => nextSeed(s)), []);

  const resetDemo = useCallback(() => {
    setSeed(0);
    notify({ type: 'info', msg: '↺ Demo reset — back to seed 0.' });
  }, [notify]);

  return (
    <div>
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">✉️</div>
          <div>
            <div className="brand-name">InboxPilot</div>
            <div className="brand-sub">mission control for machine decisions</div>
          </div>
        </div>
        <span className="demo-badge">DEMO</span>
        <button
          className="seed-chip"
          onClick={resetDemo}
          title="Reset the demo to seed 0"
          aria-label="Reset demo to seed 0"
        >
          <span className="seed-dot" />
          seed <b>{seed}</b><span className="seed-reset-hint">↺</span>
        </button>
      </header>

      <nav className="nav">
        {VIEWS.map((v) => (
          <button key={v.id} className={`nav-btn ${view === v.id ? 'active' : ''}`} onClick={() => { setView(v.id); window.scrollTo({ top: 0 }); }}>
            <span className="k">{v.icon}</span>{v.label}
          </button>
        ))}
      </nav>

      <main className="wrap">
        <ViewErrorBoundary key={view} onReset={() => setView('triage')}>
          {view === 'triage' && <Dashboard seed={seed} onRerun={bumpSeed} notify={notify} />}
          {view === 'digest' && <Digest seed={seed} notify={notify} />}
          {view === 'explorer' && <Explorer seed={seed} />}
          {view === 'tuner' && <Tuner seed={seed} notify={notify} />}
          {view === 'audit' && <Audit seed={seed} />}
          {view === 'cost' && <CostPrivacy />}
        </ViewErrorBoundary>
      </main>

      <div className="toasts">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.type}`}>
            <span>{t.msg}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
