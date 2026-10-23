"""Read-only attendance evidence; day flags never imply a billable slot count."""
from __future__ import annotations

import calendar
import re
from datetime import date

from core.payment_rules import PaymentError
from core.makeup_payload_rules import normalize_makeup_schedule


def month_window(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}", value):
        raise PaymentError("invalid_month", "조회 월을 YYYY-MM 형식으로 선택해 주세요.")
    try:
        first = date.fromisoformat(value + "-01")
        last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
    except ValueError:
        raise PaymentError("invalid_month", "조회 월을 확인해 주세요.") from None
    return first.isoformat(), last.isoformat()


def project_evidence(sid, month, *, attendance, arrivals, absence, makeup, extra):
    first, last = month_window(month)
    for mapping in (attendance, arrivals, absence, makeup, extra):
        if not isinstance(mapping, dict):
            raise PaymentError("invalid_evidence", "출결 자료 형식을 확인해 주세요.", 503)
    for mapping, keys in ((absence, ("by_date", "by_student", "by_slot")), (makeup, ("by_absence", "manual"))):
        if any(key in mapping and not isinstance(mapping[key], dict) for key in keys):
            raise PaymentError("invalid_evidence", "결석·보강 자료 형식을 확인해 주세요.", 503)
    rows = []

    def add(day, kind, label, *, slot=None, source=None):
        if isinstance(day, str) and first <= day <= last:
            try:
                if date.fromisoformat(day).isoformat() != day:
                    return
            except ValueError:
                return
            rows.append({"date": day, "slot": slot, "kind": kind, "label": label,
                "source": source, "requiresConfirmation": True})

    def by_sid(mapping):
        for day, values in mapping.items():
            if first <= day <= last and isinstance(values, dict) and sid in values:
                yield day, values[sid]

    for day, flag in by_sid(attendance):
        if flag is True or type(flag) is int and flag == 1:
            add(day, "attendance", "출석 체크 · 수업 타임 확인 필요")
    for day, time in by_sid(arrivals):
        if isinstance(time, str) and time.strip():
            add(day, "arrival", f"등원 {time[:20]} · 수업 완료 확인 필요")
    by_date = absence.get("by_date", {})
    by_slot = absence.get("by_slot", {})
    days = {day for day, ids in by_date.items() if isinstance(ids, list) and sid in ids}
    legacy = absence.get("by_student", absence).get(sid)
    if isinstance(legacy, str):
        days.add(legacy)
    days.update(day for day, values in by_slot.items() if isinstance(values, dict) and sid in values)
    for day in sorted(days):
        slots = by_slot.get(day, {}).get(sid, [])
        valid = [slot for slot in slots if type(slot) is int and 1 <= slot <= 6] if isinstance(slots, list) else []
        for slot in valid or [None]:
            add(day, "absence", "결석 · 차감 없음", slot=slot)
    for day, ids in extra.items():
        if isinstance(ids, list) and sid in [str(value) for value in ids]:
            add(day, "extra", "추가 등원 예정 · 출석 확인 필요")
    for source_kind, mapping in (("absence", makeup.get("by_absence", makeup)), ("manual", makeup.get("manual", {}))):
        if not isinstance(mapping, dict):
            continue
        for original_date, values in mapping.items():
            if not isinstance(values, dict):
                continue
            for key, row in values.items():
                if not isinstance(row, dict):
                    continue
                owner = str(row.get("sid", "")) if source_kind == "manual" else str(key).split("|", 1)[0]
                raw_schedule = row.get("scheduledMakeup", row.get("scheduled_makeup"))
                schedule = normalize_makeup_schedule(raw_schedule,
                    fallback_student_id=owner, fallback_original_absence_id=f"{source_kind}|{original_date}|{key}")
                if not schedule or schedule["studentId"] != sid or schedule["status"] != "scheduled":
                    continue
                makeup_date = schedule["makeupDate"]
                slots = raw_schedule.get("makeupTimes") or raw_schedule.get("makeup_times") or raw_schedule.get("ownedSlots") or raw_schedule.get("owned_slots") or raw_schedule.get("slots") or raw_schedule.get("slot") or []
                if type(slots) is int:
                    slots = [slots]
                valid = [slot for slot in slots if type(slot) is int and 1 <= slot <= 6] if isinstance(slots, list) else []
                for slot in valid or [None]:
                    add(makeup_date, "makeup", f"보강 예약 · 원결석 {original_date}", slot=slot,
                        source={"date": original_date, "key": str(key), "kind": source_kind})
    return sorted(rows, key=lambda row: (row["date"], row["slot"] or 0, row["kind"]))
