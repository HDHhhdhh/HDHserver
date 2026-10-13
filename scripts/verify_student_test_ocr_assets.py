from __future__ import annotations

import datetime as dt
import tempfile
from pathlib import Path

from core.student_test_ocr_assets import OcrAssetError, purge_expired_assets, store_and_register_capture
from core.student_test_ocr_repository import StudentTestOcrRepository
from core.student_test_ocr_rules import ANSWER_VALUE, CHOICE_NUMBER


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "scripts" / "migrations" / "20260828_create_student_test_ocr.sql"
KST = dt.timezone(dt.timedelta(hours=9))


def _raises(code: str, callback) -> None:
    try:
        callback()
    except OcrAssetError as error:
        assert error.code == code, (error.code, code)
    else:
        raise AssertionError(f"expected {code}")


def run() -> dict:
    assertions = 0
    with tempfile.TemporaryDirectory(prefix="student-test-ocr-assets-") as temp_dir:
        temp_root = Path(temp_dir)
        repository = StudentTestOcrRepository(temp_root / "app.sqlite")
        repository.apply_migration(MIGRATION.read_text(encoding="utf-8"))
        repository.begin_submission(
            submission_id="sub-assets",
            idempotency_key="idem-assets",
            request_hash="hash-assets",
            sid="student-1",
            test_id="test-1",
            round_no="1",
            assignment_date="2026-08-28",
            answer_modes=[CHOICE_NUMBER, ANSWER_VALUE] * 10,
            now="2026-08-28T10:00:00+09:00",
        )
        asset_root = temp_root / "ocr-assets"
        created_at = dt.datetime(2026, 8, 28, 10, 0, 0, tzinfo=KST)
        jpeg = b"\xff\xd8\xff\xe0" + b"camera-capture" * 4
        stored = store_and_register_capture(
            repository,
            root=asset_root,
            asset_id="asset-full",
            submission_id="sub-assets",
            question_no=None,
            kind="full_sheet",
            content=jpeg,
            created_at=created_at,
        )
        stored_path = Path(stored["absolute_path"])
        assert stored_path.is_file() and stored_path.read_bytes() == jpeg
        assert stored["expires_at"] == "2026-09-04T10:00:00+09:00"
        assert str(stored_path).startswith(str(asset_root.resolve()))
        assertions += 3

        _raises(
            "unsupported_capture_format",
            lambda: store_and_register_capture(
                repository,
                root=asset_root,
                asset_id="asset-bad",
                submission_id="sub-assets",
                question_no=1,
                kind="student_crop",
                content=b"not-an-image" * 4,
                created_at=created_at,
            ),
        )
        _raises(
            "invalid_asset_question",
            lambda: store_and_register_capture(
                repository,
                root=asset_root,
                asset_id="asset-bad-question",
                submission_id="sub-assets",
                question_no=None,
                kind="student_crop",
                content=jpeg,
                created_at=created_at,
            ),
        )
        assertions += 2

        before = purge_expired_assets(
            repository,
            root=asset_root,
            now=dt.datetime(2026, 9, 4, 9, 59, 59, tzinfo=KST),
        )
        assert before == {"examined": 0, "deleted": (), "failed": ()} and stored_path.exists()
        assertions += 1

        expired = purge_expired_assets(
            repository,
            root=asset_root,
            now=dt.datetime(2026, 9, 4, 10, 0, 0, tzinfo=KST),
        )
        assert expired == {"examined": 1, "deleted": ("asset-full",), "failed": ()}
        assert not stored_path.exists()
        assert repository.expired_assets(now="2026-09-05T10:00:00+09:00") == []
        assertions += 3

    return {"name": "student-test-ocr-assets", "assertions": assertions, "passed": True}


if __name__ == "__main__":
    result = run()
    print(f"{result['name']} passed: {result['assertions']} assertions")
