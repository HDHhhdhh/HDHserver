"""Temporary-store HTTP and independent browser oracle for reservation history."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flask import Flask
from core.makeup_history import append_makeup_history
from core.makeup_sheet_sync import _normalize_carryover
from core.storage import save_atomic
import routes.api_makeup_carryover as route


def main():
    key = "absence|2026-10-01|s|1"
    schedule = {"originalAbsenceId": key, "studentId": "s", "makeupDate": "2026-10-04",
                "makeupTimes": [1], "status": "scheduled"}
    initial = {"by_absence": {"2026-10-01": {"s|1": {"state": "carried", "scheduledMakeup": schedule}}}, "manual": {}}
    with tempfile.TemporaryDirectory(prefix="verify-makeup-history-") as tmp:
        base = Path(tmp)
        data, absent = base / "makeup.json", base / "absent.json"
        data.write_text('{"by_absence":{},"manual":{}}', "utf-8")
        absent.write_text('{"by_date":{},"by_slot":{}}', "utf-8")

        def save(path, value):
            assert Path(path).resolve().is_relative_to(base.resolve())
            save_atomic(path, value, mirror=False)

        with patch.object(route, "MAKEUP_CARRYOVER_PATH", data), patch.object(route, "ABS_PATH", absent), \
             patch.object(route, "save_atomic", save), patch.object(route, "enqueue_current_schedule_changes", lambda _: None):
            app = Flask("makeup-history-temp")
            app.register_blueprint(route.bp_api_makeup_carryover)
            client = app.test_client()

            def post(payload):
                snapshot = client.get("/api/makeup-carryover")
                assert snapshot.headers["X-Makeup-History-Version"] == "1"
                revision = snapshot.headers["X-Makeup-Carryover-Revision"]
                response = client.post("/api/makeup-carryover", json=payload, headers={"If-Match": revision})
                assert response.status_code == 200, response.data
                assert response.get_json() == json.loads(data.read_text("utf-8"))
                return response.get_json()

            saved = post(initial)
            assert [e["action"] for e in saved["scheduleHistory"][key]] == ["scheduled"]
            assert saved["scheduleHistory"][key][0]["makeupDate"] == "2026-10-04"
            original_events = deepcopy(saved["scheduleHistory"])
            forged = deepcopy(saved)
            forged["scheduleHistory"] = {"forged": [{"action": "rescheduled"}]}
            forged["by_absence"]["2026-10-01"]["s|1"]["scheduledMakeup"]["updatedAt"] = "client-metadata"
            saved = post(forged)
            assert saved["scheduleHistory"] == original_events
            absent.write_text(json.dumps({"by_date": {"2026-10-04": ["s"]}, "by_slot": {"2026-10-04": {"s": [1]}}}), "utf-8")
            moved = deepcopy(saved)
            moved["by_absence"]["2026-10-01"]["s|1"]["scheduledMakeup"]["makeupDate"] = "2026-10-11"
            saved = post(moved)
            events = saved["scheduleHistory"][key]
            assert [e["action"] for e in events] == ["scheduled", "rescheduled"]
            assert [e["makeupDate"] for e in events] == ["2026-10-04", "2026-10-11"]
            assert events[0]["missedSlots"] == [1] and "missedSlots" not in events[1]
            assert all(e["recordedAt"] for e in events)
            assert post(saved)["scheduleHistory"] == saved["scheduleHistory"], "identical retry must not append"
            fingerprint = data.read_bytes()
            response = client.post("/api/makeup-carryover", json=initial, headers={"If-Match": "stale"})
            assert response.status_code == 409 and data.read_bytes() == fingerprint
            assert client.post("/api/makeup-carryover", json=initial).status_code == 428
            assert data.read_bytes() == fingerprint
            fixture = base / "roundtrip.json"
            fixture.write_text(json.dumps(saved, ensure_ascii=False), "utf-8")
            subprocess.run(["node", "scripts/verify_makeup_history.mjs", str(fixture)], cwd=ROOT, check=True)
            cancelled = post({"by_absence": {}, "manual": {}})
            assert [e["action"] for e in cancelled["scheduleHistory"][key]] == ["scheduled", "rescheduled", "cancelled"]
            assert post(cancelled)["scheduleHistory"] == cancelled["scheduleHistory"]
            restored = post(initial)
            assert restored["scheduleHistory"][key][-1]["action"] == "rescheduled"
            assert len(restored["scheduleHistory"][key]) == 4
            assert _normalize_carryover(restored)["scheduleHistory"] == restored["scheduleHistory"], "sheet sync retains history"

    legacy = append_makeup_history(initial, moved, recorded_at="now")
    assert legacy["scheduleHistory"][key][0]["legacy"] is True
    assert legacy["scheduleHistory"][key][-1]["action"] == "rescheduled"
    assert "missedSlots" not in legacy["scheduleHistory"][key][0], "moving before absence must not link future regular absence"
    manual = {"by_absence": {}, "manual": {"2026-10-01": {"m": {
        "sid": "s", "dateOnly": True, "scheduledMakeup": {**schedule, "originalAbsenceId": "forged-key"}}}}}
    first = append_makeup_history({}, manual, recorded_at="now")
    assert list(first["scheduleHistory"]) == ["manual|2026-10-01|m"]
    changed = deepcopy(first)
    changed["manual"]["2026-10-01"]["m"]["scheduledMakeup"]["makeupTimes"] = [2]
    second = append_makeup_history(first, changed, recorded_at="later")
    assert [e["action"] for e in second["scheduleHistory"]["manual|2026-10-01|m"]] == ["scheduled", "rescheduled"]
    ambiguous = deepcopy(initial)
    ambiguous["by_absence"]["2026-10-02"] = {"s|1": {"scheduledMakeup": deepcopy(schedule)}}
    cleared = append_makeup_history(ambiguous, {}, recorded_at="now", absent={"by_date": {"2026-10-04": ["s"]}})
    assert all("missedSlots" not in e for entries in cleared["scheduleHistory"].values() for e in entries)
    assert "scheduleHistory" not in initial, "pure transforms must not mutate input"
    note = "예정 정규수업 결석: 2026-10-01 1타임 / 직보 추가등원 예약으로 1회 차감: 2026-10-04 2타임 미적분1 (s). 실제 이행 완료 표시는 아님. [approved-fixture-20261001]"
    note_only = {"by_absence": {"2026-10-01": {"s|1": {"state": "carried", "note": note}}}, "manual": {}}
    note_moved = append_makeup_history(note_only, moved, recorded_at="now")
    assert [(e["action"], e["makeupDate"], e["makeupTimes"]) for e in note_moved["scheduleHistory"][key]] == [
        ("scheduled", "2026-10-04", [2]), ("rescheduled", "2026-10-11", [1]),
    ], "approved note reservation must supply the legacy baseline"
    for bad_note in (note + " / " + note, note.replace("2026-10-01 1타임", "2026-10-02 1타임"), note.replace("[approved-fixture-20261001]", "")):
        note_only["by_absence"]["2026-10-01"]["s|1"]["note"] = bad_note
        assert len(append_makeup_history(note_only, moved, recorded_at="now")["scheduleHistory"][key]) == 1
    note_only["by_absence"]["2026-10-01"]["s|1"].update(note=note, scheduledMakeup=None)
    assert len(append_makeup_history(note_only, moved, recorded_at="now")["scheduleHistory"][key]) == 1, "null tombstone must suppress legacy note"
    print("makeup history HTTP/persistence/retry/revision/manual/legacy/sheet checks: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
