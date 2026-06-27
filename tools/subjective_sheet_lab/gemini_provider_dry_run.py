from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

from gemini_provider import ContactImage, build_contact_payload, contact_image_from_path

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]

PROVIDER_PHRASES: Final[tuple[str, ...]] = (
    "original crop as the primary evidence",
    "enhanced crop is only a secondary reference",
    "If original and enhanced disagree",
    "Do not infer an equals sign from an arrow-like stroke",
    "Do not confuse x and n",
    "Do not confuse 6 and 0",
    "do not convert them to 7",
    "Return JSON only",
)
ASSET_PHRASES: Final[tuple[str, ...]] = (
    "original crop is the primary evidence",
    "soft enhanced crop is secondary",
    "If original and enhanced disagree, do not guess",
    "Do not confuse x and n",
    "Do not confuse 0 and 6",
    "do not convert them to 7, 4, C, 2, L",
)


@dataclass(frozen=True, slots=True)
class DryRunConfig:
    manifest_path: Path
    out_path: Path


@dataclass(frozen=True, slots=True)
class PhraseCheck:
    phrase: str
    ok: bool


@dataclass(frozen=True, slots=True)
class ContactSummary:
    path: str
    bytes: int
    questions: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class DryRunReport:
    ok: bool
    api_calls: int
    manifest: str
    out_path: str
    contact_sheets: tuple[ContactSummary, ...]
    provider_prompt_checks: tuple[PhraseCheck, ...]
    asset_prompt_checks: tuple[PhraseCheck, ...]
    payload_part_count: int
    inline_image_count: int
    failures: tuple[str, ...]


class DryRunError(Exception):
    pass


def main() -> int:
    config = parse_args()
    report = build_report(config)
    write_report(config.out_path, report)
    if not report.ok:
        raise DryRunError("; ".join(report.failures))
    print(json.dumps({"ok": True, "api_calls": 0, "out": str(config.out_path)}, ensure_ascii=False))
    return 0


def parse_args() -> DryRunConfig:
    parser = argparse.ArgumentParser(description="Validate Gemini provider contact-sheet inputs without API calls.")
    parser.add_argument("--asset-manifest", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    return DryRunConfig(manifest_path=args.asset_manifest.resolve(), out_path=args.out.resolve())


def build_report(config: DryRunConfig) -> DryRunReport:
    manifest = load_manifest(config.manifest_path)
    contacts = tuple(contact_image_from_path(path) for path in manifest_contact_paths(manifest))
    payload = build_contact_payload(list(contacts))
    provider_prompt = provider_prompt_text(payload)
    asset_prompt = manifest_prompt_path(manifest).read_text(encoding="utf-8-sig")
    provider_checks = tuple(PhraseCheck(phrase, phrase in provider_prompt) for phrase in PROVIDER_PHRASES)
    asset_checks = tuple(PhraseCheck(phrase, phrase in asset_prompt) for phrase in ASSET_PHRASES)
    failures = tuple(f"missing provider prompt phrase: {check.phrase}" for check in provider_checks if not check.ok) + tuple(f"missing asset prompt phrase: {check.phrase}" for check in asset_checks if not check.ok)
    return DryRunReport(
        ok=not failures,
        api_calls=0,
        manifest=str(config.manifest_path),
        out_path=str(config.out_path),
        contact_sheets=tuple(contact_summary(contact) for contact in contacts),
        provider_prompt_checks=provider_checks,
        asset_prompt_checks=asset_checks,
        payload_part_count=payload_part_count(payload),
        inline_image_count=len(contacts),
        failures=failures,
    )


def load_manifest(path: Path) -> dict[str, JsonValue]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise DryRunError("asset manifest must be a JSON object")
    return payload


def manifest_contact_paths(manifest: dict[str, JsonValue]) -> tuple[Path, ...]:
    value = manifest.get("contact_sheets")
    if not isinstance(value, list):
        raise DryRunError("asset manifest contact_sheets must be a list")
    return tuple(Path(str(path)) for path in value)


def manifest_prompt_path(manifest: dict[str, JsonValue]) -> Path:
    value = manifest.get("prompt")
    if not isinstance(value, str):
        raise DryRunError("asset manifest prompt must be a string")
    return Path(value)


def provider_prompt_text(payload: dict[str, JsonValue]) -> str:
    contents = payload.get("contents")
    if not isinstance(contents, list) or not contents:
        raise DryRunError("payload lacks contents")
    first = contents[0]
    if not isinstance(first, dict):
        raise DryRunError("payload content is invalid")
    parts = first.get("parts")
    if not isinstance(parts, list) or not parts:
        raise DryRunError("payload lacks parts")
    prompt_part = parts[0]
    if not isinstance(prompt_part, dict) or not isinstance(prompt_part.get("text"), str):
        raise DryRunError("payload lacks prompt text")
    return str(prompt_part["text"])


def payload_part_count(payload: dict[str, JsonValue]) -> int:
    contents = payload.get("contents")
    if not isinstance(contents, list) or not contents:
        return 0
    first = contents[0]
    if not isinstance(first, dict):
        return 0
    parts = first.get("parts")
    return len(parts) if isinstance(parts, list) else 0


def contact_summary(contact: ContactImage) -> ContactSummary:
    return ContactSummary(path=str(contact.path), bytes=contact.path.stat().st_size, questions=contact.questions)


def write_report(path: Path, report: DryRunReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Gemini provider dry run",
        "",
        f"- ok: {report.ok}",
        f"- api_calls: {report.api_calls}",
        f"- contact_sheets: {len(report.contact_sheets)}",
        f"- payload_part_count: {report.payload_part_count}",
        f"- inline_image_count: {report.inline_image_count}",
        f"- failures: {len(report.failures)}",
        "",
        "## Provider prompt checks",
        "",
        "| phrase | ok |",
        "|---|---:|",
    ]
    for check in report.provider_prompt_checks:
        lines.append(f"| `{check.phrase}` | {check.ok} |")
    lines += ["", "## Asset prompt checks", "", "| phrase | ok |", "|---|---:|"]
    for check in report.asset_prompt_checks:
        lines.append(f"| `{check.phrase}` | {check.ok} |")
    path.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
