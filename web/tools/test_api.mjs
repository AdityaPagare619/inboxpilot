/** Functional test of the static api shim (tools/test_api.mjs, run from web/).
 * Stubs fetch/localStorage; exercises every endpoint incl. error paths.
 */
import { readFileSync, writeFileSync } from 'fs';
import { pathToFileURL } from 'url';

// ---- stubs ----
const mem = {};
globalThis.localStorage = {
  getItem: (k) => (k in mem ? mem[k] : null),
  setItem: (k, v) => { mem[k] = String(v); },
  removeItem: (k) => { delete mem[k]; },
};
const SNAP = readFileSync(new URL('../public/snapshot.json', import.meta.url), 'utf8');
globalThis.fetch = async (url) => {
  if (String(url).endsWith('snapshot.json')) {
    return { ok: true, status: 200, json: async () => JSON.parse(SNAP) };
  }
  throw new Error('unexpected fetch ' + url);
};

// import.meta.env doesn't exist in node — rewrite to '/' in a temp copy
const src = readFileSync(new URL('../src/api.js', import.meta.url), 'utf8')
  .replace('import.meta.env.BASE_URL', "'/'")
  .replace("from './static/triage.js'", "from '../src/static/triage.js'");
const tmp = new URL('./_api_test_copy.mjs', import.meta.url);
writeFileSync(tmp, src);
const testMod = await import(tmp.href);
const { api } = testMod;
const { nextSeed, TUNER_DEFAULTS, getAvailableSeeds } = testMod;

let n = 0;
const ok = (cond, name) => { n++; if (!cond) { console.log('FAIL:', name); process.exitCode = 1; } };
const throws = async (fn, part, name) => {
  try { await fn(); ok(false, name + ' (no throw)'); }
  catch (e) { ok(String(e.message).includes(part), `${name} (msg: ${e.message})`); }
};

// 1. inbox seeds
for (const seed of [0, 1, 2, 3]) {
  const d = await api.inbox(seed);
  ok(d.mode === 'demo' && d.seed === seed, `inbox(${seed}) mode/seed`);
  ok(d.emails.length === 21, `inbox(${seed}) 21 emails`);
  ok(d.counts.total === 21 && d.counts.auto_label + d.counts.auto_archive + d.counts.digest === 21, `inbox(${seed}) counts add up`);
  ok(d.emails.every((e) => e.decision && e.decision.branch && e.decision.branch_rule && e.decision.branch_rule.id === e.decision.branch), `inbox(${seed}) branch integrity`);
  ok(d.greeting.startsWith('☕ Good morning.'), `inbox(${seed}) greeting`);
  ok(Array.isArray(d.demo_notes) && d.demo_notes.length > 0, `inbox(${seed}) demo_notes`);
  ok(Math.abs(d.thresholds.tau_cat - 0.85) < 1e-9, `inbox(${seed}) default thresholds`);
}

// 2. explain
{
  const d0 = await api.inbox(0);
  const id = d0.emails[0].id;
  const x = await api.explain(id, 0);
  ok(x.email.id === id && !('decision' in x.email), 'explain: email without decision');
  ok(x.decision.email_id === id && Array.isArray(x.decision.reasons), 'explain: decision');
  ok(x.questions.urgency && x.questions.category && x.questions.needs_reply, 'explain: questions');
  ok(x.contacts.length > 0 && x.honesty.length > 0, 'explain: contacts+honesty');
  await throws(() => api.explain('nope', 0), 'unknown email id', 'explain: unknown id 404-equivalent');
}

// 3. correct: validation + fuel ladder
{
  const d0 = await api.inbox(0);
  const ids = d0.emails.map((e) => e.id); // any mail id is a valid correction target (server allows all)
  ok(ids.length === 21, 'correct: 21 correctable ids');
  await throws(() => api.correct({ id: ids[0], category: 'bogus' }), 'bad input', 'correct: bad category');
  await throws(() => api.correct({ id: ids[0], category: 'fyi', urgent: 'yes' }), 'bad input', 'correct: bad urgent');
  await throws(() => api.correct({ id: 'zzz', category: 'fyi' }), 'unknown email id', 'correct: unknown id');
  let r = await api.correct({ id: ids[0], category: 'fyi', urgent: true, seed: 0 });
  ok(r.ok && r.email_id === ids[0] && r.tuner_status.n_labels === 1 && r.tuner_status.status === 'refuse', 'correct #1 refuse');
  ok(r.retriage && r.retriage.action, 'correct: retriage present');
  for (let i = 1; i < 9; i++) await api.correct({ id: ids[i], category: 'fyi', urgent: false, seed: 0 });
  r = await api.correct({ id: ids[9], category: 'noise', urgent: null, seed: 0 });
  ok(r.tuner_status.n_labels === 10 && r.tuner_status.status === 'provisional', 'correct #10 provisional');
  ok(r.tuner_status.message.includes('10/50'), 'correct #10 message');
  for (let i = 10; i < 12; i++) await api.correct({ id: ids[i], category: 'newsletter', urgent: false, seed: 0 });
}

// 4. tune: preview
{
  const b = await api.tune({ seed: 0, fn_cost: 400, preview: true, thresholds: { tau_cat: 0.85, tau_noise: 0.95, delta: 0.15 } });
  ok(b.mode === 'preview' && b.applied === false && b.counts.total === 21, 'tune preview shape');
  const a = await api.tune({ seed: 0, fn_cost: 400, preview: true, thresholds: { tau_cat: 0.70, tau_noise: 0.90, delta: 0.05 } });
  ok(a.counts.digest <= b.counts.digest && a.counts.auto_archive >= b.counts.auto_archive, 'tune preview: looser thresholds shift counts (sanity)');
  ok(b.n_labels === 12, 'tune preview sees 12 labels');
}

// 5. tune: apply with real grid search (12 corrections -> provisional apply)
{
  const r = await api.tune({ seed: 0, fn_cost: 400, apply: true, thresholds: { tau_cat: 0.8, tau_noise: 0.95, delta: 0.15 } });
  ok(r.mode === 'tune' && r.applied === true && r.provisional === true, 'tune apply: provisional apply');
  ok(typeof r.utility_before === 'number' && typeof r.utility_after === 'number', 'tune apply: utilities');
  ok(r.counts_before.total === 21 && r.counts_after.total === 21, 'tune apply: counts');
  ok(r.notes.length >= 2, 'tune apply: notes');
  // thresholds persisted + reflected in inbox
  const d = await api.inbox(0);
  ok(Math.abs(d.thresholds.tau_cat - r.after.tau_cat) < 1e-9, 'tune apply: inbox reflects new thresholds');
  ok(mem['inboxpilot:thresholds'] !== undefined, 'tune apply: localStorage persisted');
}

// 6. audit
{
  const a = await api.audit(0);
  ok(a.entries.length >= 21, 'audit: >=21 entries');
  const kinds = new Set(a.entries.map((e) => e.kind));
  ok(kinds.has('decision') && kinds.has('correction') && kinds.has('tune'), 'audit: decision+correction+tune kinds');
  ok(a.entries.every((e) => e.summary && e.ts !== undefined), 'audit: entry shape');
  // newest-first by ts (string desc, stable)
  const ts = a.entries.map((e) => String(e.ts));
  const sorted = [...ts].sort((x, y) => (x < y ? 1 : x > y ? -1 : 0));
  ok(JSON.stringify(ts) === JSON.stringify(sorted), 'audit: newest-first order');
  ok(a.note.includes('localStorage'), 'audit: honest storage note');
}

// 7. cost math adds up
{
  const c = await api.cost();
  const expected = Math.round(120 * 1500 / 1e6 * 0.042 * 365 * 100) / 100;
  ok(Math.abs(c.cost.per_year_usd - expected) < 1e-9, `cost: per_year_usd=${c.cost.per_year_usd} expected=${expected}`);
  ok(c.privacy.length >= 2 && c.scopes.read && c.scopes.write && c.demo_caveats.length > 0, 'cost: privacy+scopes+caveats');
}

// 8. seed re-run changes some decisions (flip simulation present in data)
{
  const d0 = await api.inbox(0), d1 = await api.inbox(1);
  const diff = d0.emails.filter((e) => {
    const o = d1.emails.find((x) => x.id === e.id);
    return o && (o.decision.action !== e.decision.action || Math.abs(o.decision.urgency_p - e.decision.urgency_p) > 1e-12);
  }).length;
  ok(diff > 0, `seed flip: ${diff} mails differ between seed 0 and 1`);
}

// 9. regression: seed safety (round-2 ship-blocker) + tuner reset restores FN cost
{
  const seeds = await getAvailableSeeds();
  ok(JSON.stringify(seeds) === JSON.stringify([0, 1, 2, 3]), 'seed safety: available seeds derived from snapshot');
  // wrap-around: 8 consecutive re-runs cycle forever, never past the end
  let s = 0;
  const seq = [];
  for (let i = 0; i < 8; i++) { s = nextSeed(s); seq.push(s); }
  ok(JSON.stringify(seq) === JSON.stringify([1, 2, 3, 0, 1, 2, 3, 0]), `seed safety: 8 re-runs cycle ${seq.join('→')}`);
  ok(nextSeed(99) === 0, 'seed safety: unknown seed wraps to first available');
  // unknown-seed fallback: gentle notice, never a dead app
  const d4 = await api.inbox(4);
  ok(d4.seed === 3 && typeof d4.seed_notice === 'string' && d4.seed_notice.includes('seed 4'), 'seed safety: inbox(4) falls back to seed 3 with notice');
  ok(d4.emails.length === 21, 'seed safety: inbox(4) still serves mail');
  const d99 = await api.inbox(99);
  ok(d99.seed === 3 && d99.seed_notice, 'seed safety: inbox(99) falls back with notice');
  const id = d4.emails[0].id;
  const x = await api.explain(id, 5);
  ok(x.decision && x.seed_notice, 'seed safety: explain(id, 5) falls back with notice');
  const a = await api.audit(7);
  ok(a.entries.length > 0 && a.seed_notice, 'seed safety: audit(7) falls back with notice');
  // tuner defaults: single canonical source, fn_cost matches the backend default
  ok(TUNER_DEFAULTS.fn_cost === 100, 'tuner defaults: fn_cost is the backend default 100x');
  // reset tripwire: the reset handler must restore EVERY tuner control
  const tunerSrc = readFileSync(new URL('../src/views/Tuner.jsx', import.meta.url), 'utf8');
  const resetBody = (tunerSrc.match(/const reset = \(\) => \{([\s\S]*?)\};/) || [])[1] || '';
  for (const [setter, key] of [['setTauCat', 'tau_cat'], ['setTauNoise', 'tau_noise'], ['setDelta', 'delta'], ['setFnCost', 'fn_cost']]) {
    ok(new RegExp(setter + '\\(TUNER_DEFAULTS\\.' + key + '\\)').test(resetBody), `tuner reset restores ${key}`);
  }
  const useStates = [...tunerSrc.matchAll(/useState\(TUNER_DEFAULTS\.(\w+)\)/g)].map((m) => m[1]).sort();
  ok(JSON.stringify(useStates) === JSON.stringify(['delta', 'fn_cost', 'tau_cat', 'tau_noise']), 'tuner defaults: all four controls init from TUNER_DEFAULTS');
}

console.log(process.exitCode ? 'API SHIM TESTS: FAILURES' : `API SHIM TESTS: all ${n} assertions passed`);
