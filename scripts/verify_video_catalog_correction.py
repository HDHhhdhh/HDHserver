from __future__ import annotations

import json
import sys
import tempfile
import zipfile
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.video_catalog_correction import (
    CorrectionValidationError,
    StaleCorrectionDraft,
    UnsafeVideoDeletion,
    apply_video_catalog_correction,
    build_correction_draft,
    validate_correction_draft,
)
from scripts import apply_video_catalog_correction as apply_tool
from scripts import backup_runtime_data


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _video(video_id: int, mid: str, title: str | None = None) -> dict:
    return {
        "id": video_id,
        "mid": mid,
        "title": title or mid,
        "curriculum": "미적분1",
        "subCurriculum": "A:Ble",
        "chapter": video_id,
        "url": f"https://v.kr.kollus.com/{mid}",
    }


def _fixture():
    base = [
        _video(1, "old-manual"),
        _video(2, "old-auto"),
        _video(3, "swap-a"),
        _video(4, "swap-b"),
        _video(5, "unused-delete"),
        _video(6, "keep"),
    ]
    target = [
        _video(1, "new-shared"),
        _video(2, "new-auto"),
        _video(3, "swap-b"),
        _video(4, "swap-a"),
        _video(6, "keep", "metadata changed"),
        _video(7, "brand-new"),
    ]
    updates = {
        "2026-08-23": {
            "s1": ["old-manual", "new-shared", "old-manual", "keep"],
            "s2": {
                "source": "manual",
                "videos": ["old-auto", "new-auto", "old-auto"],
                "unknown": {"keep": True},
            },
            "s3": ["swap-a", "swap-b"],
        }
    }
    progress = {
        "2026-08-23": {
            "s1": {
                "old-manual": "none",
                "new-shared": "done",
                "old-auto": "interrupted",
                "swap-a": "done",
                "swap-b": "skip",
                "tests": {"unit-1": "done"},
                "__manualProgressMids": {"old-manual": True},
                "__autoWatchProgressMids": {
                    "new-shared": "done",
                    "old-auto": "interrupted",
                    "swap-a": "done",
                    "swap-b": "skip",
                },
                "__allStudentsProgressMids": {"old-manual": True},
                "__unknownMeta": {"keep": "exact"},
            }
        }
    }
    watch = {
        "2026-08-23": {
            "s1": {
                "old-manual": {
                    "last": 95,
                    "dur": 100,
                    "completed": False,
                    "updatedAt": 100,
                    "sourceTag": "old",
                },
                "new-shared": {
                    "last": 50,
                    "dur": 120,
                    "completed": False,
                    "updatedAt": 200,
                    "targetTag": "new",
                },
                "old-auto": {"last": 20, "dur": 100, "completed": False, "updatedAt": 300},
                "swap-a": {"last": 90, "dur": 100, "updatedAt": 400},
                "swap-b": {"last": 10, "dur": 100, "updatedAt": 500},
            }
        }
    }
    return base, target, updates, progress, watch


def _verify_maintenance_sources() -> None:
    wrapper = (ROOT / "scripts" / "apply_video_catalog_correction.ps1").read_text(encoding="utf-8")
    apply_source = (ROOT / "scripts" / "apply_video_catalog_correction.py").read_text(encoding="utf-8")
    required_wrapper_tokens = (
        "if (-not $Apply)",
        "if (-not $ConfirmApply)",
        "Stop-ScheduledTask",
        "backup_runtime_data.py",
        "--backup-archive",
        "finally {",
        "Start-ScheduledTask",
        "Nothing was stopped or changed.",
        "$expectedWaitressPattern",
    )
    for token in required_wrapper_tokens:
        assert token in wrapper, f"maintenance wrapper is missing: {token}"
    assert "0\\.0\\.0\\.0:8003" not in wrapper
    dry_run = wrapper.index("Video correction dry-run")
    apply_gate = wrapper.index("if (-not $Apply)")
    confirm_gate = wrapper.index("if (-not $ConfirmApply)")
    stop = wrapper.index("Stop-ScheduledTask")
    backup = wrapper.index("$backupOutput")
    live_apply = wrapper.index("--apply --backup-archive")
    restart = wrapper.index("Start-ScheduledTask")
    assert dry_run < apply_gate < confirm_gate < stop < backup < live_apply < restart
    assert 'WRITE_ORDER = ("updates.json", "progress.json", "watch.json", "videos.json")' in apply_source
    assert "live apply requires --backup-archive" in apply_source
    assert "refusing live correction while port" in apply_source
    assert "readback verification failed" in apply_source

def main() -> int:
    _verify_maintenance_sources()
    base, target, updates, progress, watch = _fixture()
    originals = deepcopy((base, target, updates, progress, watch))
    draft = build_correction_draft(base, target, created_at="2026-08-23T13:00:00Z")
    validated = validate_correction_draft(json.loads(json.dumps(draft, ensure_ascii=False)))
    assert validated == draft

    result = apply_video_catalog_correction(
        current_videos=base,
        draft=draft,
        updates=updates,
        progress=progress,
        watch=watch,
    )
    report = result["report"]
    assert report["replacements"] == {
        "old-manual": "new-shared",
        "old-auto": "new-auto",
        "swap-a": "swap-b",
        "swap-b": "swap-a",
    }
    assert report["removedIds"] == ["5"]
    assert report["newIds"] == ["7"]
    assert report["referenceTotals"]["updates"] == 6
    assert report["referenceTotals"]["progressStatuses"] == 4
    assert report["referenceTotals"]["progressMetadata"] == 5
    assert report["referenceTotals"]["watch"] == 4

    next_updates = result["updates"]
    assert next_updates["2026-08-23"]["s1"] == ["new-shared", "keep"]
    assert next_updates["2026-08-23"]["s2"]["videos"] == ["new-auto"]
    assert next_updates["2026-08-23"]["s2"]["unknown"] == {"keep": True}
    assert next_updates["2026-08-23"]["s3"] == ["swap-b", "swap-a"]

    per_sid = result["progress"]["2026-08-23"]["s1"]
    assert per_sid["new-shared"] == "none"
    assert per_sid["new-auto"] == "interrupted"
    assert per_sid["swap-a"] == "skip" and per_sid["swap-b"] == "done"
    assert per_sid["tests"] == {"unit-1": "done"}
    assert per_sid["__unknownMeta"] == {"keep": "exact"}
    assert per_sid["__manualProgressMids"] == {"new-shared": True}
    assert per_sid["__allStudentsProgressMids"] == {"new-shared": True}
    assert per_sid["__autoWatchProgressMids"] == {
        "new-auto": "interrupted",
        "swap-a": "skip",
        "swap-b": "done",
    }

    next_watch = result["watch"]["2026-08-23"]["s1"]
    assert next_watch["new-shared"]["last"] == 95
    assert next_watch["new-shared"]["dur"] == 120
    assert next_watch["new-shared"]["completed"] is True
    assert next_watch["new-shared"]["updatedAt"] == 200
    assert next_watch["new-shared"]["sourceTag"] == "old"
    assert next_watch["new-shared"]["targetTag"] == "new"
    assert next_watch["swap-a"]["last"] == 10
    assert next_watch["swap-b"]["last"] == 90
    assert result["videos"] == target
    assert (base, target, updates, progress, watch) == originals

    referenced_delete = deepcopy(draft)
    referenced_updates = deepcopy(updates)
    referenced_updates["2026-08-23"]["s4"] = ["unused-delete"]
    try:
        apply_video_catalog_correction(
            current_videos=base,
            draft=referenced_delete,
            updates=referenced_updates,
            progress=progress,
            watch=watch,
        )
    except UnsafeVideoDeletion as exc:
        assert exc.references["unused-delete"]["updates"] == 1
    else:
        raise AssertionError("referenced video deletion must fail closed")

    stale_current = deepcopy(base)
    stale_current[0]["title"] = "changed after draft"
    try:
        apply_video_catalog_correction(
            current_videos=stale_current,
            draft=draft,
            updates=updates,
            progress=progress,
            watch=watch,
        )
    except StaleCorrectionDraft:
        pass
    else:
        raise AssertionError("stale correction draft must be rejected")

    reused_removed_mid = deepcopy(target)
    reused_removed_mid[-1]["mid"] = "unused-delete"
    reused_removed_mid[-1]["url"] = "https://v.kr.kollus.com/unused-delete"
    try:
        build_correction_draft(base, reused_removed_mid, created_at="2026-08-23T13:00:00Z")
    except CorrectionValidationError:
        pass
    else:
        raise AssertionError("a removed MID cannot be silently reused by a new row")

    duplicate_mid = deepcopy(target)
    duplicate_mid[-1]["mid"] = "keep"
    duplicate_mid[-1]["url"] = "https://v.kr.kollus.com/keep"
    try:
        build_correction_draft(base, duplicate_mid, created_at="2026-08-23T13:00:00Z")
    except CorrectionValidationError:
        pass
    else:
        raise AssertionError("duplicate target MIDs must be rejected")

    with tempfile.TemporaryDirectory(prefix="verify-video-correction-io-") as tmp:
        temp_root = Path(tmp)
        paths = {name: temp_root / name for name in apply_tool.STORE_NAMES}
        _write_json(paths["videos.json"], base)
        _write_json(paths["updates.json"], updates)
        _write_json(paths["progress.json"], progress)
        _write_json(paths["watch.json"], watch)
        draft_path = temp_root / "draft.json"
        _write_json(draft_path, draft)
        bytes_before = {name: path.read_bytes() for name, path in paths.items()}

        dry_report = apply_tool.run_correction(
            root=temp_root,
            draft_path=draft_path,
            apply=False,
        )
        assert dry_report["mode"] == "dry-run"
        assert {name: path.read_bytes() for name, path in paths.items()} == bytes_before

        original_backup_root = backup_runtime_data.ROOT
        try:
            backup_runtime_data.ROOT = temp_root
            archive = backup_runtime_data.make_backup(temp_root / "backups")
        finally:
            backup_runtime_data.ROOT = original_backup_root
        apply_tool.verify_backup_archive(archive, temp_root, paths)

        corrupt_archive = temp_root / "backups" / "corrupt-runtime-data.zip"
        with zipfile.ZipFile(archive, "r") as source_zip, zipfile.ZipFile(
            corrupt_archive, "w", compression=zipfile.ZIP_DEFLATED
        ) as target_zip:
            for info in source_zip.infolist():
                payload = source_zip.read(info.filename)
                if info.filename == "watch.json":
                    payload = b"{}"
                target_zip.writestr(info, payload)
        try:
            apply_tool.verify_backup_archive(corrupt_archive, temp_root, paths)
        except CorrectionValidationError as exc:
            assert "backup archive content hash is invalid for watch.json" in str(exc)
        else:
            raise AssertionError("corrupted backup contents must be rejected")

        apply_report = apply_tool.run_correction(
            root=temp_root,
            draft_path=draft_path,
            apply=True,
        )
        assert apply_report["mode"] == "apply"
        assert apply_report["changedFiles"] == list(apply_tool.WRITE_ORDER)
        assert _read_json(paths["videos.json"]) == target
        assert _read_json(paths["updates.json"]) == result["updates"]
        assert _read_json(paths["progress.json"]) == result["progress"]
        assert _read_json(paths["watch.json"]) == result["watch"]

        for name, value in {
            "videos.json": base,
            "updates.json": updates,
            "progress.json": progress,
            "watch.json": watch,
        }.items():
            _write_json(paths[name], value)
        failed_once = False

        def fail_catalog_once(path: Path, value) -> None:
            nonlocal failed_once
            if path.name == "videos.json" and not failed_once:
                failed_once = True
                raise OSError("synthetic catalog write failure")
            apply_tool._save_store(path, value)

        try:
            apply_tool.run_correction(
                root=temp_root,
                draft_path=draft_path,
                apply=True,
                save_store=fail_catalog_once,
            )
        except OSError as exc:
            assert "synthetic catalog write failure" in str(exc)
        else:
            raise AssertionError("partial correction failure must propagate after rollback")
        assert failed_once
        assert _read_json(paths["videos.json"]) == base
        assert _read_json(paths["updates.json"]) == updates
        assert _read_json(paths["progress.json"]) == progress
        assert _read_json(paths["watch.json"]) == watch

        for name, path in paths.items():
            path.write_bytes(bytes_before[name])
        apply_tool.verify_backup_archive(archive, temp_root, paths)
        mutated_watch = deepcopy(watch)
        mutated_watch["after-backup"] = {}
        _write_json(paths["watch.json"], mutated_watch)
        try:
            apply_tool.verify_backup_archive(archive, temp_root, paths)
        except CorrectionValidationError as exc:
            assert "backup hash is stale for watch.json" in str(exc)
        else:
            raise AssertionError("stale backup receipt must be rejected")

    print("video catalog correction rules passed: draft, migration, metadata, deletion, stale guard, rollback")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())