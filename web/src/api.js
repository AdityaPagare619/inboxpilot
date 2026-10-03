// Thin typed client for the InboxPilot demo API (same origin, relative paths).
async function req(url, opts = {}) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), 20000);
  try {
    const r = await fetch(url, { ...opts, signal: ctrl.signal, headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) } });
    const text = await r.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch { data = { _raw: text }; }
    if (!r.ok) {
      const msg = (data && (data.error || data.message)) || `HTTP ${r.status}`;
      throw new Error(msg);
    }
    return data;
  } finally { clearTimeout(t); }
}

export const api = {
  inbox: (seed) => req(`/api/inbox?seed=${seed}`),
  explain: (id, seed) => req(`/api/explain?id=${encodeURIComponent(id)}&seed=${seed}`),
  correct: (payload) => req('/api/correct', { method: 'POST', body: JSON.stringify(payload) }),
  tune: (payload) => req('/api/tune', { method: 'POST', body: JSON.stringify(payload) }),
  audit: (seed) => req(`/api/audit?seed=${seed}`),
  cost: () => req('/api/cost'),
};

export const CATEGORY_COLORS = {
  needs_action: 'amber', fyi: 'sky', receipt: 'teal', newsletter: 'violet', noise: 'zinc',
};

export function catBadge(cat) {
  const map = CATEGORY_COLORS;
  return `b-${map[cat] || 'dim'}`;
}

export function actionBadge(action) {
  return `b-${String(action || '').replace(/-/g, '_')}`;
}

export function pct(p) {
  if (p == null || Number.isNaN(p)) return '—';
  return `${(p * 100).toFixed(1)}%`;
}
