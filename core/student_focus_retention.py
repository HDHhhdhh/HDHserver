"""Bounded retention mixin for student focus storage."""

from __future__ import annotations

from contextlib import closing

from .student_focus_rules import FocusInputError, STALE_GRACE_SECONDS


class StudentFocusRetentionMixin:
    def _close_stale(self, db, row, focus_id: str, sid: str, seq: int, current: float) -> dict:
        unknown_ms, ended = self._unknown_values(row, current)
        delta = self._delta_ms(row, current)
        db.execute(
            "INSERT INTO student_focus_events(session_id,seq,event_type,server_at,duration_ms) VALUES(?,?,?,?,?)",
            (focus_id, seq, "unknown", current, delta),
        )
        db.execute(
            "UPDATE student_focus_sessions SET state='unknown',visibility_state='unknown',ended_at=?,"
            "last_event_at=?,last_seq=?,event_count=event_count+1,unknown_ms=?,updated_at=? WHERE id=?",
            (ended, current, seq, unknown_ms, current, focus_id),
        )
        result = self._row(db, focus_id, sid)
        db.execute("COMMIT")
        return dict(result)

    def cleanup(self, *, now=None, raw_before: float, limit: int = 500) -> dict[str, int]:
        current = self._now(now)
        if type(limit) is not int or not 1 <= limit <= 5_000 or raw_before < 0:
            raise FocusInputError(message="focus cleanup bounds are invalid")
        with closing(self._connect(readonly=False)) as db:
            db.execute("BEGIN IMMEDIATE")
            stale = db.execute(
                "SELECT * FROM student_focus_sessions WHERE state='active' AND schedule_end_at+?<=? "
                "ORDER BY schedule_end_at LIMIT ?",
                (STALE_GRACE_SECONDS, current, limit),
            ).fetchall()
            for row in stale:
                unknown_ms, ended = self._unknown_values(row, current)
                db.execute(
                    "UPDATE student_focus_sessions SET state='unknown',visibility_state='unknown',unknown_ms=?,"
                    "ended_at=?,updated_at=? WHERE id=?",
                    (unknown_ms, ended, current, row["id"]),
                )
            raw = db.execute(
                "SELECT session_id,seq FROM student_focus_events WHERE server_at<? "
                "ORDER BY server_at,session_id,seq LIMIT ?",
                (float(raw_before), limit),
            ).fetchall()
            db.executemany(
                "DELETE FROM student_focus_events WHERE session_id=? AND seq=?",
                [(row[0], row[1]) for row in raw],
            )
            db.execute("COMMIT")
        return {"markedUnknown": len(stale), "eventsDeleted": len(raw)}


__all__ = ("StudentFocusRetentionMixin",)
