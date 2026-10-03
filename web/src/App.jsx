import { useCallback, useEffect, useState } from 'react';
import './styles.css';
import Dashboard from './views/Dashboard';
import Digest from './views/Digest';
import Explorer from './views/Explorer';
import Tuner from './views/Tuner';
import Audit from './views/Audit';
import CostPrivacy from './views/CostPrivacy';

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

  const notify = useCallback((t) => {
    const id = Math.random().toString(36).slice(2);
    const toast = { id, type: t.type || 'info', msg: t.msg };
    setToasts((ts) => [...ts.slice(-2), toast]);
    setTimeout(() => setToasts((ts) => ts.filter((x) => x.id !== id)), 5200);
  }, []);

  const bumpSeed = useCallback(() => setSeed((s) => s + 1), []);

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
        <div className="seed-chip" title="Jev's 1–2% non-determinism is simulated per seed">
          <span className="seed-dot" />
          seed <b>{seed}</b>
        </div>
      </header>

      <nav className="nav">
        {VIEWS.map((v) => (
          <button key={v.id} className={`nav-btn ${view === v.id ? 'active' : ''}`} onClick={() => { setView(v.id); window.scrollTo({ top: 0 }); }}>
            <span className="k">{v.icon}</span>{v.label}
          </button>
        ))}
      </nav>

      <main className="wrap">
        {view === 'triage' && <Dashboard seed={seed} onRerun={bumpSeed} notify={notify} />}
        {view === 'digest' && <Digest seed={seed} notify={notify} />}
        {view === 'explorer' && <Explorer seed={seed} />}
        {view === 'tuner' && <Tuner seed={seed} notify={notify} />}
        {view === 'audit' && <Audit seed={seed} />}
        {view === 'cost' && <CostPrivacy />}
      </main>

      <div className="toasts">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.type}`}>
            <span>{t.type === 'ok' ? '✅' : t.type === 'warn' ? '⚠️' : t.type === 'bad' ? '❌' : 'ℹ️'}</span>
            <span>{t.msg}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
