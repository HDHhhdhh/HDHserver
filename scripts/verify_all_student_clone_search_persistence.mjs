import fs from 'node:fs';
import vm from 'node:vm';

const moduleSource = fs.readFileSync('static/js/all/features/cloneButtons.js', 'utf8')
  .replace("import { loadAll, state } from '../core/state.js';", "const loadAll = async () => {}; const state = { students: [] };")
  .replace('export function hookCloneButtons', 'function hookCloneButtons');

const context = vm.createContext({
  document: {
    body: {},
    currentSearchInput: {
      value: '김민수',
      dispatchEvent() {},
    },
    emittedEvents: [],
    getElementById(id) {
      return id === 'allStudentSearchInput' ? this.currentSearchInput : null;
    },
  },
  Event: class Event {
    constructor(type) {
      this.type = type;
    }
  },
  console,
  window: {},
});

await vm.runInContext(`${moduleSource}
  (async () => {
    // Given: a filtered roster whose table render replaces the search input.
    onClonedCallback = async () => {
      document.currentSearchInput = {
        value: '',
        dispatchEvent(event) { document.emittedEvents.push(event.type); },
      };
    };

    // When: the clone refresh completes.
    await refreshAfterClone();

    // Then: the replacement input keeps the query and reapplies the filter.
    if (document.currentSearchInput.value !== '김민수') {
      throw new Error('clone refresh cleared search query: ' + document.currentSearchInput.value);
    }
    if (!document.emittedEvents.includes('input')) {
      throw new Error('clone refresh did not reapply the student search filter');
    }
  })()
`, context, { filename: 'cloneButtons.search-persistence.test.js' });

console.log('all-student clone search persistence ok');
