from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.absent import load_absent
from core.makeup_sheet_sync import (
    SHEET_SYNC_MAX_ROW,
    merge_additive_sheet_absences,
    partition_excluded_sheet_candidates,
    read_additive_sheet_candidates,
)
from core.paths import ABS_PATH, PRG_PATH, UPD_PATH
from core.storage import file_lock, load, save_atomic
from routes.absence_assignment_cleanup import (
    absence_write_scope,
    commit_new_absences_locked,
)


KST = dt.timezone(dt.timedelta(hours=9))
CONFIG_PATH = ROOT / "instance" / "makeup_sheet_sync.json"
STATUS_PATH = ROOT / "instance" / "makeup_sheet_sync_status.json"
CARRYOVER_PATH = ROOT / "makeup_carryover.json"
BACKUP_DIR = ROOT / "_runtime_backups" / "makeup-sheet-sync"
BACKUP_KEEP = 30


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def month_anchor(value: dt.date, offset: int) -> dt.date:
    absolute_month = value.year * 12 + value.month - 1 + offset
    year, zero_month = divmod(absolute_month, 12)
    return dt.date(year, zero_month + 1, 1)


def load_config() -> dict:
    try:
        raw = json.loads(CONFIG_PATH.read_text("utf-8-sig"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"동기화 설정 파일이 없습니다: {CONFIG_PATH}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"동기화 설정 파일을 읽지 못했습니다: {exc}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError("동기화 설정 형식이 올바르지 않습니다.")
    sheet_url = str(raw.get("sheetUrl") or "").strip()
    if "docs.google.com/spreadsheets/d/" not in sheet_url:
        raise RuntimeError("Google Sheets 링크가 설정되지 않았습니다.")
    return {
        "enabled": raw.get("enabled") is True,
        "sheetUrl": sheet_url,
        "maxSheetRow": SHEET_SYNC_MAX_ROW,
        "monthsBack": 1,
        "excludedCandidates": raw.get("excludedCandidates") if isinstance(raw.get("excludedCandidates"), list) else [],
    }


def collect_candidates(sheet_url: str, today: dt.date) -> tuple[list[dict], list[dict]]:
    candidates: list[dict] = []
    months: list[dict] = []
    for anchor in (month_anchor(today, -1), month_anchor(today, 0)):
        snapshot = read_additive_sheet_candidates(sheet_url, anchor.isoformat())
        candidates.extend(snapshot["candidates"])
        months.append({
            "month": snapshot["month"],
            "matchedRows": snapshot["matchedRows"],
            "candidateCount": len(snapshot["candidates"]),
        })
    return candidates, months


def backup_before_write() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    archive = BACKUP_DIR / f"makeup-sheet-sync-{stamp}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for path in (ABS_PATH, CARRYOVER_PATH, CONFIG_PATH):
            if path.exists() and path.is_file():
                output.write(path, path.relative_to(ROOT).as_posix())
        output.writestr("MODE.txt", "additive-only\nmax-sheet-row=127\n")
    old_archives = sorted(BACKUP_DIR.glob("makeup-sheet-sync-*.zip"), key=lambda path: path.stat().st_mtime, reverse=True)
    for old in old_archives[BACKUP_KEEP:]:
        try:
            old.unlink()
        except OSError:
            pass
    return archive


def save_status(payload: dict) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(STATUS_PATH, timeout_sec=2.0):
        save_atomic(STATUS_PATH, payload)


def run(*, dry_run: bool = False, today: dt.date | None = None) -> dict:
    started_at = utc_now()
    config = load_config()
    if not config["enabled"]:
        return {
            "ok": True,
            "enabled": False,
            "mode": "additive-only",
            "startedAt": started_at,
            "finishedAt": utc_now(),
            "added": 0,
        }

    operating_date = today or dt.datetime.now(KST).date()
    candidates, months = collect_candidates(config["sheetUrl"], operating_date)
    candidates, excluded_candidates = partition_excluded_sheet_candidates(
        candidates,
        config.get("excludedCandidates"),
    )

    # Sheet/network work is complete before live-data locks are acquired.
    # Dry-run keeps the legacy mutation-free two-file read scope.
    if dry_run:
        with file_lock(CARRYOVER_PATH, timeout_sec=2.0):
            with file_lock(ABS_PATH, timeout_sec=2.0):
                current_carryover = load(CARRYOVER_PATH)
                current_absent = load_absent()
                merged = merge_additive_sheet_absences(
                    current_carryover if isinstance(current_carryover, dict) else {},
                    current_absent,
                    candidates,
                )
                backup_path = ""
    else:
        # The two-second timeout deliberately yields to an administrator saving in the UI.
        with absence_write_scope(
            absent_path=ABS_PATH,
            carryover_path=CARRYOVER_PATH,
            updates_path=UPD_PATH,
            progress_path=PRG_PATH,
            lock_timeout_sec=2.0,
        ) as journal_dir:
            current_carryover = load(CARRYOVER_PATH)
            current_absent = load_absent()
            merged = merge_additive_sheet_absences(
                current_carryover if isinstance(current_carryover, dict) else {},
                current_absent,
                candidates,
            )
            backup_path = ""
            if merged["added"]:
                backup_path = str(backup_before_write())
                new_pairs = {
                    (str(item.get("date") or ""), str(item.get("sid") or ""))
                    for item in merged.get("addedPairs") or []
                }
                commit_new_absences_locked(
                    new_pairs,
                    absent_after=merged["absent"],
                    carryover_after=merged["carryover"],
                    absent_path=ABS_PATH,
                    carryover_path=CARRYOVER_PATH,
                    updates_path=UPD_PATH,
                    progress_path=PRG_PATH,
                    journal_dir=journal_dir,
                    kind="makeup-sheet-offline",
                )

    result = {
        "ok": True,
        "enabled": True,
        "dryRun": dry_run,
        "mode": "additive-only",
        "startedAt": started_at,
        "finishedAt": utc_now(),
        "operatingDate": operating_date.isoformat(),
        "maxSheetRow": SHEET_SYNC_MAX_ROW,
        "months": months,
        "candidateCount": len(candidates),
        "excludedCount": len(excluded_candidates),
        "added": merged["added"],
        "addedSids": merged["addedSids"],
        "skippedExisting": merged["skippedExisting"],
        "protectedScheduled": merged["protectedScheduled"],
        "cancelled": 0,
        "attendanceRemoved": 0,
        "backup": backup_path,
    }
    if not dry_run:
        save_status(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Add only new sheet absences; never edit makeup reservations.")
    parser.add_argument("--dry-run", action="store_true", help="Read and compare without writing runtime data.")
    parser.add_argument("--date", help="Override KST operating date for verification (YYYY-MM-DD).")
    args = parser.parse_args()
    override_date = dt.date.fromisoformat(args.date) if args.date else None
    try:
        result = run(dry_run=args.dry_run, today=override_date)
    except Exception as exc:
        failure = {
            "ok": False,
            "mode": "additive-only",
            "finishedAt": utc_now(),
            "error": f"{type(exc).__name__}: {exc}",
        }
        if not args.dry_run:
            try:
                save_status(failure)
            except Exception:
                pass
        print(json.dumps(failure, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
