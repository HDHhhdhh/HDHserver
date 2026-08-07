const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const demoDir = path.join(root, 'static', 'js', 'admin', 'demo');
const bootstrapPath = path.join(root, 'static', 'js', 'admin', 'demo', 'bootstrap.js');
const tutorialFiles = fs.readdirSync(demoDir)
  .filter(name => /^tutorial(?:\..+)?\.js$/.test(name))
  .sort();
const tutorial = tutorialFiles
  .map(name => fs.readFileSync(path.join(demoDir, name), 'utf8'))
  .join('\n');
const bootstrap = fs.readFileSync(bootstrapPath, 'utf8');

const forbidden = [
  ['admin-demo-spotlight', 'old full-screen target dimming layer'],
  ['admin-demo-guide-panel', 'old guide panel'],
  ['admin-demo-guide-current', 'old current-step card'],
  ['admin-demo-tutorial-highlight', 'old highlighted target class'],
  ['PAGE_MISSIONS', 'old guided task data name'],
  ['XP', 'old game score copy'],
  ['firstRun', 'old automatic first-run mode'],
  ['seenPages', 'old auto-open page state'],
  ['completedByPage', 'old completion progress state'],
  ['practicedByPage', 'old practice progress state'],
];

const required = [
  'academy.adminDemo.featureHelp.v1',
  'PAGE_FEATURES',
  'admin-demo-help-popover',
  'admin-demo-help-center',
  'handleInteraction',
  'seenByPage',
  '처음 눌렀어요',
  '.openStudentPopups',
  '.attendChk',
  '.markAbsent',
  '.markLeave',
  '.btn-doc',
  'compareCandidates',
  'ancestorDistance',
];

const failures = [];

for (const [needle, label] of forbidden) {
  if (tutorial.includes(needle)) {
    failures.push(`forbidden tutorial pattern remains: ${needle} (${label})`);
  }
}

if (tutorialFiles.length < 5) {
  failures.push(`expected modular feature-help tutorial files, found ${tutorialFiles.length}`);
}

for (const needle of required) {
  if (!tutorial.includes(needle)) {
    failures.push(`required feature-help pattern missing: ${needle}`);
  }
}

if (!/id:\s*'admin-today'[\s\S]*?priority:\s*-20/.test(tutorial)) {
  failures.push('today-list container help should have lower routing priority');
}

if (!bootstrap.includes("guideButton.textContent = '도움말';")) {
  failures.push('demo indicator should expose the help button as 도움말');
}

if (!bootstrap.includes("guideButton.dataset.adminDemoAction = 'help';")) {
  failures.push('demo indicator help button should have a stable action selector');
}

if (failures.length) {
  console.error(failures.join('\n'));
  process.exit(1);
}

console.log('demo feature-help source contract ok');
