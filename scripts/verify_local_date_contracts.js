const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

const root = path.resolve(__dirname, '..');
const read = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8');
const assert = (condition, message) => {
  if (!condition) throw new Error(message);
};

async function main() {
  const datePath = path.join(root, 'static/js/all/core/date.js');
  assert(fs.existsSync(datePath), 'all-students local date helper is missing');

  const { localDateKey } = await import(pathToFileURL(datePath).href);
  const afterMidnight = {
    getFullYear: () => 2026,
    getMonth: () => 6,
    getDate: () => 12,
    toISOString: () => '2026-07-11T15:30:00.000Z',
  };
  assert(localDateKey(afterMidnight) === '2026-07-12', 'local midnight must not resolve to the previous UTC date');

  const progressModal = read('static/js/all/features/progressModal.js');
  const allHover = read('static/js/all/features/hoverTooltip.js');
  const adminHover = read('static/js/admin/features/hoverTooltip.js');
  const allMain = read('static/js/all/main.js');

  for (const [label, source] of [
    ['all progress modal', progressModal],
    ['all hover tooltip', allHover],
  ]) {
    assert(source.includes("import { localDateKey } from '../core/date.js';"), `${label} must import localDateKey`);
    assert(source.includes('const today = localDateKey();'), `${label} must use localDateKey`);
    assert(!source.includes("new Date().toISOString().slice(0, 10)"), `${label} must not derive today from UTC`);
    assert(!source.includes("new Date().toISOString().slice(0,10)"), `${label} must not derive today from UTC`);
  }

  assert(adminHover.includes("import { getAdminDate } from '../core/adminDate.js';"), 'admin hover must import getAdminDate');
  assert(adminHover.includes('const today = getAdminDate();'), 'admin hover progress cutoff must use the selected admin date');
  assert(!adminHover.includes("new Date().toISOString().slice(0, 10)"), 'admin hover must not derive the cutoff from UTC');

  assert(allMain.includes('initHoverTooltip as initAdminHoverTooltip'), 'all page must import the active shared hover initializer');
  assert(allMain.includes('initAdminHoverTooltip();'), 'all page must initialize student hover tooltips');
  assert(allMain.includes('syncAdminTooltipState();'), 'all page must bridge its real-local-date roster state before hover initialization');
  assert(allHover.includes('const sid = a.dataset.sid || a.dataset.id;'), 'student hover must use the link student id before name fallback');

  console.log('local date contracts ok');
}

main().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
