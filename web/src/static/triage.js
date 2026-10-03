/**
 * Faithful port of the InboxPilot decision stack for the static build:
 *   - src/inboxpilot/triage.py  -> decideFromAnswers, DEFAULT_THRESHOLDS, LABELS, CATEGORIES
 *   - web/lib/demo_store.py     -> classifyBranch, BRANCH_RULES, ACTION_COPY, morningGreeting,
 *                                  recordCorrection status math
 *   - src/inboxpilot/tuner.py   -> utility, scoreThresholds, tune (grid search w/ tie-break)
 *
 * KEEP IN SYNC with the Python sources. The port is exact for all practical
 * inputs; known simplifications vs the server build:
 *   1. Float tie-breaks in tune() could differ in pathological cases where two
 *      grid candidates tie in utility to the last ulp (Python and JS both use
 *      IEEE-754 doubles, so this only bites on exact ties of long sums).
 *   2. Session state lives in browser memory/localStorage, not per-process
 *      server memory. Corrections/tunes survive reloads here (arguably better).
 *   3. tune() `apply` ignores the frontend's redundant `thresholds` payload,
 *      exactly like the server (preview=None -> real grid search).
 */

export const DEFAULT_THRESHOLDS = {
  tau_cat: 0.85,
  tau_noise: 0.95,
  delta: 0.15,
  urgent_high: 0.75,
  urgent_low: 0.25,
  urgency_archive_max: 0.3,
};

export const CATEGORIES = [
  'needs_action', 'fyi', 'receipt', 'newsletter', 'noise',
];

export const LABELS = {
  'needs_action|true': 'InboxPilot/P0',
  'needs_action|false': 'InboxPilot/Action',
  'fyi|false': 'InboxPilot/FYI',
  'receipt|false': 'InboxPilot/Receipts',
  'newsletter|false': 'InboxPilot/Newsletters',
};

const labelFor = (cat, urgent) => LABELS[`${cat}|${urgent ? 'true' : 'false'}`];

const FLIP_NOTE_MODEL = 'mock (scripted demo)';

function topTwo(probs) {
  const ranked = Object.entries(probs).sort((a, b) => b[1] - a[1]);
  if (ranked.length === 1) return [ranked[0], [ranked[0][0], 0]];
  return [ranked[0], ranked[1]];
}

/** Port of triage.decide_from_answers. */
export function decideFromAnswers(answers, email, contacts = [], thresholds = null, model = null) {
  const t = { ...DEFAULT_THRESHOLDS };
  if (thresholds) {
    for (const [k, v] of Object.entries(thresholds)) if (k in t) t[k] = v;
  }
  const contactsList = Array.isArray(contacts) ? contacts : [...contacts];

  const urgencyP = Number(answers.urgency_p);
  const needsReplyP = Number(answers.needs_reply_p);
  const probs = {};
  for (const [k, v] of Object.entries(answers.probs)) probs[k] = Number(v);
  const [[top1, p1], [top2, p2]] = topTwo(probs);
  const conf = Number(answers.confidence);

  const senderLc = (email.from || '').toLowerCase();
  const senderKnown = contactsList.length > 0
    && contactsList.some((c) => senderLc.includes(String(c).toLowerCase()));

  const urgent = urgencyP >= t.urgent_high;
  const calm = urgencyP <= t.urgent_low;
  const ambiguous = conf < t.tau_cat || (p1 - p2) < t.delta;

  const reasons = [];
  const decision = {
    email_id: email.id,
    category: top1,
    category_confidence: conf,
    category_probs: probs,
    urgency_p: urgencyP,
    needs_reply_p: needsReplyP,
    model: model || FLIP_NOTE_MODEL,
    usage: {},
    reasons,
  };
  const digest = (suggestedAction, suggestedLabel = null) => {
    decision.action = 'digest';
    decision.label = null;
    decision.suggested = { action: suggestedAction, label: suggestedLabel };
    return decision;
  };

  // Guardrail 1: contradiction — "noise" from a known contact
  if (top1 === 'noise' && senderKnown) {
    reasons.push('Classified as noise but the sender is in your contacts — contradiction, needs your call.');
    return digest('review', null);
  }

  // Auto-archive: noise only, extreme confidence, provably calm
  if (top1 === 'noise' && conf >= t.tau_noise && urgencyP < t.urgency_archive_max) {
    reasons.push(
      `Noise at ${conf.toFixed(2)} confidence (bar ${t.tau_noise.toFixed(2)}), ` +
      `urgency ${urgencyP.toFixed(2)} — safe to archive.`,
    );
    decision.action = 'auto_archive';
    decision.label = null;
    decision.suggested = null;
    return decision;
  }

  // Auto-label: decisive category AND decisive urgency
  if (!ambiguous && (urgent || calm)) {
    if (top1 === 'needs_action') {
      const label = labelFor(top1, urgent);
      reasons.push(`${top1} at ${conf.toFixed(2)} confidence, urgency ${urgencyP.toFixed(2)} → ${label}.`);
      decision.action = 'auto_label';
      decision.label = label;
      decision.suggested = null;
      return decision;
    }
    if (calm && ['fyi', 'receipt', 'newsletter'].includes(top1)) {
      const label = labelFor(top1, false);
      reasons.push(`${top1} at ${conf.toFixed(2)} confidence, calm → ${label}.`);
      decision.action = 'auto_label';
      decision.label = label;
      decision.suggested = null;
      return decision;
    }
    if (urgent && ['fyi', 'receipt', 'newsletter'].includes(top1)) {
      reasons.push(`Marked urgent (${urgencyP.toFixed(2)}) but categorized as ${top1} — mismatch, needs your call.`);
      return digest('review', null);
    }
    // noise below the archive bar
    reasons.push(
      `Probably noise (${conf.toFixed(2)}) but below the auto-archive bar (${t.tau_noise.toFixed(2)}) — your call.`,
    );
    return digest('archive', null);
  }

  // Everything else: digest
  if (conf < t.tau_cat) {
    reasons.push(`Category confidence ${conf.toFixed(2)} below the auto-label bar (${t.tau_cat.toFixed(2)}).`);
  }
  if ((p1 - p2) < t.delta) {
    reasons.push(`Top categories too close: ${top1} (${p1.toFixed(2)}) vs ${top2} (${p2.toFixed(2)}) — ambiguous, not guessing.`);
  }
  if (!(urgent || calm)) {
    reasons.push(`Urgency uncertain (${urgencyP.toFixed(2)}).`);
  }
  const suggested = top1 === 'noise' ? 'archive' : 'label';
  const suggestedLabel = top1 === 'noise' ? null : labelFor(top1, urgent);
  return digest(suggested, suggestedLabel);
}

// ---------------------------------------------------------------------------
// Branch classification (port of demo_store.classify_branch)
// ---------------------------------------------------------------------------

export const BRANCH_RULES = {
  guardrail_contact_noise: {
    title: 'Guardrail: contact contradiction',
    quote: 'Never act on noise when the sender is in contacts (contradiction → digest).',
  },
  auto_archive: {
    title: 'Auto-archive: provably calm noise',
    quote: 'Auto-archive (noise only) ONLY at confidence ≥ τ_noise AND urgency < 0.3.',
  },
  auto_label_p0: {
    title: 'Auto-label: decisive P0',
    quote: 'Auto-label ONLY when category confidence ≥ τ_cat, urgency decisive, top-2 margin ≥ δ.',
  },
  auto_label: {
    title: 'Auto-label: decisive, calm',
    quote: 'Auto-label ONLY when category confidence ≥ τ_cat, urgency decisive, top-2 margin ≥ δ.',
  },
  guardrail_urgent_mismatch: {
    title: 'Guardrail: urgent-but-routine mismatch',
    quote: 'Marked urgent but categorized as fyi/receipt/newsletter — mismatch, needs your call.',
  },
  digest_noise_bar: {
    title: 'Digest: below the archive bar',
    quote: 'Probably noise but below the auto-archive bar (τ_noise) — your call.',
  },
  digest_low_conf: {
    title: 'Digest: below confidence bar',
    quote: 'Category confidence below the auto-label bar (τ_cat). Uncertainty is a first-class output.',
  },
  digest_close_call: {
    title: 'Digest: too close to call',
    quote: 'Top categories within δ of each other — ambiguous, not guessing.',
  },
  digest_urgent_uncertain: {
    title: 'Digest: urgency uncertain',
    quote: 'Urgency not decisive (between the low/high bands) — doubt goes to the digest.',
  },
};

export function classifyBranch(decision, email, t, contacts = []) {
  const { action } = decision;
  const top1 = decision.category;
  const conf = decision.category_confidence;
  const ranked = Object.entries(decision.category_probs).sort((a, b) => b[1] - a[1]);
  const margin = ranked[0][1] - (ranked.length > 1 ? ranked[1][1] : 0);
  const up = decision.urgency_p;
  const senderLc = (email.from || '').toLowerCase();
  const known = contacts.some((c) => senderLc.includes(String(c).toLowerCase()));

  let b;
  if (action === 'digest' && top1 === 'noise' && known) b = 'guardrail_contact_noise';
  else if (action === 'auto_archive') b = 'auto_archive';
  else if (action === 'auto_label') b = decision.label === 'InboxPilot/P0' ? 'auto_label_p0' : 'auto_label';
  else if (action === 'digest' && up >= t.urgent_high && ['fyi', 'receipt', 'newsletter'].includes(top1)) b = 'guardrail_urgent_mismatch';
  else if (action === 'digest' && top1 === 'noise') b = 'digest_noise_bar';
  else if (action === 'digest' && conf < t.tau_cat) b = 'digest_low_conf';
  else if (action === 'digest' && margin < t.delta) b = 'digest_close_call';
  else b = 'digest_urgent_uncertain';
  return [b, { id: b, ...BRANCH_RULES[b] }];
}

// ---------------------------------------------------------------------------
// Triage-all + counts + greeting (ports of demo_store.triage_all / morning_greeting)
// ---------------------------------------------------------------------------

export function triageAll(snapshot, seed, thresholds) {
  const s = snapshot.seeds[String(seed)];
  if (!s) throw new Error(`unknown seed ${seed}`);
  const t = { ...DEFAULT_THRESHOLDS, ...(thresholds || {}) };
  const emails = s.emails.map((email) => {
    const decision = decideFromAnswers(s.answers[email.id], email, snapshot.contacts, t);
    const [branch, rule] = classifyBranch(decision, email, t, snapshot.contacts);
    decision.branch = branch;
    decision.branch_rule = rule;
    return { ...email, decision };
  });
  const counts = { total: emails.length, auto_label: 0, auto_archive: 0, digest: 0 };
  for (const e of emails) counts[e.decision.action] += 1;
  return { emails, counts, thresholds: t };
}

export function morningGreeting(counts) {
  const auto = counts.auto_label + counts.auto_archive;
  return `☕ Good morning. ${counts.total} emails arrived overnight. ${auto} handled automatically. ${counts.digest} want your call.`;
}

export const ACTION_COPY = {
  auto_label: 'Auto-labeled',
  auto_archive: 'Auto-archived',
  digest: 'Sent to digest',
};

export function buildAudit(snapshot, seed, thresholds, corrections, tuneEvents) {
  const { emails } = triageAll(snapshot, seed, thresholds);
  const entries = [];
  for (const e of emails) {
    const d = e.decision;
    let summary;
    if (d.action === 'auto_label') summary = `Labeled ${d.label}`;
    else if (d.action === 'auto_archive') summary = 'Archived (noise, provably calm)';
    else summary = `Digest — suggested: ${(d.suggested || {}).action || 'review'}`;
    entries.push({
      kind: 'decision',
      email_id: e.id,
      subject: e.subject,
      summary,
      detail: d.reasons.join('; '),
      category: d.category,
      confidence: Math.round(d.category_confidence * 100) / 100,
      urgency_p: Math.round(d.urgency_p * 100) / 100,
      branch: d.branch,
      ts: e.date,
    });
  }
  const byId = Object.fromEntries(emails.map((e) => [e.id, e]));
  for (const [eid, corr] of Object.entries(corrections)) {
    entries.push({
      kind: 'correction',
      email_id: eid,
      subject: (byId[eid] && byId[eid].subject) || eid,
      summary: `You corrected → ${corr.category}` +
        (corr.urgent != null ? ` (${corr.urgent ? 'urgent' : 'not urgent'})` : ''),
      detail: 'Correction recorded in session memory; feeds the threshold tuner.',
      ts: 'session',
    });
  }
  for (const ev of tuneEvents) {
    entries.push({
      kind: 'tune',
      email_id: null,
      subject: 'Threshold tune',
      summary: `Tuned on ${ev.n} corrections`,
      detail: 'New thresholds: ' + ['tau_cat', 'tau_noise', 'delta']
        .map((k) => `${k}=${Number(ev.after[k]).toFixed(2)}`).join(', '),
      ts: 'session',
    });
  }
  // Python: entries.sort(key=ts, reverse=True), stable — equal keys keep original order.
  const withIdx = entries.map((e, i) => [e, i]);
  withIdx.sort(([a, ia], [b, ib]) => {
    const sa = String(a.ts); const sb = String(b.ts);
    if (sa !== sb) return sa < sb ? 1 : -1;
    return ia - ib;
  });
  return withIdx.map(([e]) => e);
}

// ---------------------------------------------------------------------------
// Tuner (port of src/inboxpilot/tuner.py)
// ---------------------------------------------------------------------------

export const COST_WRONG_LABEL = -10.0;
export const COST_DIGEST = -0.1;
export const REWARD_CORRECT_AUTO = 1.0;
export const GRID = {
  tau_cat: [0.70, 0.75, 0.80, 0.85, 0.90, 0.95],
  tau_noise: [0.90, 0.93, 0.95, 0.97, 0.99],
  delta: [0.05, 0.10, 0.15, 0.20, 0.25],
};
export const MIN_LABELS_FIT = 10;
export const MIN_LABELS_STABLE = 50;

export function expectedLabel(correctCategory, correctUrgent) {
  if (correctCategory === 'noise' && !correctUrgent) return 'ARCHIVE';
  if (correctUrgent == null) return null;
  return labelFor(correctCategory, Boolean(correctUrgent)) || null;
}

export function utilityOf(decision, correctCategory, correctUrgent, costWrongArchive) {
  const action = decision.action;
  if (action === 'digest') return COST_DIGEST;
  if (action === 'auto_archive') {
    if (correctCategory === 'noise' && !correctUrgent) return REWARD_CORRECT_AUTO;
    return costWrongArchive;
  }
  if (action === 'auto_label') {
    const expected = expectedLabel(correctCategory, correctUrgent);
    if (expected != null && decision.label === expected) return REWARD_CORRECT_AUTO;
    return COST_WRONG_LABEL;
  }
  return COST_DIGEST;
}

/** cases: [{email_id, sender, urgency_p, needs_reply_p, probs, confidence, correct_category, correct_urgent}] */
export function scoreThresholds(cases, thresholds, contacts, costWrongArchive) {
  let total = 0;
  for (const row of cases) {
    const email = { id: row.email_id, from: row.sender || '' };
    const answers = {
      urgency_p: row.urgency_p,
      needs_reply_p: row.needs_reply_p,
      probs: row.probs,
      confidence: row.confidence,
    };
    const decision = decideFromAnswers(answers, email, contacts, thresholds);
    total += utilityOf(decision, row.correct_category, row.correct_urgent, costWrongArchive);
  }
  return total;
}

/**
 * Port of tuner.tune(). `cases` built from the user's corrections.
 * Returns the same report dict shape the React UI reads.
 */
export function tuneThresholds(cases, current, contacts, fnCost) {
  const costWrongArchive = -Math.abs(fnCost);
  const n = cases.length;
  const report = {
    n_labels: n,
    before: { ...current },
    after: { ...current },
    utility_before: n ? scoreThresholds(cases, current, contacts, costWrongArchive) : 0,
    utility_after: 0,
    applied: false,
    provisional: false,
    notes: [],
  };
  if (n < MIN_LABELS_FIT) {
    report.notes.push(
      `Only ${n} corrections — need at least ${MIN_LABELS_FIT} before tuning. ` +
      'Thresholds unchanged (conservative defaults hold).',
    );
    return report;
  }
  const distTo = (cand) => ['tau_cat', 'tau_noise', 'delta']
    .reduce((s, k) => s + Math.abs(cand[k] - current[k]), 0);
  let best = null; let bestU = -Infinity;
  for (const tauCat of GRID.tau_cat) {
    for (const tauNoise of GRID.tau_noise) {
      for (const delta of GRID.delta) {
        const cand = { ...current, tau_cat: tauCat, tau_noise: tauNoise, delta };
        const u = scoreThresholds(cases, cand, contacts, costWrongArchive);
        if (u > bestU || (u === bestU && best !== null && distTo(cand) < distTo(best))) {
          best = cand; bestU = u;
        }
      }
    }
  }
  report.after = { ...best };
  report.utility_after = bestU;
  report.applied = true;
  if (n < MIN_LABELS_STABLE) {
    report.provisional = true;
    report.notes.push(
      `Tuned on ${n} corrections — PROVISIONAL. Research says 50–300 labels for ` +
      'stable thresholds; the tuner stays conservative until then.',
    );
  } else {
    report.notes.push(`Tuned on ${n} corrections — thresholds considered stable.`);
  }
  const improved = bestU - report.utility_before;
  report.notes.push(
    `Expected utility on your labeled history: ${report.utility_before.toFixed(1)} → ` +
    `${bestU.toFixed(1)} (Δ ${improved >= 0 ? '+' : ''}${improved.toFixed(1)}).`,
  );
  return report;
}

/** Port of demo_store.record_correction's status math. */
export function correctionStatus(n) {
  if (n < MIN_LABELS_FIT) {
    return { n_labels: n, status: 'refuse', message: `${n}/10 corrections — tuner holds conservative defaults.` };
  }
  if (n < MIN_LABELS_STABLE) {
    return { n_labels: n, status: 'provisional', message: `${n}/50 corrections — any tune would be PROVISIONAL.` };
  }
  return { n_labels: n, status: 'stable', message: `${n} corrections — stable enough to tune.` };
}
