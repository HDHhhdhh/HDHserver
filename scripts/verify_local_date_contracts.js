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
  const allTable = read('static/js/all/features/table.js');

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

  assert(allHover.includes('const sid = a.dataset.sid || a.dataset.id;'), 'student hover must use the link student id before name fallback');

  assert(allTable.includes('data-date="${todayLocalKey()}"'), 'all page rows must use a local date key');
  assert(allTable.includes('function todayLocalKey()'), 'all page table must define its local date fallback');
  assert(allTable.includes('d.getFullYear()'), 'all page table must derive the local year');
  assert(allTable.includes('d.getMonth() + 1'), 'all page table must derive the local month');
  assert(allTable.includes('d.getDate()'), 'all page table must derive the local day');
  assert(!allTable.includes("new Date().toISOString().slice(0, 10)"), 'all page table must not derive today from UTC');
  assert(allTable.includes("import('./studentRecordPopup.js')"), 'all page must lazy-load the unified student popup');
  assert(allTable.includes('window.openStudentPopupsForRow'), 'all page must launch the unified student popup after lazy loading');

  console.log('local date contracts ok');
}

main().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
