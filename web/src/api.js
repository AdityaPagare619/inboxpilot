// Static-build API shim for GitHub Pages.
//
// Same `api` interface the React views use (inbox/explain/correct/tune/audit/cost),
// served from a precomputed snapshot (public/snapshot.json) + the faithful
// decision/tuner port in ./static/triage.js. No network, no keys, no server.
//
// Session state (corrections, applied thresholds, tune events) lives in
// browser memory + localStorage — the UI says so plainly (see DEMO copy).
// Error semantics mirror the old server endpoints: unknown id -> Error with
// the 404 message, bad input -> Error with the 400 message.

import {
  DEFAULT_THRESHOLDS,
  CATEGORIES,
  triageAll,
  morningGreeting,
  buildAudit,
  tuneThresholds,
  correctionStatus,
} from './static/triage.js';

const SNAP_URL = `${import.meta.env.BASE_URL}snapshot.json`;
const LS_THRESHOLDS = 'inboxpilot:thresholds';
const LS_CORRECTIONS = 'inboxpilot:corrections';
const LS_TUNE_EVENTS = 'inboxpilot:tune_events';
const LS_HANDLED = 'inboxpilot:handled';

let _snapshot = null;
const _state = {
  corrections: {},   // email_id -> {category, urgent}  (persisted)
  tuneEvents: [],    // {n, after}                       (persisted)
  thresholds: null,  // applied overrides                (persisted)
  handled: {},       // email_id -> 'approved'|'corrected' (persisted)
};

function persistState() {
  try {
    localStorage.setItem(LS_CORRECTIONS, JSON.stringify(_state.corrections));
    localStorage.setItem(LS_TUNE_EVENTS, JSON.stringify(_state.tuneEvents));
    localStorage.setItem(LS_HANDLED, JSON.stringify(_state.handled));
  } catch { /* private mode etc. — session still works in memory */ }
}

function rehydrateState() {
  try {
    const c = JSON.parse(localStorage.getItem(LS_CORRECTIONS) || 'null');
    if (c && typeof c === 'object') _state.corrections = c;
    const te = JSON.parse(localStorage.getItem(LS_TUNE_EVENTS) || 'null');
    if (Array.isArray(te)) _state.tuneEvents = te;
    const h = JSON.parse(localStorage.getItem(LS_HANDLED) || 'null');
    if (h && typeof h === 'object') _state.handled = h;
    const saved = JSON.parse(localStorage.getItem(LS_THRESHOLDS) || 'null');
    if (saved && typeof saved === 'object') _state.thresholds = saved;
  } catch { /* ignore */ }
}

async function snapshot() {
  if (_snapshot) return _snapshot;
  const r = await fetch(SNAP_URL);
  if (!r.ok) throw new Error(`snapshot ${r.status} — rebuild with web/tools/build_snapshot.py`);
  _snapshot = await r.json();
  // restore session state from localStorage (corrections, tunes, handled, thresholds)
  rehydrateState();
  return _snapshot;
}

function getThresholds(snap) {
  const t = { ...DEFAULT_THRESHOLDS };
  if (_state.thresholds) {
    for (const k of ['tau_cat', 'tau_noise', 'delta']) {
      if (typeof _state.thresholds[k] === 'number') t[k] = _state.thresholds[k];
    }
  }
  return t;
}

function countsFor(snap, seed, thresholds) {
  return triageAll(snap, seed, thresholds).counts;
}

function labeledCases(snap, seed) {
  const s = snap.seeds[String(seed)];
  const rows = [];
  for (const [eid, corr] of Object.entries(_state.corrections)) {
    const ans = s.answers[eid];
    if (!ans) continue;
    const email = s.emails.find((e) => e.id === eid) || {};
    rows.push({
      email_id: eid,
      sender: email.from || '',
      urgency_p: ans.urgency_p,
      needs_reply_p: ans.needs_reply_p,
      probs: ans.probs,
      confidence: ans.confidence,
      correct_category: corr.category,
      correct_urgent: corr.urgent,
    });
  }
  return rows;
}

export const api = {
  inbox: async (seed) => {
    const snap = await snapshot();
    const t = getThresholds(snap);
    const { emails, counts } = triageAll(snap, seed, t);
    const handled = { ..._state.handled };
    const digestPending = emails.filter((e) => e.decision?.action === 'digest' && !handled[e.id]).length;
    return {
      mode: 'demo',
      seed,
      counts,
      thresholds: t,
      emails,
      handled,
      digest_pending: digestPending,
      tuner_status: correctionStatus(Object.keys(_state.corrections).length),
      greeting: morningGreeting({ ...counts, digest: digestPending }),
      demo_notes: snap.demo_notes,
    };
  },

  explain: async (id, seed) => {
    const snap = await snapshot();
    const s = snap.seeds[String(seed)];
    if (!s) throw new Error(`unknown seed ${seed}`);
    const email = s.emails.find((e) => e.id === id);
    if (!email) throw new Error(`unknown email id ${JSON.stringify(id)}`);
    const { emails } = triageAll(snap, seed, getThresholds(snap));
    const match = emails.find((e) => e.id === id);
    const { decision, ...emailOnly } = match;
    return {
      email: emailOnly,
      decision,
      answers: s.answers[id] || null,
      questions: snap.questions,
      thresholds: getThresholds(snap),
      contacts: snap.contacts,
      honesty: snap.honesty,
    };
  },

  correct: async (payload) => {
    const { id, category, urgent = null, seed = 0 } = payload || {};
    if (!id || !CATEGORIES.includes(category)) {
      throw new Error('bad input');
    }
    if (urgent !== null && urgent !== undefined && typeof urgent !== 'boolean') {
      throw new Error("bad input: 'urgent' must be true, false, or null");
    }
    const snap = await snapshot();
    const s = snap.seeds[String(seed)];
    if (!s || !s.answers[id]) throw new Error(`unknown email id ${JSON.stringify(id)}`);

    _state.corrections[id] = { category, urgent: urgent ?? null };
    persistState();
    const tunerStatus = correctionStatus(Object.keys(_state.corrections).length);

    const t = getThresholds(snap);
    const { emails } = triageAll(snap, seed, t);
    const match = emails.find((e) => e.id === id);
    return {
      ok: true,
      email_id: id,
      correction: { category, urgent: urgent ?? null },
      retriage: match ? match.decision : null,
      counts: countsFor(snap, seed, t),
      tuner_status: tunerStatus,
    };
  },

  tune: async (payload) => {
    const { seed = 0, fn_cost = 100, preview = null, thresholds = null, apply = true } = payload || {};
    const snap = await snapshot();
    const t = getThresholds(snap);
    const cost = Math.min(1000, Math.max(100, Number(fn_cost) || 100));
    const cases = labeledCases(snap, seed);

    // what-if: counts under custom thresholds, nothing applied (mirrors server)
    const pv = preview === true ? thresholds : preview;
    if (pv) {
      const custom = { ...t };
      for (const k of ['tau_cat', 'tau_noise', 'delta']) {
        if (typeof pv[k] === 'number') custom[k] = pv[k];
      }
      return {
        mode: 'preview',
        applied: false,
        thresholds: custom,
        counts: countsFor(snap, seed, custom),
        n_labels: cases.length,
        note: 'What-if only — thresholds not applied, no corrections consumed.',
      };
    }

    // apply: real grid search over the user's corrections (port of tuner.tune)
    const report = tuneThresholds(cases, t, snap.contacts, cost);
    if (report.applied) {
      const next = {};
      for (const k of ['tau_cat', 'tau_noise', 'delta']) next[k] = report.after[k];
      _state.thresholds = next;
      try { localStorage.setItem(LS_THRESHOLDS, JSON.stringify(next)); } catch { /* ignore */ }
      _state.tuneEvents.push({ n: report.n_labels, after: { ...report.after } });
      persistState();
    }
    const countsBefore = countsFor(snap, seed, report.before);
    const countsAfter = countsFor(snap, seed, report.after);
    return {
      ...report,
      mode: 'tune',
      fn_cost: cost,
      counts_before: countsBefore,
      counts_after: countsAfter,
    };
  },

  // Digest queue handling: approvals/corrections mark mail handled so the
  // dashboard greeting and digest counts stay live. Persisted like the rest.
  markHandled: async (id, kind) => {
    _state.handled[id] = kind === 'corrected' ? 'corrected' : 'approved';
    persistState();
    return { ok: true, email_id: id, handled: _state.handled[id] };
  },

  unhandle: async (id) => {
    delete _state.handled[id];
    persistState();
    return { ok: true, email_id: id };
  },

  audit: async (seed) => {
    const snap = await snapshot();
    const t = getThresholds(snap);
    return {
      entries: buildAudit(snap, seed, t, _state.corrections, _state.tuneEvents),
      note: 'Newest first. Corrections & tunes live in this browser (localStorage) — the demo has no server.',
      counts: countsFor(snap, seed, t),
    };
  },

  cost: async () => {
    const snap = await snapshot();
    return {
      cost: snap.cost,
      privacy: snap.privacy,
      scopes: snap.scopes,
      demo_caveats: snap.demo_caveats,
    };
  },
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
