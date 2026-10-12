from __future__ import annotations

import subprocess
import time

from ocr_preflight_environment_matrix_model import (
    APP_ENV,
    COMMANDS,
    OCR_ENV,
    ROOT,
    TIMEOUT_SECONDS,
    ArtifactSummary,
    CommandProbe,
    CommandSpec,
    EnvironmentSpec,
    JsonValue,
    MatrixReport,
    PackageProbe,
)
from ocr_preflight_environment_matrix_output import command_label, parse_json, parse_module_map, tail

ARTIFACT_FIELDS = (
    "ok",
    "extended_gate_count",
    "provider_call_count",
    "external_ocr_api_call_count",
    "submit_test_call_count",
    "ts_submit_click_count",
    "answer_key_or_grading_field_leak_count",
    "filesystem_path_leak_count",
    "production_default",
)


class EnvironmentMatrixError(Exception):
    pass


def create_report() -> MatrixReport:
    package_probes = [probe_environment(spec) for spec in (OCR_ENV, APP_ENV)]
    command_probes = [run_command(spec) for spec in COMMANDS]
    return build_report(package_probes, command_probes)


def probe_environment(spec: EnvironmentSpec) -> PackageProbe:
    if not spec.python.is_file():
        return {
            "environment": spec.name,
            "python": str(spec.python),
            "exists": False,
            "modules": {},
            "ok": False,
            "reason": "python executable missing",
        }
    script = (
        "import importlib.util, json; "
        f"mods={list(spec.required_modules)!r}; "
        "print(json.dumps({name: importlib.util.find_spec(name) is not None for name in mods}))"
    )
    completed = subprocess.run(
        (str(spec.python), "-c", script),
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    modules = parse_module_map(completed.stdout)
    ok = completed.returncode == 0 and all(modules.get(name) is True for name in spec.required_modules)
    return {
        "environment": spec.name,
        "python": str(spec.python),
        "exists": True,
        "modules": modules,
        "ok": ok,
        "reason": "ok" if ok else completed.stderr[-1000:] or "required module missing",
    }


def run_command(spec: CommandSpec) -> CommandProbe:
    command = (str(spec.environment.python), *spec.args)
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return timeout_probe(spec, command, exc)
    duration = round(time.perf_counter() - started, 3)
    return {
        "name": spec.name,
        "environment": spec.environment.name,
        "command": command_label(command),
        "exit_code": completed.returncode,
        "duration_seconds": duration,
        "ok": completed.returncode == 0,
        "stdout_json": parse_json(completed.stdout),
        "artifact_summary": read_artifact_summary(spec),
        "stdout_tail": tail(completed.stdout),
        "stderr_tail": tail(completed.stderr),
    }


def timeout_probe(
    spec: CommandSpec,
    command: tuple[str, ...],
    exc: subprocess.TimeoutExpired,
) -> CommandProbe:
    return {
        "name": spec.name,
        "environment": spec.environment.name,
        "command": command_label(command),
        "exit_code": None,
        "duration_seconds": TIMEOUT_SECONDS,
        "ok": False,
        "stdout_json": None,
        "artifact_summary": read_artifact_summary(spec),
        "stdout_tail": tail(exc.stdout),
        "stderr_tail": tail(exc.stderr),
    }


def build_report(package_probes: list[PackageProbe], command_probes: list[CommandProbe]) -> MatrixReport:
    ok = all(item["ok"] for item in package_probes) and all(item["ok"] for item in command_probes)
    return {
        "ok": ok,
        "student_facing": False,
        "provider_call_count": sum_reported_count(command_probes, "provider_call_count"),
        "external_ocr_api_call_count": sum_reported_count(command_probes, "external_ocr_api_call_count"),
        "submit_test_call_count": sum_reported_count(command_probes, "submit_test_call_count"),
        "ts_submit_click_count": sum_reported_count(command_probes, "ts_submit_click_count"),
        "extended_gate_count": first_artifact_int(command_probes, "extended_gate_count"),
        "answer_key_or_grading_field_leak_count": sum_artifact_int(command_probes, "answer_key_or_grading_field_leak_count"),
        "filesystem_path_leak_count": sum_artifact_int(command_probes, "filesystem_path_leak_count"),
        "production_default": "NO_GO",
        "package_probes": package_probes,
        "command_probes": command_probes,
        "route_or_app_checks_require_app_venv": True,
        "image_ocr_checks_require_ocr_venv": True,
        "preflight_script_modified": False,
        "recommended_operator_note": (
            "Run image/numpy/OpenCV OCR checks with C:/server-ocr/.venv, "
            "and Flask/app-import checks with C:/server/venv."
        ),
    }


def read_artifact_summary(spec: CommandSpec) -> ArtifactSummary:
    if spec.artifact_json is None:
        return {"path": None, "exists": False, "fields": {}}
    if not spec.artifact_json.is_file():
        return {"path": str(spec.artifact_json), "exists": False, "fields": {}}
    try:
        parsed = parse_json(spec.artifact_json.read_text(encoding="utf-8"))
    except OSError:
        return {"path": str(spec.artifact_json), "exists": True, "fields": {}}
    if not isinstance(parsed, dict):
        return {"path": str(spec.artifact_json), "exists": True, "fields": {}}
    return {
        "path": str(spec.artifact_json),
        "exists": True,
        "fields": {field: parsed.get(field) for field in ARTIFACT_FIELDS},
    }


def sum_reported_count(command_probes: list[CommandProbe], field: str) -> int:
    total = 0
    for item in command_probes:
        value = json_field(item["stdout_json"], field)
        if isinstance(value, int):
            total += value
        artifact_value = json_field(item["artifact_summary"]["fields"], field)
        if isinstance(artifact_value, int):
            total += artifact_value
    return total


def sum_artifact_int(command_probes: list[CommandProbe], field: str) -> int:
    total = 0
    for item in command_probes:
        value = json_field(item["artifact_summary"]["fields"], field)
        if isinstance(value, int):
            total += value
    return total


def first_artifact_int(command_probes: list[CommandProbe], field: str) -> int | None:
    for item in command_probes:
        value = json_field(item["artifact_summary"]["fields"], field)
        if isinstance(value, int):
            return value
    return None


def json_field(value: JsonValue, field: str) -> JsonValue:
    if isinstance(value, dict):
        return value.get(field)
    return None
