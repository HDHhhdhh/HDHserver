"""Read-only runtime adapter for focus eligibility and admin roster labels."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from .student_focus_rules import KST
from .student_schedule_projection import project_student_schedule


class FocusRuntimeSource:
    """Load existing JSON snapshots without importing side-effectful runtime paths."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _read(self, name: str, fallback: object) -> object:
        try:
            with (self.root / name).open("r", encoding="utf-8-sig") as stream:
                return json.load(stream)
        except (OSError, UnicodeError, json.JSONDecodeError):
            return fallback

    def roster(self) -> dict[str, dict[str, str]]:
        raw = self._read("students.json", [])
        if not isinstance(raw, list):
            return {}
        result: dict[str, dict[str, str]] = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            sid = item.get("id")
            if not isinstance(sid, str) or not sid.strip():
                continue
            result[sid.strip()] = {
                key: str(item.get(key) or "").strip()
                for key in ("name", "school", "grade")
            }
        return result

    def schedule(self, sid: str, now: float) -> list[dict[str, object]]:
        roster = self._read("students.json", [])
        students = roster if isinstance(roster, list) else []
        student = next(
            (item for item in students if isinstance(item, dict) and str(item.get("id") or "").strip() == sid),
            None,
        )
        if student is None:
            return []
        today = datetime.fromtimestamp(float(now), tz=KST).date()
        return project_student_schedule(
            student,
            sid=sid,
            start_date=today.isoformat(),
            end_date=(today + timedelta(days=1)).isoformat(),
            absence=self._read("absent.json", {}),
            extra=self._read("extra_attend.json", {}),
            weekend=self._read("weekend_slots.json", {}),
            makeup=self._read("makeup_carryover.json", {}),
        )


__all__ = ("FocusRuntimeSource",)
