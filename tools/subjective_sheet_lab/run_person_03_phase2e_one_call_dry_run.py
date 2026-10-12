# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# Dry run, no route call:
# python tools\subjective_sheet_lab\run_person_03_phase2e_one_call_dry_run.py
#
# Provider-free route dry-run:
# python tools\subjective_sheet_lab\run_person_03_phase2e_one_call_dry_run.py --route-dry-run
#
# Live run is gated and must not be used without explicit authorization:
# python tools\subjective_sheet_lab\run_person_03_phase2e_one_call_dry_run.py --execute-live-call --provider-call-budget 1 --authorization-file <utf8-approval.txt>

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.subjective_sheet_lab.person_03_phase2e_runner_support import (  # noqa: E402
    authorization_error,
    dry_run_summary,
    run_route,
)

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class CliConfig:
    route_dry_run: bool
    execute_live_call: bool
    provider_call_budget: int
    authorization_file: Path | None


class Person03RunnerCliError(Exception):
    pass


def main() -> int:
    config = parse_args(sys.argv[1:])
    auth_error = authorization_error(config.execute_live_call, config.provider_call_budget, config.authorization_file)
    if config.execute_live_call and auth_error:
        print_json({"ok": False, "status": "USER_APPROVAL_REQUIRED", "error": auth_error, "provider_call_count": 0})
        return 2
    if config.route_dry_run or config.execute_live_call:
        print_json(run_route(config.execute_live_call, config.provider_call_budget))
        return 0
    print_json(dry_run_summary(config.provider_call_budget))
    return 0


def parse_args(args: list[str]) -> CliConfig:
    route_dry_run = False
    execute_live_call = False
    provider_call_budget = 0
    authorization_file: Path | None = None
    index = 0
    while index < len(args):
        arg = args[index]
        match arg:
            case "--route-dry-run":
                route_dry_run = True
            case "--execute-live-call":
                execute_live_call = True
            case "--provider-call-budget":
                index += 1
                provider_call_budget = required_int(args, index, arg)
            case "--authorization-file":
                index += 1
                authorization_file = required_path(args, index, arg)
            case _:
                raise Person03RunnerCliError(f"unknown argument: {arg}")
        index += 1
    return CliConfig(route_dry_run, execute_live_call, provider_call_budget, authorization_file)


def required_int(args: list[str], index: int, arg: str) -> int:
    if index >= len(args):
        raise Person03RunnerCliError(f"{arg} requires a value")
    try:
        return int(args[index])
    except ValueError as exc:
        raise Person03RunnerCliError(f"{arg} must be an integer") from exc


def required_path(args: list[str], index: int, arg: str) -> Path:
    if index >= len(args):
        raise Person03RunnerCliError(f"{arg} requires a value")
    return Path(args[index])


def print_json(payload: JsonObject) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
