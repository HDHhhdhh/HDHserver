#!/usr/bin/env node

const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const sourcePath = process.env.STUDENT_JS_SOURCE
  ? path.resolve(root, process.env.STUDENT_JS_SOURCE)
  : path.join(root, "static", "js", "student.js");
const source = fs.readFileSync(sourcePath, "utf8");

function assertContract(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function extractBlockFromMarker(marker, label) {
  const start = source.indexOf(marker);
  assertContract(start !== -1, `missing ${label}`);

  const openBrace = source.indexOf("{", start);
  assertContract(openBrace !== -1, `missing opening brace for ${label}`);

  let depth = 0;
  for (let index = openBrace; index < source.length; index += 1) {
    const char = source[index];
    if (char === "{") depth += 1;
    if (char === "}") {
      depth -= 1;
      if (depth === 0) {
        return source.slice(start, index + 1);
      }
    }
  }
  throw new Error(`missing closing brace for ${label}`);
}

function extractFunction(name) {
  return extractBlockFromMarker(`function ${name}`, `function ${name}`);
}

const actionElement = extractFunction("createAssignedTestActionElement");
const sameTabHelper = extractFunction("shouldOpenAssignedTestAnswerInSameTab");
const renderStart = source.indexOf("function renderAssignedTests()");
const renderEnd = source.indexOf("async function recoverStudentSid", renderStart);
assertContract(renderStart !== -1 && renderEnd !== -1, "missing renderAssignedTests block");
const renderBlock = source.slice(renderStart, renderEnd);

for (const snippet of [
  "function assignedTestAnswerUrl(test)",
  "function isAssignedTestAnswerRestricted(test, answerUrl)",
  "function canOpenAssignedTestAnswer(answerUrl)",
  "function shouldOpenAssignedTestAnswerInSameTab()",
  "function createAssignedTestActionElement(canOpenAnswerUrl, answerUrl)",
]) {
  assertContract(source.includes(snippet), `student answer helper seam missing: ${snippet}`);
}

for (const snippet of [
  "document.createElement(canOpenAnswerUrl ? 'a' : 'button')",
  "btn.href = answerUrl;",
  "shouldOpenAssignedTestAnswerInSameTab()",
  "btn.target = '_blank';",
  "btn.rel = 'noopener noreferrer';",
]) {
  assertContract(actionElement.includes(snippet), `answer action element contract missing: ${snippet}`);
}

for (const snippet of [
  "window.matchMedia('(pointer: coarse)')",
  "nav.maxTouchPoints || nav.msMaxTouchPoints",
  "window.innerWidth",
  "<= 1024",
]) {
  assertContract(sameTabHelper.includes(snippet), `mobile/tablet same-tab detection missing: ${snippet}`);
}


for (const snippet of [
  "const answerUrl = assignedTestAnswerUrl(test);",
  "const answerRestricted = isAssignedTestAnswerRestricted(test, answerUrl);",
  "const canOpenAnswerUrl = canOpenAssignedTestAnswer(answerUrl);",
  "const btn = createAssignedTestActionElement(canOpenAnswerUrl, answerUrl);",
  "if (answerUrl) btn.dataset.answerUrl = answerUrl;",
  "if (answerRestricted) btn.dataset.answerRestricted = '1';",
  "btn.disabled = true;",
  "btn.setAttribute('aria-disabled', 'true');",
  "btn.addEventListener('click', showAcademyOnlyNotice);",
]) {
  assertContract(renderBlock.includes(snippet), `assigned-test render contract missing: ${snippet}`);
}

for (const retiredSurface of [
  'openAssignedTestSubmit',
  'openAssignedTestAnswerLink',
  '/api/submit-test',
  '/api/ocr-test-sheet',
  'testSubmitModal',
  'testAnswerPreviewModal',
]) {
  assertContract(!source.includes(retiredSurface), `retired submission surface remains: ${retiredSurface}`);
}

console.log("student answer mobile frontend contract ok");
