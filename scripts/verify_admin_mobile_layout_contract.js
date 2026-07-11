const fs = require('node:fs');
const path = require('node:path');

const css = fs.readFileSync(path.resolve(__dirname, '../static/css/admin.css'), 'utf8');
const assert = (condition, message) => {
  if (!condition) throw new Error(message);
};

assert(
  css.includes('body.admin:not(.admin-simple) #todayTools .today-search'),
  'standard admin mobile search must have a dedicated wrapping rule',
);
assert(css.includes('flex-wrap: wrap;'), 'mobile search controls must wrap');
assert(
  css.includes('body.admin:not(.admin-simple) #todayTools #homeworkLeaveBtn,'),
  'mobile action buttons must share the available row',
);
assert(
  css.includes('flex: 1 1 calc(50% - 4px) !important;'),
  'mobile action buttons must shrink within the search container',
);
assert(
  /body\.admin \.announcement-board\s*\{[^}]*left:\s*50%;[^}]*width:\s*min\(360px, calc\(100vw - 32px\)\);[^}]*transform:\s*translateX\(-50%\);/s.test(css),
  'mobile announcement board must stay centered inside the viewport',
);

console.log('admin mobile layout contract ok');
