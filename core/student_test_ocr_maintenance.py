from __future__ import annotations

import copy
import datetime as dt
import math
import threading
from pathlib import Path
from typing import Callable

from core import student_test_ocr_assets as assets
from core.student_test_ocr_repository import StudentTestOcrRepository


KST = dt.timezone(dt.timedelta(hours=9))
REPORT_SCHEMA = "student_test_ocr_maintenance_v1"


class StudentTestOcrMaintenance:
    """Opt-in, model-independent retention and overdue-review checks."""

    def __init__(
        self,
        repository: StudentTestOcrRepository,
        asset_root: Path,
        clock: Callable[[], dt.datetime],
        interval_seconds: float = 300,
        page_size: int = 100,
        maximum_pages: int = 20,
    ):
        if (isinstance(interval_seconds, bool) or not isinstance(interval_seconds, (int, float))
                or not math.isfinite(interval_seconds) or not 0 < interval_seconds <= 86400):
            raise ValueError("invalid OCR maintenance interval")
        if type(page_size) is not int or not 1 <= page_size <= 500:
            raise ValueError("invalid OCR maintenance page size")
        if type(maximum_pages) is not int or not 1 <= maximum_pages <= 100:
            raise ValueError("invalid OCR maintenance page bound")
        self.repository = repository
        self.asset_root = Path(asset_root).absolute()
        self.clock = clock
        self.interval_seconds = float(interval_seconds)
        self.page_size = page_size
        self.maximum_pages = maximum_pages
        self._condition = threading.Condition()
        self._tick_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._closed = False
        self._running = False
        self._tick_owner: int | None = None
        self._retention_cursor = ""
        self._latest = self._report(None)
        self._latest["status"] = "not_started"

    @staticmethod
    def _report(now: dt.datetime | None) -> dict:
        return {
            "schema": REPORT_SCHEMA,
            "status": "ok",
            "executionEnabled": False,
            "checkedAt": now.isoformat(timespec="seconds") if now is not None else None,
            "retention": {
                "examined": 0, "deletedCount": 0, "failedCount": 0, "busyCount": 0,
                "pages": 0, "partial": False,
            },
            "overdue": {
                "beforeDate": now.date().isoformat() if now is not None else None,
                "submissions": [], "returnedSubmissionCount": 0, "returnedQuestionCount": 0,
                "returnedExpiredCropCount": 0, "pages": 0, "partial": False,
            },
            "errorCodes": [],
        }

    def _closed_now(self) -> bool:
        with self._condition:
            return self._closed

    def _now(self) -> dt.datetime:
        now = self.clock()
        if not isinstance(now, dt.datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("invalid OCR maintenance clock")
        return now.astimezone(KST)

    def _retention(self, now: dt.datetime, report: dict) -> None:
        summary = report["retention"]
        for _ in range(self.maximum_pages):
            if self._closed_now():
                summary["partial"] = True
                return
            page = assets.purge_expired_asset_page(
                self.repository, root=self.asset_root, now=now,
                limit=self.page_size, after_id=self._retention_cursor,
            )
            examined = page["examined"]
            last_id = page["lastId"]
            if (type(examined) is not int or not 0 <= examined <= self.page_size
                    or (examined and (not isinstance(last_id, str) or not last_id
                                     or last_id <= self._retention_cursor))):
                raise ValueError("invalid OCR retention page")
            summary["pages"] += 1
            summary["examined"] += examined
            for source, target in (("deleted", "deletedCount"), ("failed", "failedCount"), ("busy", "busyCount")):
                values = page[source]
                if not isinstance(values, (tuple, list)) or len(values) > examined:
                    raise ValueError("invalid OCR retention result")
                summary[target] += len(values)
            self._retention_cursor = last_id if examined else ""
            if examined < self.page_size:
                self._retention_cursor = ""
                summary["partial"] = bool(summary["failedCount"] or summary["busyCount"])
                return
        # Continue at the next key on the next tick, including when earlier rows failed.
        summary["partial"] = True

    def _overdue(self, now: dt.datetime, report: dict, *, stop_when_closed: bool = True) -> None:
        summary = report["overdue"]
        cursor = ""
        for _ in range(self.maximum_pages):
            if stop_when_closed and self._closed_now():
                summary["partial"] = True
                return
            rows = self.repository.list_overdue_pending(
                before_date=summary["beforeDate"], now=now.isoformat(timespec="seconds"),
                limit=self.page_size, after_id=cursor,
            )
            if not isinstance(rows, list) or len(rows) > self.page_size:
                raise ValueError("invalid OCR overdue page")
            summary["pages"] += 1
            for row in rows:
                row_id = row["id"]
                numbers = row["pendingQuestionNos"]
                expired = row["expiredCropCount"]
                if (not isinstance(row_id, str) or not row_id or row_id <= cursor
                        or not isinstance(numbers, list) or not numbers
                        or any(type(number) is not int or not 1 <= number <= 20 for number in numbers)
                        or len(set(numbers)) != len(numbers)
                        or type(expired) is not int or not 0 <= expired <= len(numbers)):
                    raise ValueError("invalid OCR overdue projection")
                cursor = row_id
                # Explicit allowlist excludes answer text, keys and filesystem paths.
                summary["submissions"].append({
                    "submissionId": row_id, "sid": row["sid"], "testId": row["test_id"],
                    "round": row["round_no"], "assignmentDate": row["assignment_date"],
                    "pendingQuestionNos": list(numbers), "expiredCropCount": expired,
                })
                summary["returnedSubmissionCount"] += 1
                summary["returnedQuestionCount"] += len(numbers)
                summary["returnedExpiredCropCount"] += expired
            if len(rows) < self.page_size:
                return
        # Returned counts describe this bounded list, never all outstanding work.
        summary["partial"] = True

    def run_once(self) -> dict:
        if not self._tick_lock.acquire(blocking=False):
            result = self.snapshot()
            result["status"] = "busy"
            return result
        try:
            with self._condition:
                if self._closed:
                    result = copy.deepcopy(self._latest)
                    result["status"] = "closed"
                    return result
                self._running = True
                self._tick_owner = threading.get_ident()
            report = self._report(None)
            report["executionEnabled"] = True
            try:
                now = self._now()
                report = self._report(now)
                report["executionEnabled"] = True
            except Exception:
                report["status"] = "error"
                report["errorCodes"].append("invalid_clock")
                report["retention"]["partial"] = True
                report["overdue"]["partial"] = True
            else:
                for action, code, section in (
                    (self._retention, "asset_retention_failed", "retention"),
                    (self._overdue, "overdue_review_failed", "overdue"),
                ):
                    try:
                        action(now, report)
                    except Exception:
                        report["errorCodes"].append(code)
                        report[section]["partial"] = True
                if report["retention"]["failedCount"]:
                    report["errorCodes"].append("asset_delete_failed")
                if report["errorCodes"]:
                    report["status"] = "error"
                elif report["retention"]["partial"] or report["overdue"]["partial"]:
                    report["status"] = "partial"
            with self._condition:
                self._latest = copy.deepcopy(report)
            return report
        finally:
            with self._condition:
                self._running = False
                self._tick_owner = None
                self._condition.notify_all()
            self._tick_lock.release()

    def inspect(self) -> dict:
        """Return current overdue evidence without starting or mutating maintenance."""
        report = self._report(None)
        try:
            now = self._now()
            report = self._report(now)
        except Exception:
            report["status"] = "error"
            report["errorCodes"].append("invalid_clock")
            report["overdue"]["partial"] = True
            return report
        try:
            self._overdue(now, report, stop_when_closed=False)
        except Exception:
            report["status"] = "error"
            report["errorCodes"].append("overdue_review_failed")
            report["overdue"]["partial"] = True
        else:
            if report["overdue"]["partial"]:
                report["status"] = "partial"
        return report

    def snapshot(self) -> dict:
        with self._condition:
            return copy.deepcopy(self._latest)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.run_once()
            if self._stop.wait(self.interval_seconds):
                return

    def start(self) -> None:
        with self._condition:
            if self._closed or self._thread is not None:
                return
            thread = threading.Thread(target=self._loop, daemon=True, name="student-test-ocr-maintenance")
            self._thread = thread
            try:
                thread.start()
            except Exception:
                self._thread = None
                raise

    def shutdown(self) -> None:
        with self._condition:
            self._closed = True
            self._stop.set()
            thread = self._thread
            while self._running and self._tick_owner != threading.get_ident():
                self._condition.wait()
        if thread is not None and thread is not threading.current_thread():
            thread.join()
