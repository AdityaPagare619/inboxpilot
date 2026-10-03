/** Zero-drift check: JS port vs Python reference (tools/reference.json).
 * Usage: node tools/check_drift.mjs   (run from web/)
 * Exits nonzero on any mismatch beyond float tolerance.
 */
import { readFileSync } from 'fs';
import {
  DEFAULT_THRESHOLDS,
  triageAll,
  correctionStatus,
  tuneThresholds,
} from '../src/static/triage.js';

const TOL = 1e-9;
let failures = 0;
const fail = (where, msg) => { failures++; console.log(`MISMATCH ${where}: ${msg}`); };
const eqNum = (a, b) => Math.abs(a - b) <= TOL;

const ref = JSON.parse(readFileSync(new URL('./reference.json', import.meta.url)));
const snap = JSON.parse(readFileSync(new URL('../public/snapshot.json', import.meta.url)));

// --- per-seed decisions ---
for (const seed of ['0', '1', '2', '3']) {
  const r = ref.seeds[seed];
  const { emails, counts } = triageAll(snap, Number(seed), DEFAULT_THRESHOLDS);
  for (const k of ['total', 'auto_label', 'auto_archive', 'digest']) {
    if (counts[k] !== r.counts[k]) fail(`seed${seed}.counts.${k}`, `py=${r.counts[k]} js=${counts[k]}`);
  }
  for (const e of emails) {
    const d = r.decisions[e.id];
    const j = e.decision;
    if (!d) { fail(`seed${seed}.${e.id}`, 'missing in reference'); continue; }
    if (d.action !== j.action) fail(`seed${seed}.${e.id}.action`, `py=${d.action} js=${j.action}`);
    if (d.label !== j.label) fail(`seed${seed}.${e.id}.label`, `py=${d.label} js=${j.label}`);
    if (d.category !== j.category) fail(`seed${seed}.${e.id}.category`, `py=${d.category} js=${j.category}`);
    if (!eqNum(d.category_confidence, j.category_confidence)) fail(`seed${seed}.${e.id}.conf`, `py=${d.category_confidence} js=${j.category_confidence}`);
    if (!eqNum(d.urgency_p, j.urgency_p)) fail(`seed${seed}.${e.id}.urgency`, `py=${d.urgency_p} js=${j.urgency_p}`);
    if (d.branch !== j.branch) fail(`seed${seed}.${e.id}.branch`, `py=${d.branch} js=${j.branch}`);
    if (d.branch_rule_id !== j.branch_rule.id) fail(`seed${seed}.${e.id}.branch_rule`, `py=${d.branch_rule_id} js=${j.branch_rule.id}`);
    const pr = JSON.stringify(d.reasons), jr = JSON.stringify(j.reasons);
    if (pr !== jr) fail(`seed${seed}.${e.id}.reasons`, `\n  py=${pr}\n  js=${jr}`);
    if (JSON.stringify(d.suggested) !== JSON.stringify(j.suggested)) fail(`seed${seed}.${e.id}.suggested`, `py=${JSON.stringify(d.suggested)} js=${JSON.stringify(j.suggested)}`);
  }
}

// --- what-if counts ---
{
  const t = { ...DEFAULT_THRESHOLDS, tau_cat: 0.75, tau_noise: 0.93, delta: 0.10 };
  const { counts } = triageAll(snap, 1, t);
  for (const k of ['total', 'auto_label', 'auto_archive', 'digest']) {
    if (counts[k] !== ref.whatif.counts[k]) fail(`whatif.${k}`, `py=${ref.whatif.counts[k]} js=${counts[k]}`);
  }
}

// --- correction status messages ---
for (const n of ['3', '12', '60']) {
  const py = ref.status[n];
  const js = correctionStatus(Number(n));
  if (JSON.stringify(py) !== JSON.stringify(js)) {
    fail(`status.${n}`, `\n  py=${JSON.stringify(py)}\n  js=${JSON.stringify(js)}`);
  }
}

// --- tune report ---
{
  // rebuild the same fake-correction cases the Python harness used
  const s = snap.seeds['1'];
  const digestIds = s.emails
    .filter((e) => triageAll(snap, 1, DEFAULT_THRESHOLDS).emails.find((x) => x.id === e.id).decision.action === 'digest')
    .slice(0, 12).map((e) => e.id);
  const cats = ['needs_action', 'fyi', 'receipt', 'newsletter', 'noise'];
  const cases = digestIds.map((eid, i) => {
    const ans = s.answers[eid];
    const email = s.emails.find((e) => e.id === eid);
    return {
      email_id: eid, sender: email.from,
      urgency_p: ans.urgency_p, needs_reply_p: ans.needs_reply_p,
      probs: ans.probs, confidence: ans.confidence,
      correct_category: cats[i % 5], correct_urgent: i % 2 === 0,
    };
  });
  const js = tuneThresholds(cases, DEFAULT_THRESHOLDS, snap.contacts, 100);
  const py = ref.tune.report;
  if (js.n_labels !== py.n_labels) fail('tune.n_labels', `py=${py.n_labels} js=${js.n_labels}`);
  if (js.applied !== py.applied) fail('tune.applied', `py=${py.applied} js=${js.applied}`);
  if (js.provisional !== py.provisional) fail('tune.provisional', `py=${py.provisional} js=${js.provisional}`);
  if (!eqNum(js.utility_before, py.utility_before)) fail('tune.utility_before', `py=${py.utility_before} js=${js.utility_before}`);
  if (!eqNum(js.utility_after, py.utility_after)) fail('tune.utility_after', `py=${py.utility_after} js=${js.utility_after}`);
  for (const k of ['tau_cat', 'tau_noise', 'delta']) {
    if (!eqNum(js.after[k], py.after[k])) fail(`tune.after.${k}`, `py=${py.after[k]} js=${js.after[k]}`);
  }
  if (JSON.stringify(js.notes) !== JSON.stringify(py.notes)) {
    fail('tune.notes', `\n  py=${JSON.stringify(py.notes)}\n  js=${JSON.stringify(js.notes)}`);
  }
}

if (failures === 0) console.log('DRIFT CHECK PASSED — JS port matches Python exactly (4 seeds, what-if, status, tune).');
else console.log(`${failures} drift failures.`);
process.exit(failures ? 1 : 0);
