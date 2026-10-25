"""Server-owned reservation history, keyed by the original absence row."""

from copy import deepcopy
import re


def _legacy_schedule(row, date, key, source):
    if "scheduledMakeup" in row or "scheduled_makeup" in row or source != "absence":
        return None
    if row.get("state") != "carried":
        return None
    parts = key.split("|")
    if len(parts) != 2 or parts[1] not in ("1", "2", "3"):
        return None
    note = str(row.get("note") or "")
    matches = list(re.finditer(
        r"직보[ \t]*추가등원[ \t]*예약으로[ \t]*1회[ \t]*차감:[ \t]*(\d{4}-\d{2}-\d{2})[ \t]*([123])타임[^\r\n()[\]]*\(([^()\r\n]+)\)\.[^\r\n]*?실제 이행 완료 표시는 아님\.[ \t]*\[approved-[a-z0-9-]+-\d{8}\]",
        note,
    ))
    if len(matches) != 1:
        return None
    match = matches[0]
    if not match[3].strip() or not re.search(
        rf"결석[^\r\n/]*{re.escape(date)}[ \t]*{parts[1]}[ \t]*타임[^\r\n/]*\/[ \t]*$", note[:match.start()],
    ):
        return None
    return {"studentId": parts[0], "makeupDate": match[1], "makeupTimes": [int(match[2])],
            "status": "scheduled", "updatedAt": row.get("updatedAt", ""), "_legacyNote": True}


def _schedules(payload):
    rows = {}
    for section, source in (("by_absence", "absence"), ("manual", "manual")):
        for date, day in payload.get(section, {}).items():
            for key, row in day.items():
                schedule = row.get("scheduledMakeup") or _legacy_schedule(row, date, key, source)
                if isinstance(schedule, dict) and schedule.get("makeupDate"):
                    rows[f"{source}|{date}|{key}"] = schedule
    return rows


def _signature(schedule):
    if not schedule:
        return None
    return (schedule.get("makeupDate"), tuple(schedule.get("makeupTimes", [])),
            schedule.get("status", "scheduled"))


def _event(schedule, action, recorded_at, *, legacy=False):
    event = {"action": action, "makeupDate": schedule["makeupDate"],
             "makeupTimes": list(schedule.get("makeupTimes", [])),
             "studentId": schedule["studentId"], "recordedAt": recorded_at}
    if legacy:
        event["legacy"] = True
    return event


def append_makeup_history(previous, requested, *, recorded_at, absent=None):
    """Ignore client history; append only committed schedule transitions under the caller's lock."""
    result = deepcopy(requested)
    history = deepcopy(previous.get("scheduleHistory", {}))
    before, after = _schedules(previous), _schedules(requested)
    absent = absent or {}
    claims = {}
    for schedule in before.values():
        if schedule.get("status") != "scheduled":
            continue
        for slot in schedule.get("makeupTimes", []):
            claim = (schedule["makeupDate"], schedule["studentId"], slot)
            claims[claim] = claims.get(claim, 0) + 1
    for key in sorted(before.keys() | after.keys()):
        old, new = before.get(key), after.get(key)
        if not old and new and new.get("_legacyNote"):
            continue
        if _signature(old) == _signature(new):
            continue
        events = history.setdefault(key, [])
        if old and not events:
            action = "scheduled" if old.get("status") == "scheduled" else old.get("status", "scheduled")
            events.append(_event(old, action, old.get("updatedAt", ""), legacy=True))
        if old and old.get("status") == "scheduled":
            date, sid = old["makeupDate"], old["studentId"]
            slots = absent.get("by_slot", {}).get(date, {}).get(sid, [])
            whole_day = sid in absent.get("by_date", {}).get(date, [])
            missed = [slot for slot in old.get("makeupTimes", [])
                      if (whole_day or slot in slots) and claims.get((date, sid, slot)) == 1]
            if missed:
                # Only a recorded absence at the outgoing reservation can join this chain.
                for event in reversed(events):
                    if event.get("action") in ("scheduled", "rescheduled"):
                        event["missedSlots"] = missed
                        break
        if new and new.get("status") == "scheduled":
            had_booking = any(e.get("action") in ("scheduled", "rescheduled") or e.get("legacy") for e in events)
            events.append(_event(new, "rescheduled" if had_booking else "scheduled", recorded_at))
        elif new:
            events.append(_event(new, new["status"], recorded_at))
        elif old and old.get("status") == "scheduled":
            events.append(_event(old, "cancelled", recorded_at))
    result.pop("scheduleHistory", None)
    if history:
        result["scheduleHistory"] = history
    return result
