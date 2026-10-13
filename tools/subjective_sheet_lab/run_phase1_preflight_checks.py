# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\run_phase1_preflight_checks.py

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Final, Literal, TypeAlias

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
CheckStatus: TypeAlias = Literal["pass", "fail", "skipped", "warning"]

ROOT: Final = Path(__file__).resolve().parents[2]
LAB: Final = Path(__file__).resolve().parent
OUT_DIR: Final = Path(r"C:\server-ocr\gemini_outputs")
REPORT_JSON: Final = OUT_DIR / "phase1_preflight_report.json"
REPORT_MD: Final = OUT_DIR / "phase1_preflight_report.md"
TIMEOUT_SECONDS: Final = 120
BROWSER_TIMEOUT_SECONDS: Final = 30
PHASE1_ALLOWED_TEST_ID: Final = "t_unit_daesu_01_lv3_r1"
PHASE1_BLOCKED_TEST_ID: Final = "phase1_non_allowed_mock"
PHASE1_INELIGIBLE_MESSAGE: Final = "이 시험은 아직 사진 인식 테스트 대상이 아닙니다."
CHROME_CANDIDATES: Final = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
)
SECRET_PATTERN: Final = re.compile(r"AIza[0-9A-Za-z_\-]{10,}|x-goog-api-key\s*[:=]\s*\S+|sk-[A-Za-z0-9]{20,}")
SUBMIT_CALL_PATTERN: Final = re.compile(r"fetch\s*\([^)]*/api/submit-test|curl\b[^\n]*/api/submit-test|Invoke-RestMethod[^\n]*/api/submit-test", re.IGNORECASE)
GEMINI_CALL_PATTERN: Final = re.compile(r"google-genai|generativeai|generate_content|generateContent|x-goog-api-key", re.IGNORECASE)
FORBIDDEN_STUDENT_KEYS: Final = (
    "expected",
    "canonical_answer",
    "accepted_answers",
    "correct",
    "incorrect",
    "score",
    "wrong",
    "pct",
)


@dataclass(frozen=True, slots=True)
class CheckSpec:
    name: str
    command: tuple[str, ...]
    required_path: Path


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    status: CheckStatus
    command: str
    exit_code: int | None
    duration_seconds: float
    reason: str
    stdout_tail: str = ""
    stderr_tail: str = ""


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results = [run_check(spec) for spec in check_specs()]
    results.extend(run_phase1_eligibility_browser_checks())
    results.extend(run_safety_scans())
    production_default_no_go = read_production_default_status()
    failed = tuple(item for item in results if item.status == "fail")
    warnings = tuple(item for item in results if item.status == "warning")
    skipped = tuple(item for item in results if item.status == "skipped")
    ready_for_manual_qa = not failed and production_default_no_go
    payload = build_report_payload(results, production_default_no_go, ready_for_manual_qa)
    REPORT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(build_markdown(results, production_default_no_go, ready_for_manual_qa), encoding="utf-8")
    print(json.dumps({
        "ok": not failed,
        "total_checks": len(results),
        "failed_checks": len(failed),
        "warning_checks": len(warnings),
        "skipped_checks": len(skipped),
        "ready_for_manual_qa": ready_for_manual_qa,
        "production_default_remains_no_go": production_default_no_go,
        "report_json": str(REPORT_JSON),
        "report_md": str(REPORT_MD),
    }, ensure_ascii=False, indent=2))
    return 1 if failed else 0


def check_specs() -> tuple[CheckSpec, ...]:
    py = sys.executable
    return (
        CheckSpec("student_js_syntax", ("node", "--check", "static/js/student.js"), ROOT / "static/js/student.js"),
        CheckSpec("ocr_review_contract", (py, "tools/subjective_sheet_lab/validate_ocr_review_contract.py"), LAB / "validate_ocr_review_contract.py"),
        CheckSpec("ocr_review_contract_negative", (py, "tools/subjective_sheet_lab/verify_ocr_review_contract_negative.py"), LAB / "verify_ocr_review_contract_negative.py"),
        CheckSpec("final_review_payload_bridge", (py, "tools/subjective_sheet_lab/verify_final_review_payload_bridge.py"), LAB / "verify_final_review_payload_bridge.py"),
        CheckSpec("ocr_regression_suite_quick", (py, "tools/subjective_sheet_lab/run_ocr_regression_suite.py", "--quick", "--skip-phase1-preflight"), LAB / "run_ocr_regression_suite.py"),
        CheckSpec("ocr_qa_docs_exist", (py, "tools/subjective_sheet_lab/verify_ocr_qa_docs_exist.py"), LAB / "verify_ocr_qa_docs_exist.py"),
        CheckSpec("ocr_artifact_stability_snapshot", (py, "tools/subjective_sheet_lab/verify_ocr_artifact_stability_snapshot.py"), LAB / "verify_ocr_artifact_stability_snapshot.py"),
        CheckSpec("ocr_cached_regression_suite", (py, "tools/subjective_sheet_lab/verify_cached_ocr_regression_suite.py"), LAB / "verify_cached_ocr_regression_suite.py"),
        CheckSpec("ocr_postprocessing_gate_matrix", (py, "tools/subjective_sheet_lab/verify_ocr_postprocessing_gate_matrix.py"), LAB / "verify_ocr_postprocessing_gate_matrix.py"),
        CheckSpec("ocr_catalog_allowlist_consistency", (py, "tools/subjective_sheet_lab/verify_ocr_catalog_allowlist_consistency.py"), LAB / "verify_ocr_catalog_allowlist_consistency.py"),
        CheckSpec("ocr_answer_mode_coverage", (py, "tools/subjective_sheet_lab/verify_ocr_answer_mode_coverage.py"), LAB / "verify_ocr_answer_mode_coverage.py"),
        CheckSpec("ocr_crop_quality_thresholds", (py, "tools/subjective_sheet_lab/verify_ocr_crop_quality_thresholds.py"), LAB / "verify_ocr_crop_quality_thresholds.py"),
        CheckSpec("ocr_cached_replay_stability", (py, "tools/subjective_sheet_lab/verify_ocr_cached_replay_stability.py"), LAB / "verify_ocr_cached_replay_stability.py"),
        CheckSpec("ocr_local_candidate_tools", (py, "tools/subjective_sheet_lab/verify_ocr_local_candidate_tools.py"), LAB / "verify_ocr_local_candidate_tools.py"),
        CheckSpec("ocr_live_authorization_templates", (py, "tools/subjective_sheet_lab/verify_ocr_live_authorization_templates.py"), LAB / "verify_ocr_live_authorization_templates.py"),
        CheckSpec("admin_tests_record_detail_leak_extended", (py, "tools/subjective_sheet_lab/verify_admin_tests_record_detail_leak_extended.py"), LAB / "verify_admin_tests_record_detail_leak_extended.py"),
        CheckSpec("student_ocr_review_prefill_policy", ("node", "tools/subjective_sheet_lab/verify_student_ocr_review_prefill_policy.js"), LAB / "verify_student_ocr_review_prefill_policy.js"),
        CheckSpec("student_training_pack_round_filter", ("node", "scripts/verify_student_training_pack_round_filter.js"), ROOT / "scripts/verify_student_training_pack_round_filter.js"),
        CheckSpec("submit_test_assignment_round_matching", (py, "scripts/verify_submit_test_assignment_round_matching.py"), ROOT / "scripts/verify_submit_test_assignment_round_matching.py"),
        CheckSpec("gangyuhyun849_live_cache_replay_ui", ("node", "tools/subjective_sheet_lab/verify_student_ocr_live_cache_replay_ui.js"), LAB / "verify_student_ocr_live_cache_replay_ui.js"),
        CheckSpec("gangyuhyun849_live_review_payload_cache_replay_ui", ("node", "tools/subjective_sheet_lab/verify_student_ocr_live_review_payload_cache_replay.js"), LAB / "verify_student_ocr_live_review_payload_cache_replay.js"),
        CheckSpec("person_03_phase2e_one_call_dry_run", (py, "tools/subjective_sheet_lab/run_person_03_phase2e_one_call_dry_run.py"), LAB / "run_person_03_phase2e_one_call_dry_run.py"),
        CheckSpec("person_03_phase2e_provider_free_route_dry_run", (py, "tools/subjective_sheet_lab/run_person_03_phase2e_one_call_dry_run.py", "--route-dry-run"), LAB / "run_person_03_phase2e_one_call_dry_run.py"),
        CheckSpec("subjective_review_pipeline_dry_run", (py, "tools/subjective_sheet_lab/subjective_review_pipeline_dry_run.py"), LAB / "subjective_review_pipeline_dry_run.py"),
        CheckSpec("evaluate_ocr_policy", (py, "tools/subjective_sheet_lab/verify_evaluate_ocr_policy.py"), LAB / "verify_evaluate_ocr_policy.py"),
        CheckSpec("review_ui_mock_policy", (py, "tools/subjective_sheet_lab/verify_review_ui_mock_policy.py"), LAB / "verify_review_ui_mock_policy.py"),
        CheckSpec("ocr_benchmark_gate_generate", (py, "tools/subjective_sheet_lab/ocr_benchmark_gate.py"), LAB / "ocr_benchmark_gate.py"),
        CheckSpec("ocr_benchmark_gate", (py, "tools/subjective_sheet_lab/verify_ocr_benchmark_gate.py"), LAB / "verify_ocr_benchmark_gate.py"),
    )


def run_check(spec: CheckSpec) -> CheckResult:
    if not spec.required_path.exists():
        return CheckResult(spec.name, "skipped", command_text(spec.command), None, 0.0, f"missing {spec.required_path}")
    started = time.perf_counter()
    try:
        completed = subprocess.run(spec.command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT_SECONDS, check=False)
    except FileNotFoundError as exc:
        return CheckResult(spec.name, "fail", command_text(spec.command), None, 0.0, f"command not found: {exc.filename}")
    except subprocess.TimeoutExpired as exc:
        return CheckResult(spec.name, "fail", command_text(spec.command), None, TIMEOUT_SECONDS, f"timeout after {TIMEOUT_SECONDS}s", tail(exc.stdout), tail(exc.stderr))
    except OSError as exc:
        return CheckResult(spec.name, "fail", command_text(spec.command), None, 0.0, f"os error: {exc}")
    duration = round(time.perf_counter() - started, 3)
    status: CheckStatus = "pass" if completed.returncode == 0 else "fail"
    reason = "ok" if status == "pass" else f"exit {completed.returncode}"
    return CheckResult(spec.name, status, command_text(spec.command), completed.returncode, duration, reason, tail(completed.stdout), tail(completed.stderr))


def run_phase1_eligibility_browser_checks() -> list[CheckResult]:
    chrome = find_chrome()
    if chrome is None:
        return [CheckResult(
            "phase1_eligibility_browser_checks",
            "fail",
            "chrome --headless dump-dom",
            None,
            0.0,
            "Chrome executable not found",
        )]

    specs = (
        ("phase1_flag_off_ocr_absent", "flag_off", PHASE1_ALLOWED_TEST_ID, "?sid=990"),
        ("phase1_flag_on_allowed_visible", "allowed", PHASE1_ALLOWED_TEST_ID, "?sid=990&ocr=1"),
        ("phase1_flag_on_blocked_hidden", "blocked", PHASE1_BLOCKED_TEST_ID, "?sid=990&ocr=1"),
        ("phase1_selection_change_updates", "selection_change", PHASE1_ALLOWED_TEST_ID, "?sid=990&ocr=1"),
    )
    return [
        run_phase1_eligibility_browser_check(chrome, name, mode, test_id, query)
        for name, mode, test_id, query in specs
    ]


def run_phase1_eligibility_browser_check(
    chrome: Path,
    name: str,
    mode: str,
    test_id: str,
    query: str,
) -> CheckResult:
    harness = OUT_DIR / f"{name}.html"
    pre_id = f"{name}_result"
    harness.write_text(build_phase1_eligibility_harness(mode, pre_id, test_id), encoding="utf-8")
    command = (
        str(chrome),
        "--headless=new",
        "--disable-gpu",
        "--disable-background-networking",
        "--allow-file-access-from-files",
        "--no-sandbox",
        "--virtual-time-budget=12000",
        "--dump-dom",
        f"{harness.as_uri()}{query}",
    )
    started = time.perf_counter()
    try:
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=BROWSER_TIMEOUT_SECONDS, check=False)
    except subprocess.TimeoutExpired as exc:
        return CheckResult(name, "fail", command_text(command), None, BROWSER_TIMEOUT_SECONDS, "Chrome timeout", tail(exc.stdout), tail(exc.stderr))
    except OSError as exc:
        return CheckResult(name, "fail", command_text(command), None, 0.0, f"Chrome error: {exc}")

    duration = round(time.perf_counter() - started, 3)
    if completed.returncode != 0:
        return CheckResult(name, "fail", command_text(command), completed.returncode, duration, f"Chrome exit {completed.returncode}", tail(completed.stdout), tail(completed.stderr))

    payload = extract_pre_json(completed.stdout, pre_id)
    if payload is None:
        return CheckResult(name, "fail", command_text(command), completed.returncode, duration, f"missing #{pre_id}", tail(completed.stdout), tail(completed.stderr))

    status: CheckStatus = "pass" if payload.get("ok") is True else "fail"
    reason = "ok" if status == "pass" else json.dumps(payload, ensure_ascii=False, sort_keys=True)[:1000]
    return CheckResult(
        name,
        status,
        command_text(command),
        completed.returncode,
        duration,
        reason,
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        tail(completed.stderr),
    )


def find_chrome() -> Path | None:
    for path in CHROME_CANDIDATES:
        if path.is_file():
            return path
    found = shutil.which("chrome") or shutil.which("chrome.exe")
    return Path(found) if found else None


def build_phase1_eligibility_harness(mode: str, pre_id: str, test_id: str) -> str:
    html = (ROOT / "static/student.html").read_text(encoding="utf-8-sig")
    html = re.sub(r"\s*<script src=\"https://file\.kollus\.com/vgcontroller/.*?</script>\s*", "\n", html, flags=re.DOTALL)
    html = html.replace('href="/css/style.css"', f'href="{(ROOT / "static/css/style.css").as_uri()}"')
    html = re.sub(r'href="/css/student\.css[^"]*"', f'href="{(ROOT / "static/css/student.css").as_uri()}"', html)
    student_js = ROOT / "static/js/student.js"
    student_js_copy = OUT_DIR / f"phase1_student_{student_js.stat().st_mtime_ns}.js"
    student_js_copy.write_text(student_js.read_text(encoding="utf-8-sig"), encoding="utf-8")
    html = re.sub(r"\s*<script defer src=\"/js/student\.js[^\"]*\"></script>", lambda _: "\n" + build_phase1_fetch_stub(test_id, mode), html)
    student_runtime_script = f"  <script src=\"{student_js_copy.as_uri()}\"></script>"
    return html.replace("</body>", f"{student_runtime_script}\n{build_phase1_assertion_script(mode, pre_id, test_id)}\n</body>")


def build_phase1_fetch_stub(test_id: str, mode: str = "") -> str:
    test_ids = [PHASE1_ALLOWED_TEST_ID, PHASE1_BLOCKED_TEST_ID] if mode == "selection_change" else [test_id]
    assigned_tests = [phase1_test_fixture(item_id) for item_id in test_ids]
    bootstrap = {
        "student": {"id": "990", "name": "김가현", "day1": "일"},
        "students": [{"id": "990", "name": "김가현", "day1": "일"}],
        "videos": [],
        "updates": {},
        "materials": {},
        "assigns": {},
        "absent": {},
        "logs": {},
        "academyAccessAllowed": True,
        "assignedTests": assigned_tests,
        "homeworkBooks": [],
    }
    tests_config = {
        "categories": {
            "UNIT": {
                "label": "단원평가",
                "tests": [
                    {
                        "id": item["id"],
                        "name": item["name"],
                        "problems": 19 if item["id"] == PHASE1_BLOCKED_TEST_ID else 20,
                        "curriculum": "",
                        "difficulty": "",
                        "round": "1",
                    }
                    for item in assigned_tests
                ],
            },
        },
    }
    route_answers = ["1", "-3", "x=n", "0.5", "2", "ㄴ,ㄹ", "5", "2x+1", "4", "6", "256", "a/2", "5", "1", "-1<x<5", "y=n", "2", "139/2", "x±2=4", "26sqrt(21)"]
    route_candidates = {
        3: ["x=2", "3", "x=n", "x=?"],
        10: ["0", "6", "?"],
        18: ["129/2", "139/2", "?"],
        19: ["x+2=4", "3", "x±2=4", "x-2=4"],
    }
    route_items: list[dict[str, JsonValue]] = []
    for index, answer in enumerate(route_answers, start=1):
        candidates = route_candidates.get(index)
        if candidates is None:
            route_items.append({
                "question_no": index,
                "status": "safe_auto_grade",
                "recognized": answer,
                "warnings": [],
                "candidates": [],
                "final_answer": answer,
                "source": "safe_auto_grade",
            })
            continue
        route_items.append({
            "question_no": index,
            "status": "review_required",
            "recognized": answer,
            "warnings": ["review required"],
            "candidates": candidates,
            "final_answer": None,
            "source": None,
        })
    route_response = {
        "ok": True,
        "review_payload": {
            "source": "phase2_review_ui_preflight_fixture",
            "test_id": test_id,
            "round": "1",
            "problem_count": 20,
            "items": route_items,
        },
        "warnings": [],
    }
    return f"""
<script>
window.__FETCH_LOGS__ = [];
window.__CONSOLE_ERRORS__ = [];
window.alert = (message) => {{ window.__LAST_ALERT__ = String(message || ''); }};
window.console.error = (...args) => {{ window.__CONSOLE_ERRORS__.push(args.map(String).join(' ')); }};
const PHASE1_BOOTSTRAP = {json.dumps(bootstrap, ensure_ascii=False)};
const PHASE1_TESTS_CONFIG = {json.dumps(tests_config, ensure_ascii=False)};
const PHASE2C_REVIEW_ROUTE_RESPONSE = {json.dumps(route_response, ensure_ascii=False)};
window.fetch = async (input, init = {{}}) => {{
  const url = String(input && input.url ? input.url : input);
  const method = String(init.method || 'GET').toUpperCase();
  const body = init.body;
  const image = body instanceof FormData ? body.get('image') : null;
  const hasImage = image instanceof File;
  window.__FETCH_LOGS__.push({{
    url,
    method,
    hasImage,
    imageName: hasImage ? image.name : '',
    imageType: hasImage ? image.type : '',
    imageSize: hasImage ? image.size : 0,
  }});
  const json = (data, status = 200) => new Response(JSON.stringify(data), {{ status, headers: {{ 'Content-Type': 'application/json' }} }});
  if (url.includes('/api/ocr-test-sheet-review')) {{
    if (!hasImage) return json({{ ok: false, errorCode: 'missing_image', message: 'answer sheet image required', warnings: [] }}, 400);
    return json(PHASE2C_REVIEW_ROUTE_RESPONSE);
  }}
  if (url.includes('/api/student/bootstrap')) return json(PHASE1_BOOTSTRAP);
  if (url.includes('/api/watch/latest')) return json({{}});
  if (url.includes('/api/tests-config')) return json(PHASE1_TESTS_CONFIG);
  if (url.includes('/js/test_answer_link_map.json')) return json({{}});
  if (url.includes('/api/announcements')) return json([]);
  if (url.includes('/api/announce-status')) return json({{}});
  return json({{ ok: true }});
}};
</script>
""".strip()


def phase1_test_fixture(test_id: str) -> dict[str, str]:
    test_name = "Phase 1 allowed test" if test_id == PHASE1_ALLOWED_TEST_ID else "Phase 1 blocked test"
    return {
        "id": test_id,
        "testId": test_id,
        "name": test_name,
        "categoryKey": "UNIT",
        "categoryLabel": "단원평가",
        "round": "1",
        "status": "assigned",
    }


def build_phase1_assertion_script(mode: str, pre_id: str, test_id: str) -> str:
    return f"""
<script>
async function phase1WaitFor(predicate, label) {{
  const started = Date.now();
  while (Date.now() - started < 5000) {{
    if (predicate()) return true;
    await new Promise(resolve => setTimeout(resolve, 50));
  }}
  throw new Error('timeout: ' + label);
}}

function phase1CallCounts() {{
  const logs = Array.isArray(window.__FETCH_LOGS__) ? window.__FETCH_LOGS__ : [];
    return {{
      submitCalls: logs.filter(entry => String(entry.url).includes('/api/submit-test')).length,
      reviewRouteCalls: logs.filter(entry => String(entry.url).includes('/api/ocr-test-sheet-review')).length,
      reviewRouteImageCalls: logs.filter(entry => String(entry.url).includes('/api/ocr-test-sheet-review') && entry.hasImage === true).length,
      ocrApiCalls: logs.filter(entry => String(entry.url).includes('/api/ocr-test-sheet') && !String(entry.url).includes('/api/ocr-test-sheet-review')).length,
      geminiCalls: logs.filter(entry => /google-genai|generativeai|generateContent|generate_content|x-goog-api-key/i.test(String(entry.url))).length,
    }};
}}

function phase1ButtonVisible(button) {{
  return !!button && !button.hidden && !button.disabled && button.offsetParent !== null;
}}

function phase2ReviewHook() {{
  return window.__OCR_PHASE2_REVIEW_TEST_HOOK__ || window.__OCR_PHASE1_TEST_HOOK__;
}}

window.addEventListener('load', async () => {{
  const mode = {json.dumps(mode)};
  const testId = {json.dumps(test_id)};
  const result = {{ mode, testId, ok: false, errors: [] }};
  try {{
    await phase1WaitFor(() => typeof window.openAssignedTestSubmit === 'function' && Array.isArray(window.__ASSIGNED_TESTS__) && window.__ASSIGNED_TESTS__.length > 0, 'student modal init');
    result.flagEnabled = window.__OCR_TEST_SHEET_ENABLED__ === true;
    result.hookPresentBeforeOpen = !!phase2ReviewHook();
    result.phase2HookPresentBeforeOpen = !!window.__OCR_PHASE2_REVIEW_TEST_HOOK__;
    result.ocrButtonPresentBeforeOpen = !!document.getElementById('tsOcrReviewOpen');
    result.ocrButtonVisibleBeforeOpen = phase1ButtonVisible(document.getElementById('tsOcrReviewOpen'));
    result.opened = window.openAssignedTestSubmit(testId);
    await phase1WaitFor(() => document.getElementById('testSubmitModal')?.style.display === 'flex', 'modal open');
    await new Promise(resolve => setTimeout(resolve, 100));
    const openBtn = document.getElementById('tsOcrReviewOpen');
    const statusEl = document.getElementById('tsOcrStatus');
    const answers = document.getElementById('tsAnswersText');
    result.manualInputPresent = !!answers;
    if (answers) {{
      answers.value = 'manual-answer';
      result.manualInputWritable = answers.value === 'manual-answer';
    }}
    result.ocrButtonPresentAfterOpen = !!openBtn;
    result.ocrButtonHiddenAfterOpen = !!openBtn?.hidden;
    result.ocrButtonDisabledAfterOpen = !!openBtn?.disabled;
    result.ocrButtonVisibleAfterOpen = phase1ButtonVisible(openBtn);
    result.statusText = statusEl?.textContent || '';
    result.hookPresentAfterOpen = !!phase2ReviewHook();
    result.phase2HookPresentAfterOpen = !!window.__OCR_PHASE2_REVIEW_TEST_HOOK__;
    result.legacyHookPresentAfterOpen = !!window.__OCR_PHASE1_TEST_HOOK__;
    result.hookEligible = phase2ReviewHook()?.isCurrentTestEligible?.();
    result.allowedIds = phase2ReviewHook()?.allowedTestIds?.() || [];
    result.openRouteFlowType = typeof phase2ReviewHook()?.openRouteFlow;
    result.openReviewFlowType = typeof phase2ReviewHook()?.openReviewFlow;
    result.newHookOpenMockFlowType = typeof window.__OCR_PHASE2_REVIEW_TEST_HOOK__?.openMockFlow;
    result.legacyOpenMockFlowType = typeof window.__OCR_PHASE1_TEST_HOOK__?.openMockFlow;
    result.legacyOpenMockFlowHasRouteFetch = String(window.__OCR_PHASE1_TEST_HOOK__?.openMockFlow || '').includes('ocrReviewFetchRoutePayload');
    result.legacyOpenMockFlowHasDirectMock = String(window.__OCR_PHASE1_TEST_HOOK__?.openMockFlow || '').includes('ocrReviewCreateMockPayload');
    result.lastOpenError = window.__OCR_PHASE1_LAST_OPEN_ERROR__ || '';

    if (mode === 'allowed') {{
      const openFlow = phase2ReviewHook()?.openRouteFlow || phase2ReviewHook()?.openReviewFlow;
      result.openFlowInvoked = typeof openFlow === 'function';
      const uploadFile = new File([new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10])], 'answer-sheet.png', {{ type: 'image/png' }});
      phase2ReviewHook()?.setImageFileForTest?.(uploadFile);
      result.imageInputFileName = document.getElementById('tsOcrReviewImage')?.files?.[0]?.name || '';
      const firstOpenBefore = phase1CallCounts();
      openBtn?.click();
      await phase1WaitFor(() => !document.getElementById('tsOcrReviewPanel')?.hidden, 'review panel');
      const firstOpenAfter = phase1CallCounts();
      const reviewLogs = (window.__FETCH_LOGS__ || []).filter(entry => String(entry.url).includes('/api/ocr-test-sheet-review'));
      const firstReviewLog = reviewLogs[reviewLogs.length - 1] || {{}};
      result.statusTextAfterOpenFlow = statusEl?.textContent || '';
      result.lastOpenErrorAfterOpenFlow = window.__OCR_PHASE1_LAST_OPEN_ERROR__ || '';
      result.reviewUiFixturePayload = typeof PHASE2C_REVIEW_ROUTE_RESPONSE !== 'undefined' && PHASE2C_REVIEW_ROUTE_RESPONSE?.review_payload?.source === 'phase2_review_ui_preflight_fixture';
      result.reviewRouteCallsAfterFirstOpen = firstOpenAfter.reviewRouteCalls - firstOpenBefore.reviewRouteCalls;
      result.reviewRouteImageCallsAfterFirstOpen = firstOpenAfter.reviewRouteImageCalls - firstOpenBefore.reviewRouteImageCalls;
      result.firstReviewRouteHasImage = firstReviewLog.hasImage === true;
      result.firstReviewRouteImageName = firstReviewLog.imageName || '';
      result.firstReviewRouteImageType = firstReviewLog.imageType || '';
      result.submitCallsAfterFirstOpen = firstOpenAfter.submitCalls - firstOpenBefore.submitCalls;
      result.ocrApiCallsAfterFirstOpen = firstOpenAfter.ocrApiCalls - firstOpenBefore.ocrApiCalls;
      result.geminiCallsAfterFirstOpen = firstOpenAfter.geminiCalls - firstOpenBefore.geminiCalls;
      result.reviewItemCountAfterFirstOpen = phase2ReviewHook()?.getCurrentPayload?.()?.items?.length || 0;
      const panel = document.getElementById('tsOcrReviewPanel');
      result.leakInStudentPanel = /expected|canonical_answer|accepted_answers|correct|incorrect|score|wrong|pct/.test(panel?.innerText || '');
      const writingRule = document.getElementById('tsWritingRule');
      const writingNotice = writingRule?.textContent || writingRule?.innerText || '';
      result.writingRuleNoticePresent =
        writingNotice.includes('객관식 문항은 선지 번호만 작성하세요.') &&
        writingNotice.includes('주관식/답값형 문항은 최종 답만 작성하세요.') &&
        writingNotice.includes('풀이식, 중간식, 선지 내용은 오답 처리될 수 있습니다.');
      result.answerModeLabelsPresent =
        (panel?.innerText || '').includes('선택형 · 번호만 입력') &&
        (panel?.innerText || '').includes('답값형 · 최종 답 입력');
      const hook = phase2ReviewHook();
      const basePayload = hook?.createFixturePayload?.() || hook?.createMockPayload?.();
      function phase1CompletePayload(overrideNo, overrideAnswer) {{
        const payload = JSON.parse(JSON.stringify(basePayload));
        const defaults = new Map([[3, '3'], [10, '6'], [18, '139/2'], [19, '3']]);
        payload.items.forEach(item => {{
          const no = Number(item.question_no);
          const hasOverride = Number(overrideNo) === no;
          if (hasOverride || defaults.has(no) || item.status === 'review_required') {{
            item.final_answer = hasOverride ? overrideAnswer : (defaults.has(no) ? defaults.get(no) : item.final_answer);
            item.source = 'student_direct_input';
            item.status = 'student_direct_input';
          }}
        }});
        return payload;
      }}
      const invalidChoiceCases = [['x=2', 3], ['3sqrt(2)', 9], ['1,3', 13]];
      result.invalidChoiceBlocks = invalidChoiceCases.map(([answer, no]) => {{
        try {{
          hook.convertToAnswersText(phase1CompletePayload(no, answer));
          return false;
        }} catch (err) {{
          const message = String(err?.message || err);
          return message.includes(`${{no}}번`) && message.includes('선택형');
        }}
      }}).every(Boolean);
      try {{
        const validText = hook.convertToAnswersText(phase1CompletePayload(3, '3'));
        const validLines = validText.split('\\n');
        result.validChoicePasses = validLines.length === 20 && validLines.every(line => line.trim());
      }} catch (err) {{
        result.validChoicePasses = false;
        result.validChoiceError = String(err?.message || err);
      }}
      document.querySelector('.ts-ocr-apply')?.click();
      const blockedStatusText = statusEl?.textContent || '';
      result.blockedBeforeConfirm = /\uBA3C\uC800 \uCC98\uB9AC|\uCC98\uB9AC\uD574\uC57C|\uC9C1\uC811 \uACE8\uB77C|\uC9C1\uC811 \uD655\uC778|\uD655\uC815\uD574\uC57C|\uC120\uD0DD\uD615/.test(blockedStatusText);
      async function phase1ConfirmVisibleReviewCards(answerByQuestion) {{
        let guard = 0;
        while (document.querySelector('.ts-ocr-confirm') && guard < 20) {{
          const card = document.querySelector('.ts-ocr-card');
          const title = card?.querySelector('h4')?.textContent || '';
          const no = Number((title.match(/\\d+/) || ['0'])[0]);
          const input = card?.querySelector('.ts-ocr-current');
          if (input) {{
            input.value = answerByQuestion.get(no) || '3';
            input.dataset.answerSource = 'student_direct_input';
            input.dispatchEvent(new Event('input', {{ bubbles: true }}));
          }}
          document.querySelector('.ts-ocr-confirm')?.click();
          await new Promise(resolve => setTimeout(resolve, 0));
          guard += 1;
        }}
        return guard;
      }}
      await phase1ConfirmVisibleReviewCards(new Map([[3, 'x=2'], [10, '6'], [18, '139/2'], [19, '3']]));
      const invalidChoiceConfirmStatusText = statusEl?.textContent || '';
      result.invalidChoiceConfirmBlocked = /\uC120\uD0DD\uD615/.test(invalidChoiceConfirmStatusText) && /3\uBC88/.test(invalidChoiceConfirmStatusText);
      document.querySelector('.ts-ocr-apply')?.click();
      const invalidChoiceApplyStatusText = statusEl?.textContent || '';
      result.invalidChoiceApplyBlocked = result.invalidChoiceConfirmBlocked || (/\uC120\uD0DD\uD615/.test(invalidChoiceApplyStatusText) && /3\uBC88/.test(invalidChoiceApplyStatusText));
      result.answersUnchangedAfterInvalidChoiceApply = answers?.value === 'manual-answer';
      if (result.openFlowInvoked) await openFlow();
      await phase1WaitFor(() => !document.getElementById('tsOcrReviewPanel')?.hidden, 'review panel reset');
      await new Promise(resolve => setTimeout(resolve, 0));
      await phase1ConfirmVisibleReviewCards(new Map([[3, '3'], [10, '6'], [18, '139/2'], [19, '3']]));
      document.querySelector('.ts-ocr-apply')?.click();
      const finalAnswers = answers?.value || '';
      result.answersLineCount = finalAnswers ? finalAnswers.split('\\n').length : 0;
      result.answersNonEmptyLineCount = finalAnswers ? finalAnswers.split('\\n').filter(line => line.trim()).length : 0;
      result.reviewPanelVisible = !document.getElementById('tsOcrReviewPanel')?.hidden;
    }}

    if (mode === 'blocked') {{
      result.createMockPayloadBlocked = false;
      try {{ phase2ReviewHook()?.createFixturePayload?.(); }}
      catch (err) {{ result.createMockPayloadBlocked = String(err?.message || err).includes({json.dumps(PHASE1_INELIGIBLE_MESSAGE)}); }}
      phase2ReviewHook()?.openRouteFlow?.();
      await new Promise(resolve => setTimeout(resolve, 100));
      result.reviewPanelVisible = !document.getElementById('tsOcrReviewPanel')?.hidden;
    }}

    if (mode === 'selection_change') {{
      const testSelect = document.getElementById('tsTestId');
      result.allowedInitialEligible = phase2ReviewHook()?.isCurrentTestEligible?.();
      result.allowedInitialVisible = phase1ButtonVisible(openBtn);
      testSelect.value = {json.dumps(PHASE1_BLOCKED_TEST_ID)};
      testSelect.dispatchEvent(new Event('change', {{ bubbles: true }}));
      await new Promise(resolve => setTimeout(resolve, 100));
      result.blockedEligibleAfterChange = phase2ReviewHook()?.isCurrentTestEligible?.();
      result.blockedHiddenAfterChange = !!openBtn?.hidden;
      result.blockedDisabledAfterChange = !!openBtn?.disabled;
      result.blockedVisibleAfterChange = phase1ButtonVisible(openBtn);
      result.blockedStatusText = statusEl?.textContent || '';
      testSelect.value = {json.dumps(PHASE1_ALLOWED_TEST_ID)};
      testSelect.dispatchEvent(new Event('change', {{ bubbles: true }}));
      await new Promise(resolve => setTimeout(resolve, 100));
      result.allowedEligibleAfterReturn = phase2ReviewHook()?.isCurrentTestEligible?.();
      result.allowedVisibleAfterReturn = phase1ButtonVisible(openBtn);
      result.allowedDisabledAfterReturn = !!openBtn?.disabled;
    }}

    Object.assign(result, phase1CallCounts());
    result.consoleErrors = window.__CONSOLE_ERRORS__ || [];
    if (mode === 'flag_off') {{
      result.ok = result.flagEnabled === false && !result.hookPresentAfterOpen && !result.ocrButtonPresentAfterOpen && result.opened && result.manualInputWritable && result.submitCalls === 0 && result.reviewRouteCalls === 0 && result.ocrApiCalls === 0 && result.geminiCalls === 0 && result.consoleErrors.length === 0;
    }} else if (mode === 'allowed') {{
      result.ok = result.flagEnabled === true && result.phase2HookPresentAfterOpen && result.hookPresentAfterOpen && result.hookEligible === true && result.allowedIds.includes({json.dumps(PHASE1_ALLOWED_TEST_ID)}) && result.ocrButtonVisibleAfterOpen && result.blockedBeforeConfirm && result.writingRuleNoticePresent && result.answerModeLabelsPresent && result.invalidChoiceBlocks && result.validChoicePasses && result.invalidChoiceApplyBlocked && result.answersUnchangedAfterInvalidChoiceApply && result.answersLineCount === 20 && result.answersNonEmptyLineCount === 20 && result.reviewItemCountAfterFirstOpen === 20 && result.reviewRouteCallsAfterFirstOpen === 1 && result.reviewRouteImageCallsAfterFirstOpen === 1 && result.reviewUiFixturePayload === true && result.firstReviewRouteHasImage === true && result.firstReviewRouteImageName === 'answer-sheet.png' && result.firstReviewRouteImageType === 'image/png' && result.submitCallsAfterFirstOpen === 0 && result.ocrApiCallsAfterFirstOpen === 0 && result.geminiCallsAfterFirstOpen === 0 && result.submitCalls === 0 && result.reviewRouteCalls === 2 && result.reviewRouteImageCalls === 2 && result.ocrApiCalls === 0 && result.geminiCalls === 0 && result.openRouteFlowType === 'function' && result.openReviewFlowType === 'function' && result.newHookOpenMockFlowType === 'undefined' && result.legacyOpenMockFlowHasRouteFetch === true && result.legacyOpenMockFlowHasDirectMock === false && !result.leakInStudentPanel && result.consoleErrors.length === 0;
    }} else if (mode === 'blocked') {{
      result.ok = result.flagEnabled === true && result.hookPresentAfterOpen && result.hookEligible === false && result.ocrButtonPresentAfterOpen && !result.ocrButtonVisibleAfterOpen && (result.ocrButtonHiddenAfterOpen || result.ocrButtonDisabledAfterOpen) && result.statusText === {json.dumps(PHASE1_INELIGIBLE_MESSAGE)} && result.createMockPayloadBlocked && !result.reviewPanelVisible && result.manualInputWritable && result.submitCalls === 0 && result.reviewRouteCalls === 0 && result.ocrApiCalls === 0 && result.geminiCalls === 0 && result.consoleErrors.length === 0;
    }} else if (mode === 'selection_change') {{
      result.ok = result.flagEnabled === true && result.hookPresentAfterOpen && result.allowedInitialEligible === true && result.allowedInitialVisible === true && result.blockedEligibleAfterChange === false && !result.blockedVisibleAfterChange && (result.blockedHiddenAfterChange || result.blockedDisabledAfterChange) && result.blockedStatusText === {json.dumps(PHASE1_INELIGIBLE_MESSAGE)} && result.allowedEligibleAfterReturn === true && result.allowedVisibleAfterReturn === true && result.allowedDisabledAfterReturn === false && result.manualInputWritable && result.submitCalls === 0 && result.reviewRouteCalls === 0 && result.ocrApiCalls === 0 && result.geminiCalls === 0 && result.consoleErrors.length === 0;
    }}
  }} catch (err) {{
    result.errors.push(String(err && err.stack || err));
    Object.assign(result, phase1CallCounts());
    result.consoleErrors = window.__CONSOLE_ERRORS__ || [];
    result.statusTextAfterError = document.getElementById('tsOcrStatus')?.textContent || '';
    result.lastOpenErrorAfterError = window.__OCR_PHASE1_LAST_OPEN_ERROR__ || '';
  }}
  const pre = document.createElement('pre');
  pre.id = {json.dumps(pre_id)};
  pre.textContent = JSON.stringify(result, null, 2);
  document.body.appendChild(pre);
}});
</script>
""".strip()


def extract_pre_json(dom: str, pre_id: str) -> dict[str, JsonValue] | None:
    pattern = "<pre\\b[^>]*\\bid=[\"']" + re.escape(pre_id) + "[\"'][^>]*>(.*?)</pre>"
    match = re.search(pattern, dom, flags=re.DOTALL)
    if match:
        text = unescape(match.group(1)).strip()
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else None
    match = re.search(rf"<pre\b[^>]*id=[\"']{re.escape(pre_id)}[\"'][^>]*>(.*?)</pre>", dom, flags=re.DOTALL)
    if not match:
        return None
    text = unescape(match.group(1)).strip()
    payload = json.loads(text)
    return payload if isinstance(payload, dict) else None


def run_safety_scans() -> list[CheckResult]:
    files = generated_text_files()
    return [
        scan_secret_patterns(files),
        scan_env_values(files),
        scan_student_output_keys(),
        scan_submit_call_strings(files),
        scan_gemini_call_references(files),
    ]


def generated_text_files() -> tuple[Path, ...]:
    suffixes = {".json", ".md", ".csv", ".txt"}
    paths: list[Path] = []
    paths.extend(path for path in phase1_lab_outputs() if path.exists())
    for root in (OUT_DIR / "evaluate_ocr_policy_regression", OUT_DIR / "review_ui_mock_policy"):
        if root.exists():
            paths.extend(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in suffixes)
    paths.extend(path for path in (
        OUT_DIR / "ocr_benchmark_gate_report.json",
        OUT_DIR / "ocr_benchmark_gate_report.md",
        REPORT_JSON,
        REPORT_MD,
    ) if path.exists())
    return tuple(sorted(set(paths)))


def phase1_lab_outputs() -> tuple[Path, ...]:
    return (
        LAB / "final_review_payload_answersText.txt",
        LAB / "final_review_payload_bridge_report.md",
        LAB / "subjective_review_dry_run_review_payload.json",
        LAB / "subjective_review_dry_run_final_payload.json",
        LAB / "subjective_review_dry_run_answersText.txt",
        LAB / "subjective_review_dry_run_report.md",
        LAB / "phase1_hidden_integration_patch.patch",
        LAB / "phase1_hidden_integration_verification.md",
        LAB / "phase1_hidden_integration_manual_qa_checklist.md",
        LAB / "phase1_ocr_eligibility_guard_report.md",
    )


def scan_secret_patterns(files: tuple[Path, ...]) -> CheckResult:
    matches = scan_files(files, SECRET_PATTERN)
    return scan_result("secret_pattern_scan", not matches, f"{len(matches)} secret-like matches", matches)


def scan_env_values(files: tuple[Path, ...]) -> CheckResult:
    values = env_secret_values()
    if not values:
        return CheckResult("env_value_scan", "pass", "local file scan", None, 0.0, "no .env secret values loaded")
    matches: list[str] = []
    for path in files:
        text = read_text(path)
        if any(value in text for value in values):
            matches.append(str(path))
    return scan_result("env_value_scan", not matches, f"{len(matches)} .env value matches", tuple(matches))


def scan_student_output_keys() -> CheckResult:
    targets = tuple(path for path in (
        LAB / "final_review_payload_answersText.txt",
        LAB / "subjective_review_dry_run_review_payload.json",
        LAB / "subjective_review_dry_run_final_payload.json",
        LAB / "subjective_review_dry_run_answersText.txt",
    ) if path.exists())
    pattern = re.compile("|".join(re.escape(key) for key in FORBIDDEN_STUDENT_KEYS))
    matches = scan_files(targets, pattern)
    return scan_result("student_output_answer_key_leak_scan", not matches, f"{len(matches)} forbidden key matches", matches)


def scan_submit_call_strings(files: tuple[Path, ...]) -> CheckResult:
    non_doc_files = tuple(path for path in files if path.suffix.lower() != ".md")
    matches = scan_files(non_doc_files, SUBMIT_CALL_PATTERN)
    return scan_result("submit_call_scan", not matches, f"{len(matches)} non-doc submit call matches", matches)


def scan_gemini_call_references(files: tuple[Path, ...]) -> CheckResult:
    non_doc_files = tuple(path for path in files if path.suffix.lower() != ".md")
    matches = scan_files(non_doc_files, GEMINI_CALL_PATTERN)
    return scan_result("gemini_provider_call_reference_scan", not matches, f"{len(matches)} non-doc provider call references", matches)


def scan_result(name: str, passed: bool, reason: str, matches: tuple[str, ...] | list[str]) -> CheckResult:
    status: CheckStatus = "pass" if passed else "fail"
    detail = reason if passed else "; ".join(list(matches)[:20])
    return CheckResult(name, status, "local file scan", None, 0.0, detail)


def scan_files(files: tuple[Path, ...], pattern: re.Pattern[str]) -> tuple[str, ...]:
    matches: list[str] = []
    for path in files:
        text = read_text(path)
        if pattern.search(text):
            matches.append(str(path))
    return tuple(matches)


def env_secret_values() -> tuple[str, ...]:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return ()
    values: list[str] = []
    for line in env_path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        value = stripped.split("=", 1)[1].strip().strip('"').strip("'")
        if len(value) >= 12 and "DUMMY" not in value.upper():
            values.append(value)
    return tuple(values)


def read_production_default_status() -> bool:
    path = OUT_DIR / "ocr_benchmark_gate_report.json"
    if not path.is_file():
        return False
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        return False
    return payload.get("production_default_status") == "NO_GO" and payload.get("production_default_allowed") is False


def build_report_payload(results: list[CheckResult], production_default_no_go: bool, ready_for_manual_qa: bool) -> dict[str, JsonValue]:
    failed = [item for item in results if item.status == "fail"]
    warnings = [item for item in results if item.status == "warning"]
    skipped = [item for item in results if item.status == "skipped"]
    return {
        "summary": {
            "total_checks": len(results),
            "failed_checks": len(failed),
            "warning_checks": len(warnings),
            "skipped_checks": len(skipped),
            "ready_for_manual_qa": ready_for_manual_qa,
            "production_default_remains_no_go": production_default_no_go,
        },
        "checks": [result_to_json(item) for item in results],
    }


def result_to_json(result: CheckResult) -> dict[str, JsonValue]:
    return {
        "name": result.name,
        "status": result.status,
        "command": result.command,
        "exit_code": result.exit_code,
        "duration_seconds": result.duration_seconds,
        "reason": result.reason,
        "stdout_tail": result.stdout_tail,
        "stderr_tail": result.stderr_tail,
    }


def build_markdown(results: list[CheckResult], production_default_no_go: bool, ready_for_manual_qa: bool) -> str:
    failed = sum(1 for item in results if item.status == "fail")
    warnings = sum(1 for item in results if item.status == "warning")
    skipped = sum(1 for item in results if item.status == "skipped")
    lines = [
        "# Phase 1 Hidden OCR Preflight Report",
        "",
        f"- total checks: {len(results)}",
        f"- failed checks: {failed}",
        f"- warning checks: {warnings}",
        f"- skipped checks: {skipped}",
        f"- ready for manual QA: {ready_for_manual_qa}",
        f"- production default remains NO_GO: {production_default_no_go}",
        "",
        "| check | status | reason |",
        "|---|---|---|",
    ]
    lines.extend(f"| {item.name} | {item.status} | {escape_md(item.reason)} |" for item in results)
    return "\n".join(lines) + "\n"


def command_text(command: tuple[str, ...]) -> str:
    return " ".join(command)


def tail(value: str | bytes | None) -> str:
    if value is None:
        return ""
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
    return text[-2000:]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def escape_md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br>")


if __name__ == "__main__":
    raise SystemExit(main())
