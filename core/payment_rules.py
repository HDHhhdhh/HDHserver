"""Pure tuition-ledger commands. One SID is one course account."""
from __future__ import annotations

from copy import deepcopy
from datetime import date


class PaymentError(ValueError):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.status = code, status


def integer(value, label, minimum=0, maximum=1_000_000_000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise PaymentError("invalid_number", f"{label}: {minimum}~{maximum} 범위의 정수를 입력해 주세요.")
    return value


def text(value, label, limit=1000, required=False):
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise PaymentError("invalid_text", f"{label} 입력을 확인해 주세요.")
    value = value.strip()
    if required and not value:
        raise PaymentError("required", f"{label}을 입력해 주세요.")
    return value


def day(value):
    try:
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError()
    except ValueError:
        raise PaymentError("invalid_date", "날짜는 실제 날짜의 YYYY-MM-DD 형식이어야 합니다.") from None
    return value


def choice(value, values, label):
    if value not in values:
        raise PaymentError("invalid_choice", f"{label}을 선택해 주세요.")
    return value


def empty_account(sid):
    return {"sid": sid, "config": None, "packages": [], "receipts": [], "sessions": []}


PLANS = [
    {"id": "standard", "label": "기본 · 8회", "lines": [{"label": "기본", "units": 8, "unitPrice": 56250}]},
    {"id": "weekly3", "label": "주 3회 · 12회", "lines": [{"label": "기본", "units": 8, "unitPrice": 56250},
        {"label": "특강", "units": 4, "unitPrice": 37500}]},
    {"id": "weekly4", "label": "주 4회 · 16회", "lines": [{"label": "기본", "units": 8, "unitPrice": 56250},
        {"label": "특강", "units": 8, "unitPrice": 31250}]},
    {"id": "special4", "label": "(특) 추가 강좌만 · 4회", "lines": [{"label": "특강", "units": 4, "unitPrice": 37500}]},
    {"id": "special8", "label": "(특) 추가 강좌만 · 8회", "lines": [{"label": "특강", "units": 8, "unitPrice": 31250}]},
]


def price_lines(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 4:
        raise PaymentError("invalid_lines", "수강료 구성을 1~4개 입력해 주세요.")
    result = []
    for row in value:
        if not isinstance(row, dict) or set(row) != {"label", "units", "unitPrice"}:
            raise PaymentError("invalid_lines", "수강료 구성의 이름·회차·단가를 확인해 주세요.")
        result.append({"label": text(row["label"], "구성 이름", 40, required=True),
            "units": integer(row["units"], "회차", 1, 200), "unitPrice": integer(row["unitPrice"], "회당 단가", 1)})
    integer(sum(row["units"] for row in result), "총 회차", 1, 200)
    integer(sum(row["units"] * row["unitPrice"] for row in result), "총 수강료", 1)
    return result


def active(rows):
    return [row for row in rows if not row.get("voided")]


def find(rows, key, label):
    for row in rows:
        if row["id"] == key and not row.get("voided"):
            return row
    raise PaymentError("not_found", f"{label}을 찾지 못했습니다. 새로 불러와 주세요.", 404)


def package_balance(state, package):
    balances = [line_balance(state, package, i) for i in range(len(package["lines"]))]
    return {key: sum(row[key] for row in balances) for key in
        ("billed", "paid", "due", "refundDue", "usedUnits", "remainingUnits", "cancelledUnits")}


def line_balance(state, package, index):
    line = package["lines"][index]
    sessions = [row for row in active(state["sessions"]) if row.get("packageId") == package["id"] and row.get("lineIndex") == index]
    refunds = [row for row in active(state["receipts"]) if row["packageId"] == package["id"] and row["kind"] == "refund" and row.get("lineIndex") == index]
    cancelled = sum(row["cancelledUnits"] for row in refunds)
    used = sum(row["chargedUnits"] for row in sessions)
    credit = sum(row["creditAmount"] for row in refunds)
    net = line["units"] * line["unitPrice"] - (package["discount"] if len(package["lines"]) == 1 else 0)
    paid = sum(row["amount"] for row in active(state["receipts"]) if row["packageId"] == package["id"] and row.get("lineIndex") == index)
    return {"netAmount": net, "usedUnits": used, "cancelledUnits": cancelled, "creditAmount": credit,
        "remainingUnits": line["units"] - cancelled - used, "billed": net - credit, "paid": paid,
        "due": max(net - credit - paid, 0), "refundDue": max(paid - net + credit, 0)}


def refund_credit(state, package, index, units):
    balance = line_balance(state, package, index)
    integer(units, "취소 회차", 0, balance["remainingUnits"])
    # Cumulative integer rounding preserves the exact component total across split refunds.
    cancelled = balance["cancelledUnits"]
    return balance["netAmount"] * (cancelled + units) // package["lines"][index]["units"] - balance["creditAmount"]


def account_summary(state):
    fields = ("billed", "paid", "due", "refundDue", "usedUnits", "remainingUnits")
    result = dict.fromkeys(fields, 0)
    for package in state["packages"]:
        balance = package_balance(state, package)
        for key in fields:
            result[key] += balance[key]
    dates = [row["date"] for row in active(state["receipts"]) if row["amount"] > 0]
    result.update(configured=state["config"] is not None, lastPaymentDate=max(dates, default=""))
    return result


def _configure(state, command, _today, _entity_id):
    state["config"] = {
        "lines": price_lines(command.get("lines")),
        "chargePolicy": "attended",
        "startsOn": day(command.get("startsOn")),
    }
    return "config"


def _package(state, command, today, entity_id):
    if not state["config"]:
        raise PaymentError("account_not_configured", "먼저 단가와 회차 차감 규칙을 설정해 주세요.")
    sold_on = day(command.get("date"))
    if sold_on > today:
        raise PaymentError("future_payment", "미래 날짜로 수강권을 등록할 수 없습니다.")
    lines = price_lines(command.get("lines"))
    units = sum(row["units"] for row in lines)
    total = sum(row["units"] * row["unitPrice"] for row in lines)
    discount = integer(command.get("discount", 0), "할인액", 0, total)
    if len(lines) > 1 and discount:
        raise PaymentError("component_discount_required", "여러 강좌의 할인은 해당 강좌의 단가에 반영해 주세요.")
    state["packages"].append({"id": entity_id, "date": sold_on, "units": units,
        "lines": lines, "discount": discount,
        "chargePolicy": state["config"]["chargePolicy"], "memo": text(command.get("memo", ""), "메모")})
    return entity_id


def _payment(state, command, today, entity_id):
    package = find(state["packages"], command.get("packageId"), "수강권")
    paid_on = day(command.get("date"))
    if paid_on > today:
        raise PaymentError("future_payment", "미래 날짜로 수납을 등록할 수 없습니다.")
    amount = integer(command.get("amount"), "수납액", 1)
    index = command.get("lineIndex")
    if index == "all":
        indices = list(range(len(package["lines"])))
        due = package_balance(state, package)["due"]
        if amount != due:
            raise PaymentError("partial_component_required", "분할 수납은 금액을 받은 강좌를 선택해 주세요.")
    else:
        indices = [integer(index, "수납 강좌", 0, len(package["lines"]) - 1)]
        due = line_balance(state, package, indices[0])["due"]
    if amount > due:
        raise PaymentError("overpayment", "수강권의 미수금보다 큰 금액입니다. 다음 수강권을 먼저 추가해 주세요.")
    method = choice(command.get("method"), ("card", "transfer", "cash", "other"), "수납 수단")
    memo = text(command.get("memo", ""), "메모")
    left = amount
    for i in indices:
        value = min(left, line_balance(state, package, i)["due"])
        if value:
            state["receipts"].append({"id": entity_id if len(indices) == 1 else f"{entity_id}:{i}", "packageId": package["id"],
                "lineIndex": i, "date": paid_on, "amount": value, "kind": "payment", "method": method, "memo": memo})
            left -= value
    return entity_id


def _refund(state, command, today, entity_id):
    package = find(state["packages"], command.get("packageId"), "수강권")
    index = integer(command.get("lineIndex"), "취소할 강좌", 0, len(package["lines"]) - 1)
    balance = line_balance(state, package, index)
    units = integer(command.get("units"), "취소 회차", 0, line_balance(state, package, index)["remainingUnits"])
    credit = refund_credit(state, package, index, units)
    amount = integer(command.get("amount"), "실제 환불액", 0, balance["paid"])
    refund_on = day(command.get("date"))
    if refund_on > today or not (units or credit or amount):
        raise PaymentError("invalid_refund", "환불 날짜와 취소 내용을 확인해 주세요.")
    if amount > max(balance["paid"] - balance["billed"] + credit, 0):
        raise PaymentError("excess_refund", "청구 감액 후 환급할 금액을 초과했습니다.")
    reason = text(command.get("memo", ""), "취소·환불 사유", required=True)
    state["receipts"].append({"id": entity_id, "packageId": package["id"], "date": refund_on,
        "amount": -amount, "kind": "refund", "method": "refund", "memo": reason,
        "lineIndex": index, "cancelledUnits": units, "creditAmount": credit})
    return entity_id


def _session(state, command, today, entity_id):
    target_day = day(command.get("date"))
    if not state["config"] or target_day < state["config"]["startsOn"]:
        raise PaymentError("before_tracking_start", "회차 관리 시작일 이후의 수업을 등록해 주세요.")
    slot = integer(command.get("slot"), "타임", 1, 6)
    status = choice(command.get("status"), ("planned", "attended", "absent", "cancelled"), "수업 상태")
    kind = choice(command.get("kind"), ("regular", "makeup", "self_study"), "수업 종류")
    if target_day > today and status != "planned":
        raise PaymentError("future_session", "미래 수업은 예정으로만 등록할 수 있습니다.")
    previous_id = command.get("sessionId")
    previous = find(state["sessions"], previous_id, "수업 회차") if previous_id else None
    if previous and any(row.get("sourceSessionId") == previous_id for row in active(state["sessions"])):
        raise PaymentError("linked_makeup", "연결된 보강을 먼저 정정해 주세요.")
    if any(row["date"] == target_day and row["slot"] == slot and row["id"] != previous_id
           for row in active(state["sessions"])):
        raise PaymentError("duplicate_session", "같은 날짜·타임의 수업 회차가 이미 있습니다.", 409)
    package = find(state["packages"], command.get("packageId"), "수강권") if kind != "self_study" else None
    index = integer(command.get("lineIndex"), "수업 강좌", 0, len(package["lines"]) - 1) if package else None
    source_id = command.get("sourceSessionId") or None
    if kind == "makeup":
        source = find(state["sessions"], source_id, "원래 결석 회차")
        if (source["status"] != "absent" or source["kind"] != "regular" or source["packageId"] != package["id"]
                or source.get("lineIndex") != index):
            raise PaymentError("invalid_makeup_source", "같은 수강권·강좌의 정규 결석 회차를 연결해 주세요.")
        if source["id"] == previous_id:
            raise PaymentError("invalid_makeup_source", "보강 자신을 원결석으로 연결할 수 없습니다.")
        if status in ("planned", "attended") and any(row.get("sourceSessionId") == source_id and row["id"] != previous_id
                and row["status"] in ("planned", "attended") for row in active(state["sessions"])):
            raise PaymentError("duplicate_makeup", "이 결석 회차에 연결된 보강이 이미 있습니다.", 409)
    elif source_id:
        raise PaymentError("invalid_makeup_source", "보강 수업에만 원결석을 연결할 수 있습니다.")
    charged = 0
    if package and status == "attended":
        charged = 1
    if package:
        remaining = line_balance(state, package, index)["remainingUnits"]
        if previous and previous.get("packageId") == package["id"] and previous.get("lineIndex") == index:
            remaining += previous["chargedUnits"]
        if charged > remaining:
            raise PaymentError("no_sessions_left", "남은 회차가 없습니다. 수강권을 추가하거나 다른 수강권을 선택해 주세요.")
    row = {"id": previous_id or entity_id, "date": target_day, "slot": slot, "kind": kind,
        "status": status, "packageId": package["id"] if package else None, "sourceSessionId": source_id,
        "lineIndex": index, "chargedUnits": charged, "memo": text(command.get("memo", ""), "메모")}
    if previous:
        previous.update(row)
    else:
        state["sessions"].append(row)
    return row["id"]


def _void(state, command, _today, _entity_id):
    reason = text(command.get("memo", ""), "정정 사유", required=True)
    target_type = choice(command.get("targetType"), ("receipt", "session"), "정정 대상")
    rows = state["receipts"] if target_type == "receipt" else state["sessions"]
    row = find(rows, command.get("targetId"), "정정 대상")
    if target_type == "receipt":
        package = find(state["packages"], row["packageId"], "수강권")
        if row["kind"] == "refund":
            refunds = [other for other in active(state["receipts"]) if other["packageId"] == row["packageId"]
                and other["lineIndex"] == row["lineIndex"] and other["kind"] == "refund"]
            if refunds[-1]["id"] != row["id"]:
                raise PaymentError("later_refund_exists", "같은 강좌의 뒤에 등록된 환불부터 정정해 주세요.")
        if row["kind"] == "payment" and line_balance(state, package, row["lineIndex"])["paid"] < row["amount"]:
            raise PaymentError("refunded_payment", "이미 환불에 사용된 수납 기록은 취소할 수 없습니다.")
    elif any(other.get("sourceSessionId") == row["id"] for other in active(state["sessions"])):
        raise PaymentError("linked_makeup", "연결된 보강을 먼저 정정해 주세요.")
    row.update(voided=True, voidReason=reason)
    return row["id"]


COMMANDS = {
    "configure": (_configure, {"lines", "startsOn"}),
    "package": (_package, {"date", "lines", "discount", "memo"}),
    "payment": (_payment, {"packageId", "lineIndex", "date", "amount", "method", "memo"}),
    "refund": (_refund, {"packageId", "lineIndex", "date", "units", "amount", "memo"}),
    "session": (_session, {"sessionId", "date", "slot", "kind", "status", "packageId", "lineIndex", "sourceSessionId", "memo"}),
    "void": (_void, {"targetType", "targetId", "memo"}),
}


def apply_command(current, command, *, today, entity_id):
    if not isinstance(command, dict) or not isinstance(command.get("action"), str) or command["action"] not in COMMANDS:
        raise PaymentError("invalid_action", "처리할 작업을 확인해 주세요.")
    handler, fields = COMMANDS[command["action"]]
    if set(command) - fields - {"action", "operationId", "baseRevision", "sid"}:
        raise PaymentError("unknown_field", "지원하지 않는 입력 항목이 있습니다.")
    state = deepcopy(current)
    entity = handler(state, command, today, entity_id)
    return state, entity
