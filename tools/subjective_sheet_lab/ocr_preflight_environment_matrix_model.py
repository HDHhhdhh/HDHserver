from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, TypeAlias, TypedDict

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
ProbeStatus: TypeAlias = Literal["pass", "fail"]

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
LAB: Final[Path] = Path(__file__).resolve().parent
OCR_PYTHON: Final[Path] = Path(r"C:\server-ocr\.venv\Scripts\python.exe")
APP_PYTHON: Final[Path] = ROOT / "venv" / "Scripts" / "python.exe"
REPORT_JSON: Final[Path] = LAB / "ocr_preflight_environment_matrix.json"
REPORT_MD: Final[Path] = LAB / "ocr_preflight_environment_matrix.md"
TIMEOUT_SECONDS: Final[int] = 120


class PackageProbe(TypedDict):
    environment: str
    python: str
    exists: bool
    modules: dict[str, bool]
    ok: bool
    reason: str


class ArtifactSummary(TypedDict):
    path: str | None
    exists: bool
    fields: dict[str, JsonValue]


class CommandProbe(TypedDict):
    name: str
    environment: str
    command: str
    exit_code: int | None
    duration_seconds: float
    ok: bool
    stdout_json: JsonValue
    artifact_summary: ArtifactSummary
    stdout_tail: str
    stderr_tail: str


class MatrixReport(TypedDict):
    ok: bool
    student_facing: bool
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    extended_gate_count: int | None
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    package_probes: list[PackageProbe]
    command_probes: list[CommandProbe]
    route_or_app_checks_require_app_venv: bool
    image_ocr_checks_require_ocr_venv: bool
    preflight_script_modified: bool
    recommended_operator_note: str


@dataclass(frozen=True, slots=True)
class EnvironmentSpec:
    name: str
    python: Path
    required_modules: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CommandSpec:
    name: str
    environment: EnvironmentSpec
    args: tuple[str, ...]
    artifact_json: Path | None = None


OCR_ENV: Final[EnvironmentSpec] = EnvironmentSpec(
    "ocr_venv",
    OCR_PYTHON,
    ("numpy", "cv2"),
)
APP_ENV: Final[EnvironmentSpec] = EnvironmentSpec(
    "app_venv",
    APP_PYTHON,
    ("flask",),
)
COMMANDS: Final[tuple[CommandSpec, ...]] = (
    CommandSpec(
        "ocr_extended_provider_free_gate",
        OCR_ENV,
        ("tools/subjective_sheet_lab/verify_ocr_provider_free_accuracy_gate_extended.py",),
        LAB / "ocr_provider_free_accuracy_gate_extended.json",
    ),
    CommandSpec(
        "admin_tests_record_detail_leak_extended",
        APP_ENV,
        ("tools/subjective_sheet_lab/verify_admin_tests_record_detail_leak_extended.py",),
    ),
    CommandSpec(
        "submit_test_assignment_round_matching",
        APP_ENV,
        ("scripts/verify_submit_test_assignment_round_matching.py",),
    ),
    CommandSpec(
        "person_03_phase2e_provider_free_route_dry_run",
        APP_ENV,
        ("tools/subjective_sheet_lab/run_person_03_phase2e_one_call_dry_run.py", "--route-dry-run"),
    ),
)
