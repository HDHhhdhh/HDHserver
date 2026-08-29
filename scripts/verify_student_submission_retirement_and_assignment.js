#!/usr/bin/env node

const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const studentPath = process.env.STUDENT_JS_SOURCE
  ? path.resolve(root, process.env.STUDENT_JS_SOURCE)
  : path.join(root, 'static', 'js', 'student.js');
const studentSource = fs.readFileSync(studentPath, 'utf8');
const presentationSource = fs.readFileSync(path.join(root, 'static', 'js', 'student', 'testPresentation.js'), 'utf8');
const adminSource = fs.readFileSync(path.join(root, 'static', 'js', 'admin', 'features', 'testModal.js'), 'utf8');

function assertContract(condition, message) {
  if (!condition) throw new Error(message);
}

for (const retiredMarker of [
  'availableRoundsForType',
  'renderRoundOptions',
  'findSiblingTestByRound',
  'openAssignedTestSubmit',
  'openAssignedTestAnswerLink',
  '/api/submit-test',
  '/api/ocr-test-sheet',
  'testSubmitModal',
  'testAnswerPreviewModal',
]) {
  assertContract(!(studentSource + presentationSource).includes(retiredMarker), `retired student submission marker remains: ${retiredMarker}`);
}

for (const readOnlyMarker of [
  'function renderAssignedTests()',
  'const view = assignedTestViewModel(test, { academyAccessAllowed });',
  'const btn = createAssignedTestActionElement(view.canOpenAnswerUrl, view.answerUrl);',
  "btn.disabled = true;",
  "btn.setAttribute('aria-disabled', 'true');",
]) {
  assertContract(studentSource.includes(readOnlyMarker), `read-only assigned-test contract missing: ${readOnlyMarker}`);
}

for (const assignmentMarker of [
  'function roundOptionsFor(',
  'function unitTestsForRound(',
  'normalizeRound(test.round',
  'data-round=',
  'assignedTests',
  '/api/progress/patch',
]) {
  assertContract(adminSource.includes(assignmentMarker), `admin test-assignment contract missing: ${assignmentMarker}`);
}

console.log('student submission retired; admin test assignment round contract preserved');
