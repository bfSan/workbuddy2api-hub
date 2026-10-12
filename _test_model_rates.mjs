// Tests for the dashboard model rate column (data-driven credits + promo badges).
//
// dashboard.html is a browser-only file with no bundler, so the pure helpers
// live between explicit markers and this script evaluates that one region.
// That keeps a single source of truth instead of a copy that could drift.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const html = fs.readFileSync(path.join(HERE, 'dashboard.html'), 'utf8');

const BEGIN = '/* model-rates-core:begin */';
const END = '/* model-rates-core:end */';
const start = html.indexOf(BEGIN);
const end = html.indexOf(END);

let PASS = 0;
let FAIL = 0;

function check(label, cond, extra) {
  if (cond) {
    PASS += 1;
    console.log('  [PASS] ' + label);
  } else {
    FAIL += 1;
    console.log('  [FAIL] ' + label + (extra !== undefined ? '  ' + JSON.stringify(extra) : ''));
  }
}

if (start < 0 || end < 0 || end < start) {
  console.error('  [FAIL] model-rates core markers not found in dashboard.html');
  console.error('    expected ' + BEGIN + ' ... ' + END);
  process.exit(1);
}

const region = html.slice(start + BEGIN.length, end);
// esc() is a dashboard global; inject a faithful stub so the region stays pure.
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
));
const core = new Function('esc', '"use strict";' + region + '; return {modelCreditBadge};')(esc);

const { modelCreditBadge } = core;

console.log('upstream credits win over hard-coded promos');
// Regression: deepseek-v4.1-flash used to be pinned at 0.03x ("独家优惠") in the
// dashboard while upstream had already moved to 0.11x.
const ds = modelCreditBadge({ id: 'deepseek-v4.1-flash', credits: 'x0.11 credits' }, 'cn');
check('shows the live upstream multiplier', ds.indexOf('0.11x') >= 0, ds);
check('drops the stale hard-coded promo', ds.indexOf('独家优惠') < 0, ds);
check('normalizes "x0.11 credits" to "0.11x"', ds.indexOf('>0.11x<') >= 0, ds);

console.log('free detection comes from the credits value');
const hy3 = modelCreditBadge({ id: 'hy3', credits: 'x0.00 credits' }, 'cn');
check('zero credits render as 限时免费 0.00x', hy3.indexOf('限时免费 0.00x') >= 0, hy3);
check('numeric zero is also free', modelCreditBadge({ id: 'x', credits: 0 }, 'cn').indexOf('限时免费') >= 0);
check('non-zero credits are not free', modelCreditBadge({ id: 'x', credits: 'x0.29' }, 'cn').indexOf('限时免费') < 0);

console.log('promo badges come from upstream badge tags');
const glm = modelCreditBadge(
  { id: 'glm-5.2', credits: 'x0.79 credits', badges: [{ text: '夜间折扣', color: '#1E90FF' }] }, 'cn');
check('upstream multiplier still shown', glm.indexOf('0.79x') >= 0, glm);
check('badge tag rendered as promo', glm.indexOf('夜间折扣') >= 0, glm);
check('badge uses the upstream color', glm.indexOf('#1E90FF') >= 0, glm);
check('badge text is escaped', modelCreditBadge(
  { id: 'x', credits: 'x1', badges: [{ text: '<script>', color: '#FF0000' }] }, 'cn'
).indexOf('<script>') < 0);

console.log('a free promo badge is not duplicated next to the green one');
const hy3Tagged = modelCreditBadge(
  { id: 'hy3', credits: 'x0.00', badges: [{ text: '限时免费', color: '#FF0000' }] }, 'cn');
check('限时免费 appears exactly once', (hy3Tagged.match(/限时免费/g) || []).length === 1, hy3Tagged);
const hy4p = modelCreditBadge(
  { id: 'hy4-preview', credits: 'x0.29', badges: [{ text: '夜间免费', color: '#FF0000' }] }, 'cn');
check('non-free promo badge is kept', hy4p.indexOf('夜间免费') >= 0 && hy4p.indexOf('0.29x') >= 0, hy4p);

console.log('no upstream data falls back to the built-in promos');
check('hy4-preview-f stays 限时免费 without data',
  modelCreditBadge({ id: 'hy4-preview-f' }, 'cn').indexOf('限时免费 0.00x') >= 0);
check('hy3 stays 限时免费 without data',
  modelCreditBadge({ id: 'hy3' }, 'cn').indexOf('限时免费 0.00x') >= 0);
check('deepseek intl stays 限时免费 without data',
  modelCreditBadge({ id: 'deepseek-v4.1-flash' }, 'intl').indexOf('限时免费 0.00x') >= 0);
check('deepseek cn keeps 独家优惠 fallback without data',
  modelCreditBadge({ id: 'deepseek-v4.1-flash' }, 'cn').indexOf('独家优惠 0.03x') >= 0);
check('glm-5.2 keeps the night-discount fallback without data',
  modelCreditBadge({ id: 'glm-5.2' }, 'cn').indexOf('(夜间0.5x)') >= 0);
check('unknown model without data renders a dash',
  modelCreditBadge({ id: 'whatever' }, 'cn') === '-');
check('empty model object renders a dash', modelCreditBadge(null, 'cn') === '-');

console.log();
console.log(`PASS=${PASS} FAIL=${FAIL}`);
process.exit(FAIL ? 1 : 0);
