from __future__ import annotations

import datetime as dt
import random
import re
import time
import os
import json
import sqlite3
from urllib.parse import parse_qs, urlparse
from typing import List, Optional, Tuple, Dict, Any

from flask import Blueprint, abort, jsonify, request

from core.paths import (
    STU_PATH, VID_PATH, PRG_PATH, UPD_PATH, ASN_PATH, MAT_PATH, CAL_PATH,
    EXTRA_PATH, LOGS_PATH, CLINIC_PATH, TODAY_ORDER_PATH, WEEKEND_SLOTS_PATH,
    WATCH_PATH,
)
from core.storage import load, save_atomic, nocache_resp
from core.absent import load_absent, save_absent, DATE_RE

bp_api_basic = Blueprint("api_basic", __name__)

CT = {"Content-Type": "application/json"}
STUDENT_COURSE_BLOCK_MESSAGE = "수업일이 아닌 것 같습니다. 선생님께 문의주세용 ^_^"

# ─────────────────────────────────────────────
# 공통 CRUD
# ─────────────────────────────────────────────
def crud(path):
    if request.method == "GET":
        return jsonify(load(path))
    obj = request.get_json(force=True)
    save_atomic(path, obj)
    return "", 204


def _load_progress_strict() -> dict:
    try:
        data = json.loads(PRG_PATH.read_text("utf-8-sig"))
    except FileNotFoundError:
        return {}
    except Exception as e:
        raise RuntimeError(f"progress.json read failed: {e}") from e

    if not isinstance(data, dict):
        raise RuntimeError("progress.json must be an object")
    return data


def _student_has_schedule_on_date(student: dict, date_key: str) -> bool:
    try:
        target = dt.date.fromisoformat(date_key)
    except ValueError:
        return False
    wchr = "월화수목금토일"[target.weekday()]
    for key, value in (student or {}).items():
        if re.fullmatch(r"day\d+", str(key)) and str(value or "").startswith(wchr):
            return True
    return False


def _student_is_registered_on_date(student: dict, sid: str, date_key: str) -> bool:
    if _student_has_schedule_on_date(student, date_key):
        return True
    try:
        extra = load(EXTRA_PATH) or {}
    except Exception:
        extra = {}
    extra_ids = extra.get(date_key, []) if isinstance(extra, dict) else []
    return str(sid) in {str(x) for x in (extra_ids or [])}


def _extract_kollus_mid_from_url(url) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""

    try:
        parsed = urlparse(raw)
    except Exception:
        return ""

    host = (parsed.netloc or "").lower()
    if "kollus.com" not in host:
        return ""

    query = parse_qs(parsed.query or "", keep_blank_values=False)
    for key in ("mid", "m", "media_content_key", "MEDIA_CONTENT_KEY", "content_key"):
        vals = query.get(key)
        if not vals:
            continue
        cand = str(vals[0] or "").strip()
        if re.fullmatch(r"[A-Za-z0-9_-]+", cand):
            return cand

    parts = [p for p in (parsed.path or "").split("/") if p]
    for cand in reversed(parts):
        cand_s = str(cand or "").strip()
        if re.fullmatch(r"[A-Za-z0-9_-]+", cand_s):
            return cand_s

    return ""


def _normalize_video_mid_fields(videos):
    if not isinstance(videos, list):
        return videos

    out = []
    for item in videos:
        if not isinstance(item, dict):
            out.append(item)
            continue

        vid = dict(item)
        parsed_mid = _extract_kollus_mid_from_url(vid.get("url"))
        if parsed_mid:
            vid["mid"] = parsed_mid
        elif vid.get("mid") is not None:
            vid["mid"] = str(vid.get("mid") or "").strip()
        out.append(vid)
    return out


def _progress_status_rank(status: str) -> int:
    s = str(status or "").strip()
    if s == "done":
        return 3
    if s == "interrupted":
        return 2
    if s == "skip":
        return 1
    return 0


def _merge_progress_status(existing: str, incoming: str) -> str:
    a = str(existing or "").strip()
    b = str(incoming or "").strip()
    return a if _progress_status_rank(a) >= _progress_status_rank(b) else b


def _normalize_watch_entry_for_mid_migration(entry) -> dict:
    if not isinstance(entry, dict):
        entry = {}

    try:
        last = max(0, int(float(entry.get("last", 0) or 0)))
    except Exception:
        last = 0
    try:
        dur = max(0, int(float(entry.get("dur", 0) or 0)))
    except Exception:
        dur = 0
    try:
        updated_at = int(entry.get("updatedAt") or 0)
    except Exception:
        updated_at = 0

    completed = bool(entry.get("completed", False))
    if dur > 0 and (last / dur) >= 0.90:
        completed = True

    return {
        "last": last,
        "dur": dur,
        "completed": completed,
        "updatedAt": updated_at,
    }


def _merge_watch_entries_for_mid_migration(prev, incoming) -> dict:
    a = _normalize_watch_entry_for_mid_migration(prev)
    b = _normalize_watch_entry_for_mid_migration(incoming)

    last = max(a["last"], b["last"])
    dur = max(a["dur"], b["dur"])
    completed = a["completed"] or b["completed"]
    if dur > 0 and (last / dur) >= 0.90:
        completed = True

    return {
        "last": last,
        "dur": dur,
        "completed": completed,
        "updatedAt": max(a["updatedAt"], b["updatedAt"]),
    }


def _replace_mid_in_updates(data, old_mid: str, new_mid: str) -> bool:
    changed = False
    for by_day in (data.values() if isinstance(data, dict) else []):
        if not isinstance(by_day, dict):
            continue
        for sid, raw in list(by_day.items()):
            if isinstance(raw, list):
                next_raw = [new_mid if str(x) == old_mid else x for x in raw]
                if next_raw != raw:
                    by_day[sid] = next_raw
                    changed = True
            elif isinstance(raw, dict) and isinstance(raw.get("videos"), list):
                videos = raw.get("videos") or []
                next_videos = [new_mid if str(x) == old_mid else x for x in videos]
                if next_videos != videos:
                    next_raw = dict(raw)
                    next_raw["videos"] = next_videos
                    by_day[sid] = next_raw
                    changed = True
    return changed


def _replace_mid_in_progress(data, old_mid: str, new_mid: str) -> bool:
    changed = False
    for by_day in (data.values() if isinstance(data, dict) else []):
        if not isinstance(by_day, dict):
            continue
        for sid, per_sid in list(by_day.items()):
            if not isinstance(per_sid, dict) or old_mid not in per_sid:
                continue
            old_status = str(per_sid.pop(old_mid) or "").strip()
            new_status = _merge_progress_status(per_sid.get(new_mid), old_status)
            if new_status:
                per_sid[new_mid] = new_status
            changed = True
            if not per_sid:
                by_day.pop(sid, None)
    return changed


def _replace_mid_in_watch(data, old_mid: str, new_mid: str) -> bool:
    changed = False
    for by_day in (data.values() if isinstance(data, dict) else []):
        if not isinstance(by_day, dict):
            continue
        for sid, per_sid in list(by_day.items()):
            if not isinstance(per_sid, dict) or old_mid not in per_sid:
                continue
            old_entry = per_sid.pop(old_mid)
            per_sid[new_mid] = _merge_watch_entries_for_mid_migration(per_sid.get(new_mid), old_entry)
            changed = True
            if not per_sid:
                by_day.pop(sid, None)
    return changed


def _migrate_video_mid_references(prev_videos, next_videos):
    prev_map = {}
    for item in (prev_videos or []):
        if not isinstance(item, dict):
            continue
        key = str(item.get("id") or "").strip()
        if key:
            prev_map[key] = item

    replacements = []
    for item in (next_videos or []):
        if not isinstance(item, dict):
            continue
        key = str(item.get("id") or "").strip()
        if not key or key not in prev_map:
            continue

        old_mid = str(prev_map[key].get("mid") or "").strip()
        new_mid = str(item.get("mid") or "").strip()
        if old_mid and new_mid and old_mid != new_mid:
            replacements.append((old_mid, new_mid))

    if not replacements:
        return

    updates = load(UPD_PATH) or {}
    progress = _load_progress_strict()
    watch = load(WATCH_PATH) or {}

    updates_changed = False
    progress_changed = False
    watch_changed = False

    for old_mid, new_mid in replacements:
        updates_changed = _replace_mid_in_updates(updates, old_mid, new_mid) or updates_changed
        progress_changed = _replace_mid_in_progress(progress, old_mid, new_mid) or progress_changed
        watch_changed = _replace_mid_in_watch(watch, old_mid, new_mid) or watch_changed

    if updates_changed:
        save_atomic(UPD_PATH, updates)
    if progress_changed:
        save_atomic(PRG_PATH, progress)
    if watch_changed:
        save_atomic(WATCH_PATH, watch)


# ─────────────────────────────────────────────
# ✅ 프로세스 간 파일 락 (JSON 저장 보호용)
# ─────────────────────────────────────────────
class _InterProcessFileLock:
    def __init__(
        self,
        lock_path: str,
        timeout_sec: float = 4.0,
        poll_sec: float = 0.05,
        stale_sec: float = 30.0,
    ):
        self.lock_path = lock_path
        self.timeout_sec = timeout_sec
        self.poll_sec = poll_sec
        self.stale_sec = stale_sec
        self._fd = None

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
        except Exception:
            return False

    def _try_break_stale_lock(self):
        try:
            st = os.stat(self.lock_path)
        except FileNotFoundError:
            return
        except Exception:
            return

        age = time.time() - float(st.st_mtime)
        if age < self.stale_sec:
            return

        pid = None
        try:
            with open(self.lock_path, "r", encoding="utf-8", errors="ignore") as f:
                txt = f.read()
            m = re.search(r"\bpid=(\d+)\b", txt)
            if m:
                pid = int(m.group(1))
        except Exception:
            pid = None

        # If owner pid is known and still alive, don't break lock even if old.
        if pid is not None and self._pid_alive(pid):
            return

        try:
            os.remove(self.lock_path)
        except FileNotFoundError:
            pass
        except Exception:
            pass

    def acquire(self):
        deadline = time.time() + self.timeout_sec
        while True:
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
                self._fd = fd
                os.write(fd, f"pid={os.getpid()} time={time.time()}".encode("utf-8"))
                return
            except FileExistsError:
                self._try_break_stale_lock()
                if time.time() > deadline:
                    raise TimeoutError(f"lock timeout: {self.lock_path}")
                time.sleep(self.poll_sec)

    def release(self):
        try:
            if self._fd is not None:
                try:
                    os.close(self._fd)
                except Exception:
                    pass
            self._fd = None
            try:
                os.remove(self.lock_path)
            except FileNotFoundError:
                pass
        except Exception:
            pass

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_):
        self.release()


def _logs_lock():
    lp = str(getattr(LOGS_PATH, "__fspath__", lambda: str(LOGS_PATH))())
    return _InterProcessFileLock(lp + ".lock", timeout_sec=8.0, poll_sec=0.05, stale_sec=30.0)


def _progress_lock():
    pp = str(getattr(PRG_PATH, "__fspath__", lambda: str(PRG_PATH))())
    return _InterProcessFileLock(pp + ".lock", timeout_sec=8.0, poll_sec=0.05, stale_sec=30.0)


def _updates_lock():
    up = str(getattr(UPD_PATH, "__fspath__", lambda: str(UPD_PATH))())
    return _InterProcessFileLock(up + ".lock", timeout_sec=8.0, poll_sec=0.05, stale_sec=30.0)


def _sid_lookup(mapping: dict, sid: str):
    if not isinstance(mapping, dict):
        return None
    keys = [str(sid or "").strip()]
    if keys[0].isdigit():
        alt = str(int(keys[0]))
        if alt not in keys:
            keys.append(alt)
    for key in keys:
        if key and key in mapping:
            return mapping.get(key)
    return None


def _write_sid_mapping(mapping: dict, sid: str, value) -> None:
    key = str(sid or "").strip()
    if not key:
        return
    num_key = str(int(key)) if key.isdigit() else None
    if num_key and num_key != key:
        mapping.pop(num_key, None)
    if value is None:
        mapping.pop(key, None)
    else:
        mapping[key] = value


def _normalize_video_assign_list(value) -> list[str]:
    if isinstance(value, dict):
        value = value.get("videos")
    if not isinstance(value, list):
        return []
    out = []
    seen = set()
    for item in value:
        mid = str(item or "").strip()
        if not mid or mid in seen:
            continue
        out.append(mid)
        seen.add(mid)
    return out


def _merge_update_assignment(current, incoming):
    if incoming is None:
        return current

    videos = _normalize_video_assign_list(incoming)
    if isinstance(incoming, list):
        return videos

    if isinstance(incoming, dict):
        if incoming.get("remove") is True:
            return None
        out = dict(current) if isinstance(current, dict) else {}
        for key, value in incoming.items():
            if key in ("remove",):
                continue
            if key == "videos":
                out["videos"] = videos
            elif value is not None:
                out[str(key)] = value
        if "videos" not in incoming and videos:
            out["videos"] = videos
        return out if out else (videos if videos else current)

    return current


def _merge_updates_payload(current, incoming):
    if not isinstance(current, dict):
        current = {}
    if not isinstance(incoming, dict):
        return current

    out = dict(current)
    for date, by_sid in incoming.items():
        date_s = str(date or "").strip()
        if not DATE_RE.match(date_s) or not isinstance(by_sid, dict):
            continue

        day = out.setdefault(date_s, {})
        if not isinstance(day, dict):
            out[date_s] = {}
            day = out[date_s]

        for sid, value in by_sid.items():
            sid_s = str(sid or "").strip()
            if not sid_s:
                continue
            merged = _merge_update_assignment(_sid_lookup(day, sid_s), value)
            _write_sid_mapping(day, sid_s, merged)

        if not day:
            out.pop(date_s, None)
    return out


def _assigned_material_list(value) -> list[str]:
    if isinstance(value, dict):
        value = value.get("materials")
    if not isinstance(value, list):
        return []
    out = []
    seen = set()
    for item in value:
        if isinstance(item, dict):
            item = item.get("id") or item.get("url") or item.get("path")
        key = str(item or "").strip()
        if not key or key in seen:
            continue
        out.append(key)
        seen.add(key)
    return out


def _filter_materials_for_assignment(materials, assigned):
    if not isinstance(materials, dict):
        return {}
    wanted = {str(x) for x in (assigned or []) if str(x or "").strip()}
    if not wanted:
        return {}

    out = {}
    for key, value in materials.items():
        item = value if isinstance(value, dict) else {}
        candidates = {
            str(key),
            str(item.get("id") or ""),
            str(item.get("mid") or ""),
            str(item.get("url") or ""),
            str(item.get("path") or ""),
        }
        if candidates & wanted:
            out[key] = value
    return out


# ─────────────────────────────────────────────
# ✅ logs 안전 merge (날아감 방지)
# - PATCH가 기본
# - "빈 값"으로 기존 "유효 값" 덮는 거 금지
# - "__clear": ["notes", ...] 로 명시 삭제
# - done=true 는 저장/수정으로 false로 풀리지 않게(명시 해제 기능 없으면 고정)
# ─────────────────────────────────────────────
def _is_empty_value(v) -> bool:
    if v is None:
        return True
    if isinstance(v, str) and v.strip() == "":
        return True
    if isinstance(v, list) and len(v) == 0:
        return True
    if isinstance(v, dict) and len(v) == 0:
        return True
    return False


def _truthy(v) -> bool:
    return v is True or v == 1 or v == "1" or v == "true"


def _is_question_placeholder(value) -> bool:
    text = re.sub(r"\s+", "", str(value or ""))
    return len(text) >= 2 and set(text) == {"?"}


def _looks_corrupted_placeholder_text(value) -> bool:
    text = str(value or "").strip()
    if text.count("?") < 2:
        return False
    # If any real Korean/CJK/Latin text remains, keep it. This avoids
    # stripping legitimate notes such as "확인??" while hiding mojibake.
    return re.search(r"[A-Za-z가-힣一-龥]", text) is None


def _clean_placeholder_text(value) -> str:
    text = str(value or "").strip()
    return "" if _is_question_placeholder(text) or _looks_corrupted_placeholder_text(text) else text


def _student_homework_books(sid: str) -> List[str]:
    try:
        students = load(STU_PATH) or []
    except Exception:
        students = []
    if not isinstance(students, list):
        return []

    sid_s = str(sid or "").strip()
    stu = next(
        (s for s in students if isinstance(s, dict) and str(s.get("id") or "").strip() == sid_s),
        None,
    )
    if not stu:
        return []

    books: List[str] = []
    for key in sorted(stu.keys(), key=lambda k: int(k[7:]) if re.match(r"^subBook\d+$", str(k)) else 999):
        if not re.match(r"^subBook\d+$", str(key)):
            continue
        val = str(stu.get(key) or "").strip()
        if val and val not in books:
            books.append(val)
    return books


def _book_key(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip()).lower()


def _hw_row_summary(row: dict) -> str:
    if not isinstance(row, dict) or row.get("_deleted"):
        return ""

    book = str(row.get("book") or "").strip()
    this_hw = str(row.get("this") or "").strip()
    pct = row.get("pct")
    pct_s = "" if pct in ("", None) else f"{str(pct).strip()}%"
    comment = str(row.get("comment") or "").strip()
    next_hw = str(row.get("next") or "").strip()

    parts: List[str] = []
    if book:
        parts.append(f"[{book}]")
    if this_hw:
        parts.append(this_hw)
    if pct_s:
        parts.append(pct_s)
    if comment:
        parts.append(f"({comment})")
    if next_hw:
        parts.append(f"→ {next_hw}")
    return " ".join(parts).strip()


def _repair_homework_rows(rows, sid: str) -> tuple[list, bool]:
    if not isinstance(rows, list):
        return [], False

    books = _student_homework_books(sid)
    used = {
        _book_key(row.get("book"))
        for row in rows
        if isinstance(row, dict) and not _is_question_placeholder(row.get("book"))
    }
    used.discard("")

    out: List[dict] = []
    changed = False

    for row in rows:
        if not isinstance(row, dict):
            changed = True
            continue

        next_row = dict(row)

        raw_book = str(next_row.get("book") or "").strip()
        if _is_question_placeholder(raw_book):
            replacement = next((b for b in books if _book_key(b) not in used), "")
            next_row["book"] = replacement
            if replacement:
                used.add(_book_key(replacement))
            changed = True
        elif raw_book:
            used.add(_book_key(raw_book))

        for field in ("this", "comment", "next"):
            if field in next_row:
                cleaned = _clean_placeholder_text(next_row.get(field))
                if cleaned != str(next_row.get(field) or "").strip():
                    next_row[field] = cleaned
                    changed = True

        out.append(next_row)

    return out, changed


def _repair_log_entry_placeholders(entry: dict, sid: str) -> dict:
    if not isinstance(entry, dict):
        return {}

    out = dict(entry)

    if "notes" in out:
        cleaned_notes = _clean_placeholder_text(out.get("notes"))
        if cleaned_notes:
            out["notes"] = cleaned_notes
        else:
            out.pop("notes", None)

    rows = out.get("homeworkTable")
    repaired_rows, changed = _repair_homework_rows(rows, sid)

    if isinstance(rows, list):
        out["homeworkTable"] = repaired_rows
        if changed:
            summary = " / ".join(
                s for s in (_hw_row_summary(row) for row in repaired_rows) if s
            )
            if summary:
                out["homework"] = summary
            else:
                out.pop("homework", None)
    elif _is_question_placeholder(out.get("homework")):
        out.pop("homework", None)

    return out


def _merge_entry_safe(cur: dict, inc: dict) -> dict:
    if not isinstance(cur, dict):
        cur = {}
    if not isinstance(inc, dict):
        return cur

    out = dict(cur)

    # 명시 삭제
    clear = inc.get("__clear")
    if isinstance(clear, list):
        for k in clear:
            kk = str(k).strip()
            if kk:
                out.pop(kk, None)

    cur_done = _truthy(cur.get("done"))

    for k, v in inc.items():
        if k == "__clear":
            continue

        # None은 삭제로 쓰지 말고 __clear로
        if v is None:
            continue

        # 빈값이 기존 유효값을 덮는 것 방지
        if _is_empty_value(v) and not _is_empty_value(out.get(k)):
            continue

        out[k] = v

    # ✅ inc가 done을 언급하지 않았는데, cur이 done이었다면 유지
    if cur_done and "done" not in inc:
        out["done"] = True

    # Safety: if this patch explicitly marks completion, do not keep
    # stale archived=true unless the patch also explicitly asks to archive.
    marks_done_now = _truthy(inc.get("done"))
    marks_leave_now = any(
        (k in inc) and (not _is_empty_value(inc.get(k)))
        for k in ("leaveTime", "leaveAt", "doneTime")
    )
    done_after_merge = _truthy(out.get("done"))
    if (marks_done_now or (marks_leave_now and (cur_done or done_after_merge))) and "archived" not in inc:
        out.pop("archived", None)

    return out


def _normalize_hw_rows_for_compare(rows) -> list:
    if not isinstance(rows, list):
        return []

    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue

        if "book" in row or "this" in row or "comment" in row or "next" in row:
            book = str(row.get("book") or "").strip()
            this_hw = str(row.get("this") or "").strip()
            pct = row.get("pct")
            pct_s = "" if pct in ("", None) else str(pct).strip()
            comment = str(row.get("comment") or "").strip()
            next_hw = str(row.get("next") or "").strip()
            deleted = bool(row.get("_deleted") or row.get("_del") or row.get("deleted"))
        else:
            book = str(row.get("name") or "").strip()
            this_hw = str(row.get("unit") or "").strip()
            pct = row.get("pct")
            pct_s = "" if pct in ("", None) else str(pct).strip()
            comment = str(row.get("rem") or "").strip()
            next_hw = ""
            deleted = False

        out.append({
            "book": book,
            "this": this_hw,
            "pct": pct_s,
            "comment": comment,
            "next": next_hw,
            "_deleted": deleted,
        })

    return out


def _extract_hw_rows_for_compare(entry: dict) -> list:
    if not isinstance(entry, dict):
        return []

    rows = entry.get("homeworkTable")
    if isinstance(rows, list) and rows:
        return _normalize_hw_rows_for_compare(rows)

    homework = str(entry.get("homework") or "").strip()
    if homework:
        return _normalize_hw_rows_for_compare([{
            "book": "",
            "this": "",
            "pct": "",
            "comment": homework,
            "next": "",
            "_deleted": False,
        }])

    return []


def _entry_conflicts_with_base(cur: dict, base: dict) -> bool:
    if not isinstance(base, dict) or not base:
        return False

    current = cur if isinstance(cur, dict) else {}

    if "notes" in base:
        cur_notes = str(current.get("notes") or "").strip()
        base_notes = str(base.get("notes") or "").strip()
        if cur_notes != base_notes:
            return True

    if "homeworkTable" in base:
        cur_rows = _extract_hw_rows_for_compare(current)
        base_rows = _normalize_hw_rows_for_compare(base.get("homeworkTable"))
        if cur_rows != base_rows:
            return True

    return False


# ─────────────────────────────────────────────
# ✅ progress 1건(date/sid) 안전 merge
# - inc[mid] = "done" | "interrupted" | "skip" | "none"
# - "none" is an explicit manual clear marker. It must override older
#   historical progress and automatic watch-status updates.
# ─────────────────────────────────────────────
PROGRESS_ALL_STUDENTS_META_KEY = "__allStudentsProgressMids"
WATCH_AUTO_PROGRESS_META_KEY = "__autoWatchProgressMids"
PROGRESS_MANUAL_META_KEY = "__manualProgressMids"


def _merge_progress_day_sid(cur: dict, inc: dict, source: str = "") -> dict:
    if not isinstance(cur, dict):
        cur = {}
    if not isinstance(inc, dict):
        return dict(cur)

    out = dict(cur)
    source_s = str(source or "").strip()
    all_page_meta = out.get(PROGRESS_ALL_STUDENTS_META_KEY)
    if not isinstance(all_page_meta, dict):
        all_page_meta = {}
    else:
        all_page_meta = dict(all_page_meta)
    watch_auto_meta = out.get(WATCH_AUTO_PROGRESS_META_KEY)
    if not isinstance(watch_auto_meta, dict):
        watch_auto_meta = {}
    else:
        watch_auto_meta = dict(watch_auto_meta)
    manual_meta = out.get(PROGRESS_MANUAL_META_KEY)
    if not isinstance(manual_meta, dict):
        manual_meta = {}
    else:
        manual_meta = dict(manual_meta)

    for mid, st in inc.items():
        mid_s = str(mid).strip()
        if not mid_s:
            continue
        if mid_s.startswith("__"):
            continue

        st_s = str(st).strip()
        if source_s == "auto":
            prev_s = str(out.get(mid_s) or "").strip()
            prev_auto = (
                prev_s in ("done", "interrupted", "skip")
                and str(watch_auto_meta.get(mid_s) or "").strip() == prev_s
            )
            manual_override = bool(manual_meta.get(mid_s))

            all_page_meta.pop(mid_s, None)
            if st_s in ("", "none"):
                if prev_auto and prev_s != "done":
                    out.pop(mid_s, None)
                    watch_auto_meta.pop(mid_s, None)
                elif prev_s not in ("done", "interrupted", "skip", "none"):
                    out.pop(mid_s, None)
                    watch_auto_meta.pop(mid_s, None)
                continue

            if st_s == "interrupted":
                if prev_s == "" or (prev_auto and prev_s != "done"):
                    out[mid_s] = "interrupted"
                    watch_auto_meta[mid_s] = "interrupted"
                    manual_meta.pop(mid_s, None)
                continue

            if st_s == "done":
                if prev_s == "" or prev_auto or (prev_s == "interrupted" and not manual_override):
                    out[mid_s] = "done"
                    watch_auto_meta[mid_s] = "done"
                    manual_meta.pop(mid_s, None)
                continue

            if st_s == "skip":
                if prev_s == "":
                    out[mid_s] = "skip"
                    watch_auto_meta[mid_s] = "skip"
                    manual_meta.pop(mid_s, None)
                continue

        if st_s == "none":
            out[mid_s] = "none"
        elif st_s == "":
            out.pop(mid_s, None)
        else:
            out[mid_s] = st_s

        if source_s == "allStudents":
            if st_s == "":
                all_page_meta.pop(mid_s, None)
            else:
                all_page_meta[mid_s] = True
        else:
            all_page_meta.pop(mid_s, None)
        watch_auto_meta.pop(mid_s, None)
        if source_s == "auto" or st_s == "":
            manual_meta.pop(mid_s, None)
        else:
            manual_meta[mid_s] = True

    if all_page_meta:
        out[PROGRESS_ALL_STUDENTS_META_KEY] = all_page_meta
    else:
        out.pop(PROGRESS_ALL_STUDENTS_META_KEY, None)
    if watch_auto_meta:
        out[WATCH_AUTO_PROGRESS_META_KEY] = watch_auto_meta
    else:
        out.pop(WATCH_AUTO_PROGRESS_META_KEY, None)
    if manual_meta:
        out[PROGRESS_MANUAL_META_KEY] = manual_meta
    else:
        out.pop(PROGRESS_MANUAL_META_KEY, None)

    return out


# ─────────────────────────────────────────────
# ✅ SQLite (logs 테이블) — dual-write용
# logs(date TEXT, sid TEXT, entry_json TEXT, updated_at TEXT, PRIMARY KEY(date,sid))
# ─────────────────────────────────────────────
KST = dt.timezone(dt.timedelta(hours=9))


def _now_kst_iso() -> str:
    return dt.datetime.now(KST).isoformat(timespec="seconds")


def _default_db_path() -> str:
    p = os.environ.get("DB_PATH")
    if p:
        return p
    logs_json = str(getattr(LOGS_PATH, "__fspath__", lambda: str(LOGS_PATH))())
    base_dir = os.path.dirname(os.path.abspath(logs_json))
    return os.path.join(base_dir, "app.sqlite")


def _db_connect() -> sqlite3.Connection:
    db_path = _default_db_path()
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

    con = sqlite3.connect(
        db_path,
        timeout=30.0,
        isolation_level=None,
        check_same_thread=False
    )
    con.row_factory = sqlite3.Row

    con.execute("PRAGMA busy_timeout=30000;")
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    return con


def _db_ensure_schema(con: sqlite3.Connection):
    con.execute("""
    CREATE TABLE IF NOT EXISTS logs (
      date TEXT NOT NULL,
      sid TEXT NOT NULL,
      entry_json TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(date, sid)
    );
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_logs_sid ON logs(sid);")


def _db_get_entry(con: sqlite3.Connection, date: str, sid: str) -> dict:
    row = con.execute("SELECT entry_json FROM logs WHERE date=? AND sid=?;", (date, sid)).fetchone()
    if not row:
        return {}
    try:
        return json.loads(row["entry_json"]) if row["entry_json"] else {}
    except Exception:
        return {}


def _db_upsert_entry(con: sqlite3.Connection, date: str, sid: str, entry: dict):
    safe_entry = _repair_log_entry_placeholders(entry or {}, sid)
    ej = json.dumps(safe_entry, ensure_ascii=False)
    ua = _now_kst_iso()
    con.execute(
        """
        INSERT INTO logs(date, sid, entry_json, updated_at)
        VALUES(?,?,?,?)
        ON CONFLICT(date, sid) DO UPDATE SET
          entry_json=excluded.entry_json,
          updated_at=excluded.updated_at;
        """,
        (date, sid, ej, ua),
    )


def _db_dump_all(con: sqlite3.Connection) -> dict:
    out: Dict[str, Dict[str, dict]] = {}
    rows = con.execute("SELECT date, sid, entry_json FROM logs;").fetchall()
    for r in rows:
        d = str(r["date"])
        s = str(r["sid"])
        try:
            e = json.loads(r["entry_json"]) if r["entry_json"] else {}
        except Exception:
            e = {}
        out.setdefault(d, {})[s] = _repair_log_entry_placeholders(e, s)
    return out


def _db_dump_date(con: sqlite3.Connection, date: str) -> dict:
    out: Dict[str, Dict[str, dict]] = {date: {}}
    rows = con.execute("SELECT sid, entry_json FROM logs WHERE date=?;", (date,)).fetchall()
    for r in rows:
        s = str(r["sid"])
        try:
            e = json.loads(r["entry_json"]) if r["entry_json"] else {}
        except Exception:
            e = {}
        out[date][s] = _repair_log_entry_placeholders(e, s)
    return out


def _db_dump_sid(con: sqlite3.Connection, sid: str) -> dict:
    out: Dict[str, Dict[str, dict]] = {}
    rows = con.execute("SELECT date, sid, entry_json FROM logs WHERE sid=?;", (sid,)).fetchall()
    for r in rows:
        d = str(r["date"])
        s = str(r["sid"])
        try:
            e = json.loads(r["entry_json"]) if r["entry_json"] else {}
        except Exception:
            e = {}
        if isinstance(e, dict) and e:
            out.setdefault(d, {})[s] = _repair_log_entry_placeholders(e, s)
    return out


def _db_dump_date_sid(con: sqlite3.Connection, date: str, sid: str) -> dict:
    out: Dict[str, Dict[str, dict]] = {date: {}}
    entry = _db_get_entry(con, date, sid)
    if isinstance(entry, dict) and entry:
        out[date][sid] = _repair_log_entry_placeholders(entry, sid)
    return out


def _filter_logs_map(data: dict, date_filter: str = "", sid_filter: str = "") -> dict:
    if not isinstance(data, dict):
        return {}

    dates = [date_filter] if date_filter else sorted(data.keys())
    out: Dict[str, Dict[str, dict]] = {}

    for d in dates:
        by_sid = data.get(d) if isinstance(data, dict) else None
        if not isinstance(by_sid, dict):
            if date_filter:
                out.setdefault(str(d), {})
            continue

        if sid_filter:
            entry = _sid_lookup(by_sid, sid_filter)
            if isinstance(entry, dict) and entry:
                out.setdefault(str(d), {})[str(sid_filter)] = _repair_log_entry_placeholders(entry, sid_filter)
            elif date_filter:
                out.setdefault(str(d), {})
            continue

        out[str(d)] = {
            str(sid): _repair_log_entry_placeholders(entry, str(sid))
            for sid, entry in by_sid.items()
            if isinstance(entry, dict)
        }

    return out


# ─────────────────────────────────────────────
# updates 자동배정 보정 (원본 유지)
# ─────────────────────────────────────────────
def _chap_num(v: dict) -> float:
    c = v.get("chapter", 0)
    try:
        return float(c)
    except Exception:
        s = re.sub(r"[^0-9.]", "", str(c))
        return float(s) if s else 0.0


def _has_assigned(val) -> bool:
    if isinstance(val, list):
        return len(val) > 0
    if isinstance(val, dict):
        vids = val.get("videos")
        return isinstance(vids, list) and len(vids) > 0
    return False


AUTO_VIDEO_ASSIGN_FIELD = "autoVideoAssignCount"
DEFAULT_AUTO_VIDEO_ASSIGN_COUNT = 3
MIN_AUTO_VIDEO_ASSIGN_COUNT = 1
MAX_AUTO_VIDEO_ASSIGN_COUNT = 10
WATCH_INTERRUPTED_RATIO = 0.05
WATCH_DONE_RATIO = 0.90


def _coerce_auto_video_assign_count(value, default: int = DEFAULT_AUTO_VIDEO_ASSIGN_COUNT) -> int:
    try:
        n = int(round(float(value)))
    except Exception:
        n = default
    return max(MIN_AUTO_VIDEO_ASSIGN_COUNT, min(MAX_AUTO_VIDEO_ASSIGN_COUNT, n))


def _student_auto_video_assign_count(stu: dict) -> int:
    if not isinstance(stu, dict):
        return DEFAULT_AUTO_VIDEO_ASSIGN_COUNT
    return _coerce_auto_video_assign_count(stu.get(AUTO_VIDEO_ASSIGN_FIELD))


def _build_latest_status_by_sid(progress: dict) -> dict:
    out = {}
    if not isinstance(progress, dict):
        return out

    for d in sorted(progress.keys()):
        day = progress.get(d) or {}
        if not isinstance(day, dict):
            continue
        for sid, mids in day.items():
            if not isinstance(mids, dict):
                continue
            sm = out.setdefault(str(sid), {})
            for mid, st in mids.items():
                mid_s = str(mid)
                if mid_s.startswith("__") or mid_s == "tests":
                    continue
                sm[mid_s] = st
    return out


def _watch_ratio(entry: dict) -> float:
    if not isinstance(entry, dict):
        return 0.0
    try:
        last = max(0.0, float(entry.get("last") or 0))
        dur = max(0.0, float(entry.get("dur") or 0))
    except Exception:
        return 0.0
    if dur <= 0:
        return 0.0
    return max(0.0, min(1.0, last / dur))


def _watch_auto_status(entry: dict) -> str:
    if not isinstance(entry, dict):
        return ""
    if bool(entry.get("completed")) or _watch_ratio(entry) >= WATCH_DONE_RATIO:
        return "done"
    if _watch_ratio(entry) >= WATCH_INTERRUPTED_RATIO:
        return "interrupted"
    return ""


def _build_auto_assignment_blocked_by_sid(progress: dict, watch: dict) -> dict:
    blocked: dict[str, set[str]] = {}
    manual_cleared_at: dict[tuple[str, str], str] = {}

    if isinstance(progress, dict):
        for d in sorted(progress.keys()):
            day = progress.get(d) or {}
            if not isinstance(day, dict):
                continue
            for sid, mids in day.items():
                if not isinstance(mids, dict):
                    continue
                sid_s = str(sid)
                manual_meta = mids.get(PROGRESS_MANUAL_META_KEY)
                if not isinstance(manual_meta, dict):
                    manual_meta = {}
                for mid, st in mids.items():
                    mid_s = str(mid)
                    if mid_s.startswith("__") or mid_s == "tests":
                        continue
                    st_s = str(st or "").strip()
                    key = (sid_s, mid_s)
                    if st_s in ("done", "skip"):
                        blocked.setdefault(sid_s, set()).add(mid_s)
                    elif st_s == "none" and manual_meta.get(mid_s):
                        blocked.setdefault(sid_s, set()).discard(mid_s)
                        manual_cleared_at[key] = str(d)

    if isinstance(watch, dict):
        for d in sorted(watch.keys()):
            by_date = watch.get(d) or {}
            if not isinstance(by_date, dict):
                continue
            for sid, mids in by_date.items():
                if not isinstance(mids, dict):
                    continue
                sid_s = str(sid)
                for mid, entry in mids.items():
                    mid_s = str(mid or "").strip()
                    if not mid_s:
                        continue
                    status = _watch_auto_status(entry)
                    if status != "done":
                        continue
                    cleared_at = manual_cleared_at.get((sid_s, mid_s), "")
                    if cleared_at and str(cleared_at) >= str(d):
                        continue
                    blocked.setdefault(sid_s, set()).add(mid_s)

    return blocked


def _today_kst_iso() -> str:
    return dt.datetime.now(KST).date().isoformat()


def _ensure_today_auto_assign(updates, students, videos, progress, date_key: str | None = None, watch=None):
    today = date_key or _today_kst_iso()

    if not isinstance(updates, dict):
        updates = {}
    updates.setdefault(today, {})
    if not isinstance(updates[today], dict):
        updates[today] = {}

    valid_mids = set()
    for v in (videos or []):
        if isinstance(v, dict):
            mid = str(v.get("mid") or "").strip()
            if mid:
                valid_mids.add(mid)

    blocked_by_sid = _build_auto_assignment_blocked_by_sid(progress, watch or {})

    def _normalize_assigned(val):
        if isinstance(val, list):
            return [str(x).strip() for x in val if str(x).strip()]
        if isinstance(val, dict):
            vids = val.get("videos")
            if isinstance(vids, list):
                return [str(x).strip() for x in vids if str(x).strip()]
        return []

    changed = False

    for sid, cur in list(updates[today].items()):
        assigned = _normalize_assigned(cur)
        if not assigned:
            continue
        cleaned = [mid for mid in assigned if mid in valid_mids]
        if cleaned != assigned:
            if cleaned:
                updates[today][sid] = cleaned
            else:
                updates[today].pop(sid, None)
            changed = True

    for stu in students or []:
        if not isinstance(stu, dict):
            continue

        sid = str(stu.get("id") or "").strip()
        if not sid:
            continue

        cur_key = (stu.get("curriculum") or "").strip()
        sub_key = (stu.get("subCurriculum") or "").strip()

        cur = updates[today].get(sid)
        if _has_assigned(cur):
            continue

        cur_vids = [
            v for v in (videos or [])
            if isinstance(v, dict)
            and (v.get("curriculum") or "").strip() == cur_key
            and (v.get("subCurriculum") or "").strip() == sub_key
        ]
        cur_vids.sort(key=lambda v: (_chap_num(v), str(v.get("mid") or "")))

        blocked = {str(mid) for mid in (blocked_by_sid.get(sid) or set())}

        max_assign = _student_auto_video_assign_count(stu)

        picked = []
        for v in cur_vids:
            mid = str(v.get("mid") or "").strip()
            if not mid:
                continue
            if mid not in valid_mids:
                continue
            if mid in blocked:
                continue
            picked.append(mid)
            if len(picked) >= max_assign:
                break

        if picked:
            print("[AUTOASSIGN] PICK sid =", sid, "picked =", picked, flush=True)
            updates[today][sid] = picked
            changed = True

    return updates


def _json_stable(obj) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except Exception:
        return ""


def _load_updates_with_auto_assign(students=None, videos=None, date_key: str | None = None):
    students = students if students is not None else load(STU_PATH)
    videos = videos if videos is not None else load(VID_PATH)
    progress = load(PRG_PATH)
    watch = load(WATCH_PATH)

    with _updates_lock():
        updates = load(UPD_PATH) or {}
        before = _json_stable(updates)
        fixed = _ensure_today_auto_assign(updates, students, videos, progress, date_key=date_key, watch=watch)
        if _json_stable(fixed) != before:
            save_atomic(UPD_PATH, fixed)
        return fixed


# ─────────────────────────────────────────────
# 기본 API
# ─────────────────────────────────────────────
@bp_api_basic.route("/api/students", methods=["GET", "POST"])
def api_students():
    return crud(STU_PATH)


@bp_api_basic.route("/api/videos", methods=["GET", "POST"])
def api_videos():
    if request.method == "GET":
        return jsonify(load(VID_PATH))

    prev_videos = load(VID_PATH)
    next_videos = _normalize_video_mid_fields(request.get_json(force=True))
    save_atomic(VID_PATH, next_videos)
    _migrate_video_mid_references(prev_videos, next_videos)
    return "", 204


@bp_api_basic.route("/api/progress", methods=["GET"])
def api_progress():
    data = _load_progress_strict()
    date = str(request.args.get("date") or "").strip()
    sid = str(request.args.get("sid") or "").strip()

    if date:
        if not DATE_RE.match(date):
            return jsonify({"ok": False, "error": "bad date"}), 400
        day = data.get(date) if isinstance(data, dict) else {}
        if sid:
            entry = _sid_lookup(day if isinstance(day, dict) else {}, sid) or {}
            return jsonify({date: {str(sid): entry}})
        return jsonify({date: day if isinstance(day, dict) else {}})

    if sid:
        out = {}
        for d, day in (data.items() if isinstance(data, dict) else []):
            if not isinstance(day, dict):
                continue
            entry = _sid_lookup(day, sid)
            if isinstance(entry, dict) and entry:
                out[d] = {str(sid): entry}
        return jsonify(out)

    return jsonify(data)


@bp_api_basic.post("/api/progress/patch")
def api_progress_patch():
    """
    body:
      {
        "date": "YYYY-MM-DD",
        "sid": "전강우334",
        "progress": {
          "mid1": "done",
          "mid2": "interrupted",
          "mid3": "none"
        }
      }
    """
    body = request.get_json(force=True) or {}
    date = str(body.get("date") or "").strip()
    sid = str(body.get("sid") or "").strip()
    prog = body.get("progress") or {}
    source = str(body.get("source") or "").strip()

    if not date or not sid or not isinstance(prog, dict):
        return jsonify({"ok": False, "error": "bad payload"}), 400
    if not DATE_RE.match(date):
        return jsonify({"ok": False, "error": "bad date"}), 400

    try:
        with _progress_lock():
            current = _load_progress_strict()

            day = current.setdefault(date, {})
            if not isinstance(day, dict):
                current[date] = {}
                day = current[date]

            cur_sid = day.get(sid, {})
            if not isinstance(cur_sid, dict):
                cur_sid = {}

            merged = _merge_progress_day_sid(cur_sid, prog, source=source)

            if merged:
                day[sid] = merged
            else:
                day.pop(sid, None)

            if not day:
                current.pop(date, None)

            save_atomic(PRG_PATH, current)

        return jsonify({"ok": True, "progress": merged})
    except TimeoutError as e:
        return jsonify({"ok": False, "error": str(e)}), 409
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp_api_basic.route("/api/updates", methods=["GET", "POST"])
def api_updates():
    if request.method == "GET":
        return nocache_resp(_load_updates_with_auto_assign())

    incoming = request.get_json(force=True) or {}
    with _updates_lock():
        current = load(UPD_PATH) or {}
        merged = _merge_updates_payload(current, incoming)
        save_atomic(UPD_PATH, merged)
    return "", 204


@bp_api_basic.post("/api/updates/patch")
def api_updates_patch():
    body = request.get_json(force=True) or {}
    date = str(body.get("date") or "").strip()
    sid = str(body.get("sid") or "").strip()
    remove = bool(body.get("remove"))

    if not date or not sid or not DATE_RE.match(date):
        return jsonify({"ok": False, "error": "bad payload"}), 400

    if remove:
        incoming = {"remove": True}
    else:
        incoming = dict(body.get("entry") or {}) if isinstance(body.get("entry"), dict) else {}
        if "videos" in body:
            incoming["videos"] = body.get("videos")
        if not incoming:
            incoming["videos"] = []

    try:
        with _updates_lock():
            current = load(UPD_PATH) or {}
            day = current.setdefault(date, {})
            if not isinstance(day, dict):
                current[date] = {}
                day = current[date]

            if remove:
                _write_sid_mapping(day, sid, None)
                assignment = []
            else:
                assignment = _merge_update_assignment(_sid_lookup(day, sid), incoming)
                _write_sid_mapping(day, sid, assignment)

            if not day:
                current.pop(date, None)

            save_atomic(UPD_PATH, current)
        return jsonify({"ok": True, "assignment": assignment})
    except TimeoutError as e:
        return jsonify({"ok": False, "error": str(e)}), 409


@bp_api_basic.get("/api/student/bootstrap")
def api_student_bootstrap():
    sid = str(request.args.get("sid") or "").strip()
    date = str(request.args.get("date") or _today_kst_iso()).strip()
    if not sid:
        return jsonify({"ok": False, "error": "missing sid"}), 400
    if not DATE_RE.match(date):
        return jsonify({"ok": False, "error": "bad date"}), 400

    students = load(STU_PATH) or []
    student = next((s for s in students if isinstance(s, dict) and str(s.get("id")) == sid), None)
    if not student:
        return jsonify({"ok": False, "error": "student not found"}), 404

    absences = load_absent()
    absent_for_date = {
        "by_date": {date: (absences.get("by_date") or {}).get(date, [])},
        "by_student": {sid: (absences.get("by_student") or {}).get(sid)}
            if (absences.get("by_student") or {}).get(sid) else {},
    }

    if not _student_is_registered_on_date(student, sid, date):
        return nocache_resp({
            "ok": True,
            "date": date,
            "students": [student],
            "student": student,
            "videos": [],
            "updates": {date: {sid: []}},
            "materials": {},
            "assigns": {sid: []},
            "absent": absent_for_date,
            "logs": {date: {}},
            "courseBlocked": True,
            "blockMessage": STUDENT_COURSE_BLOCK_MESSAGE,
        })

    videos_all = load(VID_PATH) or []
    if date == _today_kst_iso():
        updates = _load_updates_with_auto_assign(students=students, videos=videos_all, date_key=date)
    else:
        updates = load(UPD_PATH) or {}
    day_updates = updates.get(date) if isinstance(updates, dict) else {}
    assignment = _sid_lookup(day_updates if isinstance(day_updates, dict) else {}, sid)
    assigned_videos = _normalize_video_assign_list(assignment)
    assigned_set = set(assigned_videos)

    videos = [
        v for v in videos_all
        if isinstance(v, dict) and str(v.get("mid") or "").strip() in assigned_set
    ]

    assigns = load(ASN_PATH) or {}
    material_assignment = _sid_lookup(assigns if isinstance(assigns, dict) else {}, sid)
    assigned_materials = _assigned_material_list(material_assignment)
    materials = _filter_materials_for_assignment(load(MAT_PATH) or {}, assigned_materials)

    logs = {}
    try:
        con = _db_connect()
        _db_ensure_schema(con)
        entry = _db_get_entry(con, date, sid)
        if isinstance(entry, dict) and entry:
            logs = {date: {sid: entry}}
    except Exception:
        logs = {}
    finally:
        try:
            con.close()
        except Exception:
            pass

    if not logs:
        try:
            json_logs = load(LOGS_PATH) or {}
            entry = _sid_lookup((json_logs.get(date) or {}) if isinstance(json_logs, dict) else {}, sid)
            logs = {date: {sid: entry}} if isinstance(entry, dict) and entry else {date: {}}
        except Exception:
            logs = {date: {}}

    return nocache_resp({
        "ok": True,
        "date": date,
        "students": [student],
        "student": student,
        "videos": videos,
        "updates": {date: {sid: assignment or []}},
        "materials": materials,
        "assigns": {sid: material_assignment or []},
        "absent": absent_for_date,
        "logs": logs,
    })


@bp_api_basic.route("/api/mat-assign", methods=["GET", "POST"])
def api_mat_assign():
    return crud(ASN_PATH)


@bp_api_basic.route("/api/materials", methods=["GET", "POST"])
def api_materials():
    if request.method == "GET":
        return jsonify(load(MAT_PATH))
    save_atomic(MAT_PATH, request.get_json(force=True))
    return "", 204


@bp_api_basic.route("/api/school-calendar", methods=["GET", "POST"])
def api_school_calendar():
    if request.method == "GET":
        return nocache_resp(load(CAL_PATH))
    data = request.get_json(force=True) or {}
    with _InterProcessFileLock(str(CAL_PATH) + ".lock", timeout_sec=4.0, poll_sec=0.05):
        save_atomic(CAL_PATH, data)
    return jsonify(data)


@bp_api_basic.post("/api/add-student")
def api_add_student():
    students: List[dict] = load(STU_PATH)
    data = request.get_json(force=True) or {}
    raw_name = str(data.get("name", "user"))
    name_slug = re.sub(r"[^0-9A-Za-z가-힣]", "", raw_name)
    data["id"] = f"{name_slug}{random.randint(0, 999):03d}"
    students.append(data)
    save_atomic(STU_PATH, students)
    return jsonify({"id": data["id"]})


@bp_api_basic.post("/api/feedback")
def api_feedback():
    import json as _json
    from core.paths import BASE
    data = request.get_json(force=True) or {}
    with open(BASE / "feedbacks.json", "a", encoding="utf-8") as f:
        _json.dump(data, f, ensure_ascii=False)
        f.write("\n")
    return "", 204


@bp_api_basic.route("/api/extra-attend", methods=["GET", "POST"])
def api_extra_attend():
    return crud(EXTRA_PATH)


@bp_api_basic.route("/api/weekend-slots", methods=["GET", "POST"])
def api_weekend_slots():
    if request.method == "GET":
        return jsonify(load(WEEKEND_SLOTS_PATH))
    body = request.get_json(force=True) or {}
    cur = load(WEEKEND_SLOTS_PATH)
    for date, mapping in (body.items() if isinstance(body, dict) else []):
        if not isinstance(mapping, dict):
            continue

        def norm(v):
            if isinstance(v, list):
                return [int(x) for x in v if str(x).isdigit()]
            if str(v).isdigit():
                return int(v)
            return v

        cur.setdefault(date, {}).update({str(k): norm(v) for k, v in mapping.items()})
    save_atomic(WEEKEND_SLOTS_PATH, cur)
    return "", 204


@bp_api_basic.get("/api/logs/entry")
def api_logs_entry():
    """
    GET /api/logs/entry?date=YYYY-MM-DD&sid=...
    - SQLite 우선 조회
    - 없거나 실패하면 logs.json fallback
    """
    date = str(request.args.get("date") or "").strip()
    sid = str(request.args.get("sid") or "").strip()

    if not date or not sid or not DATE_RE.match(date):
        return jsonify({"ok": False, "error": "bad query"}), 400

    try:
        con = _db_connect()
        _db_ensure_schema(con)
        entry = _db_get_entry(con, date, sid) or {}
        try:
            con.close()
        except Exception:
            pass

        if isinstance(entry, dict) and entry:
            return jsonify({"ok": True, "source": "sqlite", "entry": _repair_log_entry_placeholders(entry, sid)})
    except Exception as e:
        print("[logs.entry] sqlite failed:", e, flush=True)
        try:
            con.close()
        except Exception:
            pass

    try:
        logs = load(LOGS_PATH) or {}
        entry = (logs.get(date) or {}).get(sid) or {}
        if not isinstance(entry, dict):
            entry = {}
    except Exception:
        entry = {}

    return jsonify({"ok": True, "source": "json", "entry": _repair_log_entry_placeholders(entry, sid)})


def _summarize_unarchived_done_logs(exclude_date: str = "") -> dict:
    entries: Dict[str, Dict[str, dict]] = {}
    sqlite_keys = set()

    con = None
    try:
        con = _db_connect()
        _db_ensure_schema(con)
        for row in con.execute("SELECT date, sid FROM logs;").fetchall():
            sqlite_keys.add((str(row["date"]), str(row["sid"])))

        rows = con.execute(
            """
            SELECT date, sid, entry_json
            FROM logs
            WHERE json_extract(entry_json, ?) IN (1, 'true')
              AND COALESCE(json_extract(entry_json, ?), 0) NOT IN (1, 'true');
            """,
            ("$.done", "$.archived"),
        ).fetchall()
        for row in rows:
            d = str(row["date"])
            sid = str(row["sid"])
            try:
                entry = json.loads(row["entry_json"]) if row["entry_json"] else {}
            except Exception:
                entry = {}
            if isinstance(entry, dict):
                entries.setdefault(d, {})[sid] = _repair_log_entry_placeholders(entry, sid)
    except Exception as e:
        print("[logs.unarchived-summary] sqlite failed:", e, flush=True)
    finally:
        try:
            con.close()
        except Exception:
            pass

    try:
        json_map = load(LOGS_PATH) or {}
        if isinstance(json_map, dict):
            for d, by_sid in json_map.items():
                if not isinstance(by_sid, dict):
                    continue
                d_s = str(d)
                day = entries.setdefault(str(d), {})
                for sid, entry in by_sid.items():
                    sid_s = str(sid)
                    if (d_s, sid_s) in sqlite_keys or sid_s in day or not isinstance(entry, dict):
                        continue
                    if not _truthy(entry.get("done")) or _truthy(entry.get("archived")):
                        continue
                    day[sid_s] = _repair_log_entry_placeholders(entry, sid_s)
    except Exception:
        pass

    by_date: Dict[str, int] = {}
    students = set()
    total = 0
    today = _today_kst_iso()
    for d, by_sid in entries.items():
        d_s = str(d)
        if exclude_date and d_s == exclude_date:
            continue
        if d_s >= today:
            continue
        if not isinstance(by_sid, dict):
            continue
        for sid, entry in by_sid.items():
            if not isinstance(entry, dict):
                continue
            if not _truthy(entry.get("done")) or _truthy(entry.get("archived")):
                continue
            by_date[d_s] = by_date.get(d_s, 0) + 1
            students.add(str(sid))
            total += 1

    return {
        "ok": True,
        "excludeDate": exclude_date,
        "total": total,
        "students": len(students),
        "byDate": [
            {"date": d, "count": by_date[d]}
            for d in sorted(by_date.keys(), reverse=True)
        ],
    }


@bp_api_basic.get("/api/logs/unarchived-summary")
def api_logs_unarchived_summary():
    exclude_date = str(
        request.args.get("exclude_date")
        or request.args.get("excludeDate")
        or ""
    ).strip()
    if exclude_date and not DATE_RE.match(exclude_date):
        return jsonify({"ok": False, "error": "bad date"}), 400
    return jsonify(_summarize_unarchived_done_logs(exclude_date))


# ─────────────────────────────────────────────
# ✅ LOGS (dual-write)
# GET: SQLite 우선 + JSON 보강
# POST /api/logs/patch: SQLite 저장 + JSON 저장(둘 다)
# POST /api/logs: 레거시 전체 업로드도 둘 다 반영
# ─────────────────────────────────────────────
@bp_api_basic.route("/api/logs", methods=["GET", "POST"])
def api_logs():
    if request.method == "GET":
        date_filter = str(request.args.get("date") or "").strip()
        sid_filter = str(request.args.get("sid") or "").strip()
        if date_filter and not DATE_RE.match(date_filter):
            return jsonify({"ok": False, "error": "bad date"}), 400

        sqlite_map = {}
        sqlite_ok = False
        try:
            con = _db_connect()
            _db_ensure_schema(con)
            if date_filter and sid_filter:
                sqlite_map = _db_dump_date_sid(con, date_filter, sid_filter)
            elif date_filter:
                sqlite_map = _db_dump_date(con, date_filter)
            elif sid_filter:
                sqlite_map = _db_dump_sid(con, sid_filter)
            else:
                sqlite_map = _db_dump_all(con)
            sqlite_ok = True
        except Exception as e:
            print("[logs] sqlite GET failed:", e, flush=True)
            sqlite_ok = False
        finally:
            try:
                con.close()
            except Exception:
                pass

        json_map = {}
        try:
            json_map = load(LOGS_PATH) or {}
            if not isinstance(json_map, dict):
                json_map = {}
            if date_filter or sid_filter:
                json_map = _filter_logs_map(json_map, date_filter, sid_filter)
        except Exception:
            json_map = {}

        if not sqlite_ok:
            return nocache_resp(json_map)

        out = dict(sqlite_map)
        for d, by_sid in (json_map.items() if isinstance(json_map, dict) else []):
            if not isinstance(by_sid, dict):
                continue
            day = out.setdefault(d, {})
            if not isinstance(day, dict):
                out[d] = {}
                day = out[d]
            for sid, entry in by_sid.items():
                sid_s = str(sid)
                if sid_s not in day:
                    if isinstance(entry, dict):
                        day[sid_s] = _repair_log_entry_placeholders(entry, sid_s)
        return nocache_resp(out)

    incoming = request.get_json(force=True) or {}
    if not isinstance(incoming, dict):
        incoming = {}

    sqlite_ok = False
    sqlite_err = None

    try:
        con = _db_connect()
        _db_ensure_schema(con)
        con.execute("BEGIN IMMEDIATE;")
        for date, by_sid in incoming.items():
            if not isinstance(by_sid, dict):
                continue
            if not DATE_RE.match(str(date)):
                continue
            for sid, entry in by_sid.items():
                if not isinstance(entry, dict):
                    continue
                date_s = str(date)
                sid_s = str(sid)
                safe_entry = _repair_log_entry_placeholders(entry, sid_s)

                cur = _db_get_entry(con, date_s, sid_s)
                merged = _merge_entry_safe(cur, safe_entry)
                _db_upsert_entry(con, date_s, sid_s, merged)
        con.execute("COMMIT;")
        sqlite_ok = True
    except Exception as e:
        sqlite_err = e
        try:
            con.execute("ROLLBACK;")
        except Exception:
            pass
        print("[logs] sqlite legacy POST failed:", e, flush=True)
        sqlite_ok = False
    finally:
        try:
            con.close()
        except Exception:
            pass

    with _logs_lock():
        current = load(LOGS_PATH) or {}
        if not isinstance(current, dict):
            current = {}

        for date, by_sid in incoming.items():
            if not isinstance(by_sid, dict):
                continue
            cur_day = current.setdefault(date, {})
            if not isinstance(cur_day, dict):
                current[date] = {}
                cur_day = current[date]

            for sid, entry in by_sid.items():
                if not isinstance(entry, dict):
                    continue
                sid_s = str(sid)
                safe_entry = _repair_log_entry_placeholders(entry, sid_s)
                cur_entry = cur_day.get(sid_s, {})
                cur_day[sid_s] = _merge_entry_safe(cur_entry, safe_entry)

        save_atomic(LOGS_PATH, current)

    if not sqlite_ok:
        return jsonify({"ok": False, "sqlite": False, "error": str(sqlite_err) if sqlite_err else "sqlite failed"}), 409

    return "", 204


@bp_api_basic.post("/api/logs/patch")
def api_logs_patch():
    """
    dual-write PATCH
    body:
      {
        "date": "YYYY-MM-DD",
        "sid": "???334",
        "entry": { ...????... },
        "__clear": ["notes", ...]
      }
    """
    body = request.get_json(force=True) or {}
    date = str(body.get("date") or "").strip()
    sid = str(body.get("sid") or "").strip()
    entry = body.get("entry") or {}
    base = body.get("base") if isinstance(body.get("base"), dict) else {}

    top_clear = body.get("__clear")
    if isinstance(top_clear, list) and isinstance(entry, dict):
        entry = dict(entry)
        entry["__clear"] = top_clear

    if not date or not sid or not isinstance(entry, dict):
        return jsonify({"ok": False, "error": "bad payload"}), 400
    if not DATE_RE.match(date):
        return jsonify({"ok": False, "error": "bad date"}), 400

    entry = _repair_log_entry_placeholders(entry, sid)
    base = _repair_log_entry_placeholders(base, sid)

    merged: dict = {}

    sqlite_ok = False
    sqlite_err = None
    sqlite_base_conflict = False
    try:
        con = _db_connect()
        _db_ensure_schema(con)
        con.execute("BEGIN IMMEDIATE;")
        cur = _repair_log_entry_placeholders(_db_get_entry(con, date, sid), sid)
        if _entry_conflicts_with_base(cur, base):
            con.execute("ROLLBACK;")
            # SQLite? JSON? ?? ??? ??? ?? ?? ?? ??? JSON ???? ??.
            sqlite_base_conflict = True
            sqlite_ok = False
        else:
            merged = _merge_entry_safe(cur, entry)
            _db_upsert_entry(con, date, sid, merged)
            con.execute("COMMIT;")
            sqlite_ok = True
    except Exception as e:
        sqlite_err = e
        try:
            con.execute("ROLLBACK;")
        except Exception:
            pass
        print("[logs] sqlite PATCH failed:", e, flush=True)
        sqlite_ok = False
    finally:
        try:
            con.close()
        except Exception:
            pass

    try:
        with _logs_lock():
            current = load(LOGS_PATH) or {}
            if not isinstance(current, dict):
                current = {}
            day = current.setdefault(date, {})
            if not isinstance(day, dict):
                current[date] = {}
                day = current[date]

            cur_json = day.get(sid, {})
            if not isinstance(cur_json, dict):
                cur_json = {}
            cur_json = _repair_log_entry_placeholders(cur_json, sid)

            if _entry_conflicts_with_base(cur_json, base):
                return jsonify({
                    "ok": False,
                    "retryable": False,
                    "error": "?? ???? ????/??? ?? ??????. ?? ?? ?? ?? ??????.",
                    "entry": cur_json,
                }), 409

            if not merged:
                merged = _merge_entry_safe(cur_json, entry)
            merged = _repair_log_entry_placeholders(merged, sid)
            day[sid] = merged

            save_atomic(LOGS_PATH, current)
    except Exception as e:
        print("[logs] json PATCH failed:", e, flush=True)

    # JSON ?? ?? ? SQLite ????(?? ??/?? ?? ??? ??)
    if not sqlite_ok:
        try:
            con2 = _db_connect()
            _db_ensure_schema(con2)
            _db_upsert_entry(con2, date, sid, merged)
            con2.commit()
            sqlite_ok = True
            sqlite_err = None
        except Exception as e:
            sqlite_err = e
            sqlite_ok = False
        finally:
            try:
                con2.close()
            except Exception:
                pass

    if not sqlite_ok:
        # ??? ?? ??? ?? ?? ?? JSON ?? ? 200?? ??
        if sqlite_base_conflict:
            return jsonify({"ok": True, "sqlite": False, "entry": merged, "warning": "sqlite out-of-sync"})
        return jsonify({"ok": False, "sqlite": False, "error": str(sqlite_err) if sqlite_err else "sqlite failed"}), 409

    return jsonify({"ok": True, "sqlite": True, "entry": merged})


# ─────────────────────────────────────────────
# 기타
# ─────────────────────────────────────────────
@bp_api_basic.delete("/api/students/<string:sid>")
def api_delete_student(sid: str):
    students: List[dict] = load(STU_PATH)
    for i, s in enumerate(students):
        if str(s.get("id")) == str(sid):
            del students[i]
            save_atomic(STU_PATH, students)
            return "", 204
    abort(404, description="학생을 찾을 수 없습니다.")


@bp_api_basic.post("/api/update")
def api_update_student_field():
    body = request.get_json(force=True) or {}
    sid = body.get("id")
    field = body.get("field")
    value = body.get("value")

    if not sid or not field:
        abort(400)

    students: List[dict] = load(STU_PATH)
    for s in students:
        if str(s.get("id")) == str(sid):
            if field == AUTO_VIDEO_ASSIGN_FIELD:
                value = _coerce_auto_video_assign_count(value)
            s[field] = value
            save_atomic(STU_PATH, students)
            return "OK"
    abort(404)


@bp_api_basic.get("/api/ping")
def api_ping():
    return "ok"
