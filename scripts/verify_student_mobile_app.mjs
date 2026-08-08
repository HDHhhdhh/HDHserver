import path from 'node:path';
import { pathToFileURL } from 'node:url';

const root = path.resolve(import.meta.dirname, '..');
const choices = ['shell'];
const modules = Object.fromEntries(choices.map((name) => [
  name,
  path.join(root, 'scripts', 'student_mobile_app_checks', `${name}.mjs`),
]));

function parseSelection(argv) {
  const onlyIndex = argv.indexOf('--only');
  if (onlyIndex < 0) return ['all'];
  const value = argv[onlyIndex + 1];
  if (!value || value.startsWith('--')) throw new Error('--only requires a suite name');
  if (value === 'all') return ['all'];
  const selected = value.split(',').map((name) => name.trim()).filter(Boolean);
  if (selected.length === 0 || selected.some((name) => !choices.includes(name))) {
    throw new Error(`unknown suite; choose ${choices.join('|')}|all`);
  }
  return selected;
}

async function importSuite(name) {
  try {
    return await import(pathToFileURL(modules[name]).href);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`missing ${name} module at ${path.relative(root, modules[name])}: ${message}`);
  }
}

try {
  const selected = parseSelection(process.argv.slice(2));
  const suites = selected[0] === 'all' ? choices : selected;
  let assertions = 0;
  for (const name of suites) {
    const module = await importSuite(name);
    const runner = module.runChecks ?? module.runShellChecks ?? module.default;
    if (typeof runner !== 'function') {
      throw new Error(`suite ${name} does not export runChecks()`);
    }
    const result = await runner();
    assertions += Number(result?.checks ?? result?.assertions ?? 0);
    console.log(`${name}: ${Number(result?.checks ?? result?.assertions ?? 0)} assertions passed`);
  }
  console.log(`student-mobile-app: ${assertions} assertions passed`);
} catch (error) {
  console.error(`student-mobile-app verification failed: ${error instanceof Error ? error.message : String(error)}`);
  process.exitCode = 1;
}
