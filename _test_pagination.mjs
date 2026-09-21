// Tests for the dashboard pagination core.
//
// dashboard.html is a browser-only file with no bundler, so the pure helpers
// live between explicit markers and this script evaluates that one region.
// That keeps a single source of truth instead of a copy that could drift.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const html = fs.readFileSync(path.join(HERE, 'dashboard.html'), 'utf8');

const BEGIN = '/* pagination-core:begin */';
const END = '/* pagination-core:end */';
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
  console.error('  [FAIL] pagination core markers not found in dashboard.html');
  console.error('    expected ' + BEGIN + ' ... ' + END);
  process.exit(1);
}

const region = html.slice(start + BEGIN.length, end);
const core = new Function(
  'paginate',
  '"use strict";' + region + '; return {paginate, pageWindow, filterByQuery, clampSize};',
)();

const { paginate, pageWindow, filterByQuery, clampSize } = core;
const list = (n) => Array.from({ length: n }, (_, i) => i + 1);

console.log('clampSize');
check('falls back to 20 for unknown sizes', clampSize(7) === 20, clampSize(7));
check('accepts the offered sizes', [20, 50, 100].every((s) => clampSize(s) === s));
check('tolerates junk input', clampSize(undefined) === 20 && clampSize('nope') === 20);

console.log('paginate: empty and small lists');
{
  const v = paginate([], { page: 1 }, 20);
  check('empty list still reports one page', v.pages === 1 && v.page === 1, v);
  check('empty list has no rows', v.items.length === 0);
  check('empty list shows an empty range', v.start === 0 && v.end === 0, v);
}
{
  const v = paginate(list(3), { page: 1 }, 20);
  check('short list fits on one page', v.pages === 1 && v.items.length === 3);
  check('short list range is 1-3', v.start === 1 && v.end === 3, v);
}

console.log('paginate: slicing');
{
  const v = paginate(list(63), { page: 1 }, 20);
  check('63 rows make 4 pages', v.pages === 4);
  check('page 1 holds 20 rows', v.items.length === 20);
  check('page 1 covers 1-20', v.start === 1 && v.end === 20, v);
}
{
  const v = paginate(list(63), { page: 4 }, 20);
  check('last page holds the remainder', v.items.length === 3, v.items.length);
  check('last page covers 61-63', v.start === 61 && v.end === 63, v);
}
{
  const v = paginate(list(40), { page: 2 }, 20);
  check('exact multiple leaves no empty page', v.pages === 2 && v.items.length === 20);
}

console.log('paginate: page clamping');
{
  const v = paginate(list(30), { page: 9 }, 20);
  check('page beyond the end clamps to the last page', v.page === 2, v.page);
}
{
  const v = paginate(list(30), { page: 0 }, 20);
  check('page below 1 clamps to 1', v.page === 1);
}
{
  const v = paginate(list(30), {}, 20);
  check('missing page state defaults to 1', v.page === 1);
}
{
  // Deleting rows on the last page must not strand the viewer on a blank page.
  const before = paginate(list(41), { page: 3 }, 20);
  check('starts on the last of 3 pages', before.page === 3 && before.pages === 3);
  const after = paginate(list(40), { page: before.page }, 20);
  check('shrinking to 2 pages clamps back to 2', after.page === 2, after.page);
}

console.log('paginate: absolute indices');
{
  // The API-key editor addresses rows by index in API_KEY_ROWS, so the page
  // must hand back absolute indices or edits land on the wrong key.
  const src = list(50);
  const v = paginate(src, { page: 3 }, 20);
  // list(n) holds the values 1..n, so array index 40 carries value 41. Asserting
  // both proves `index` is an array position and not a re-numbered row offset.
  check('page 3 starts at array index 40', v.items[0].index === 40, v.items[0]);
  check('page 3 starts at value 41', v.items[0].item === 41, v.items[0]);
  check('page 3 indices are contiguous', v.items.every((r, i) => r.index === 40 + i));
  check('items line up with the source array', v.items.every((r) => src[r.index] === r.item));
}

console.log('paginate: page size changes');
{
  const v = paginate(list(100), { page: 5 }, 50);
  check('100 rows at 50 per page make 2 pages', v.pages === 2);
  check('stale page 5 clamps to 2', v.page === 2, v.page);
}
{
  const v = paginate(list(100), { page: 1 }, 100);
  check('100 rows at 100 per page make 1 page', v.pages === 1 && v.items.length === 100);
}

console.log('pageWindow');
{
  check('single page shows just 1', JSON.stringify(pageWindow(1, 1)) === '[1]');
  check('short run shows every page', JSON.stringify(pageWindow(2, 5)) === '[1,2,3,4,5]');
  check('boundary at the slot limit stays flat', String(pageWindow(4, 7)).indexOf('…') < 0);
}
{
  const w = pageWindow(1, 10);
  check('first page shows no leading ellipsis', w[0] === 1 && w[1] !== '…', w);
  check('first page ends at the last page', w[w.length - 1] === 10, w);
  check('window stays within 7 slots', w.length <= 7, w.length);
}
{
  const w = pageWindow(5, 10);
  check('middle page keeps the current page', w.includes(5), w);
  check('middle page shows both ellipses', w.filter((x) => x === '…').length === 2, w);
  check('middle page anchors first and last', w[0] === 1 && w[w.length - 1] === 10, w);
  check('window stays within 7 slots', w.length <= 7, w.length);
}
{
  const w = pageWindow(10, 10);
  check('last page includes the last page number', w.includes(10), w);
  check('last page shows no trailing ellipsis', w[w.length - 1] === 10 && w[w.length - 2] !== '…', w);
}
{
  const w = pageWindow(2, 10);
  check('near-first page drops the leading ellipsis', w[1] !== '…', w);
}
{
  for (const cur of [1, 2, 3, 6, 9, 12, 15, 16]) {
    const w = pageWindow(cur, 16);
    check('cur=' + cur + ' always contains itself', w.includes(cur), w);
    check('cur=' + cur + ' stays within 7 slots', w.length <= 7, w.length);
  }
}

console.log('filterByQuery');
{
  const rows = [
    { uid: 'abc123', nickname: '主号' },
    { uid: 'def456', nickname: '备用' },
  ];
  const hay = (r) => [r.uid, r.nickname].join(' ').toLowerCase();
  check('empty query keeps everything', filterByQuery(rows, '', hay).length === 2);
  check('whitespace query keeps everything', filterByQuery(rows, '   ', hay).length === 2);
  check('matches on uid fragment', filterByQuery(rows, 'def4', hay).length === 1);
  check('matches on nickname', filterByQuery(rows, '备用', hay)[0].uid === 'def456');
  check('is case insensitive', filterByQuery(rows, 'ABC1', hay)[0].uid === 'abc123');
  check('no match returns empty', filterByQuery(rows, 'zzz', hay).length === 0);
  check('null list is safe', filterByQuery(null, 'x', hay).length === 0);
}
{
  // Search and pagination compose: the filtered list drives the page count.
  const rows = list(100).map((n) => ({ uid: 'u' + n, tag: n <= 5 ? 'hot' : 'cold' }));
  const hay = (r) => r.tag;
  const filtered = filterByQuery(rows, 'hot', hay);
  const v = paginate(filtered, { page: 1 }, 20);
  check('filtered search drives the page count', v.total === 5 && v.pages === 1, v);
}

console.log('');
console.log('pagination: ' + PASS + ' passed, ' + FAIL + ' failed');
process.exit(FAIL ? 1 : 0);
