"""Explicitly initialized SQLite tuition accounts with transactional command receipts."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

from core.payment_rules import PaymentError, account_summary, apply_command, empty_account, integer, text, price_lines, package_balance, line_balance


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


class PaymentRepository:
    def __init__(self, database):
        self.database = Path(database).absolute()

    def _connect(self, readonly=True):
        try:
            con = sqlite3.connect(f"{self.database.as_uri()}?mode={'ro' if readonly else 'rw'}",
                                  uri=True, timeout=5, isolation_level=None)
        except sqlite3.Error as exc:
            raise PaymentError("payments_not_initialized", "결제 원장 초기화가 필요합니다.", 503) from exc
        con.row_factory = sqlite3.Row
        try:
            if readonly:
                con.execute("PRAGMA query_only=ON")
            version = con.execute("SELECT version FROM payment_schema").fetchone()
            if version is None or version[0] != 1:
                raise sqlite3.DatabaseError("unsupported payment schema")
            con.execute("SELECT sid,state_json,student_json,summary_json,revision,updated_at FROM payment_accounts LIMIT 0")
            con.execute("SELECT operation_id,sid,request_hash,request_json,result_json,action,entity_id,actor,created_at,seq FROM payment_operations LIMIT 0")
        except sqlite3.Error as exc:
            con.close()
            raise PaymentError("payments_not_initialized", "결제 원장 초기화가 필요합니다.", 503) from exc
        return con

    def initialize(self):
        sql = Path(__file__).with_name("resources").joinpath("payment_schema.sql").read_text(encoding="utf-8")
        with closing(sqlite3.connect(self.database, timeout=5, isolation_level=None)) as con:
            con.executescript(sql)

    @staticmethod
    def _account(con, sid):
        row = con.execute("SELECT state_json,revision FROM payment_accounts WHERE sid=?", (sid,)).fetchone()
        if row is None:
            return empty_account(sid), 0
        try:
            state = json.loads(row["state_json"])
            if not isinstance(state, dict) or state["sid"] != sid or type(row["revision"]) is not int or row["revision"] < 1:
                raise ValueError()
            for key in ("packages", "receipts", "sessions"):
                rows = state[key]
                if not isinstance(rows, list) or any(not isinstance(item, dict) for item in rows):
                    raise ValueError()
                ids = [text(item["id"], "id", 80, required=True) for item in rows]
                if len(set(ids)) != len(ids):
                    raise ValueError()
            config = state["config"]
            if config is not None:
                price_lines(config["lines"])
                if config["chargePolicy"] != "attended":
                    raise ValueError()
            for package in state["packages"]:
                lines = price_lines(package["lines"])
                if package["units"] != sum(line["units"] for line in lines):
                    raise ValueError()
                integer(package["discount"], "discount")
                for i in range(len(lines)):
                    if any(type(value) is not int or value < 0 for value in line_balance(state, package, i).values()):
                        raise ValueError()
            packages = {item["id"]: item for item in state["packages"]}
            for entry in state["receipts"] + state["sessions"]:
                if entry.get("kind") == "self_study":
                    if entry.get("packageId") is not None or entry.get("chargedUnits") != 0:
                        raise ValueError()
                    continue
                package = packages[entry["packageId"]]
                integer(entry["lineIndex"], "lineIndex", 0, len(package["lines"]) - 1)
                if "chargedUnits" in entry:
                    integer(entry["chargedUnits"], "chargedUnits", 0, 1)
                elif entry["kind"] == "payment":
                    integer(entry["amount"], "amount", 1)
                elif entry["kind"] == "refund":
                    integer(-entry["amount"], "amount")
                    integer(entry["cancelledUnits"], "cancelledUnits")
                    integer(entry["creditAmount"], "creditAmount")
                else:
                    raise ValueError()
            account_summary(state)
        except (ValueError, TypeError, KeyError, AttributeError):
            raise PaymentError("payment_state_corrupt", "결제 원장 형식을 확인해야 합니다. 기존 기록을 보존했습니다.", 503) from None
        return state, row["revision"]

    def overview(self):
        with closing(self._connect()) as con:
            return [{"sid": row["sid"], "revision": row["revision"], "student": json.loads(row["student_json"]),
                     **json.loads(row["summary_json"])} for row in con.execute(
                "SELECT sid,revision,student_json,summary_json FROM payment_accounts ORDER BY sid")]

    def get(self, sid):
        with closing(self._connect()) as con:
            con.execute("BEGIN")
            state, revision = self._account(con, sid)
            audit = [dict(row) for row in con.execute(
                "SELECT operation_id AS operationId,action,entity_id AS entityId,actor,created_at AS createdAt,request_json "
                "FROM payment_operations WHERE sid=? ORDER BY seq DESC LIMIT 100", (sid,))]
            for entry in audit:
                request = json.loads(entry.pop("request_json"))
                entry["details"] = {key: value for key, value in request.items() if key not in ("operationId", "baseRevision", "sid")}
            con.execute("COMMIT")
            return {"account": state, "revision": revision, "summary": account_summary(state), "audit": audit}

    def replay(self, sid, command):
        """Return a committed receipt even after its student leaves the active roster."""
        operation_id = command.get("operationId")
        if not isinstance(operation_id, str):
            return None
        with closing(self._connect()) as con:
            row = con.execute("SELECT sid,request_hash,result_json FROM payment_operations WHERE operation_id=?", (operation_id,)).fetchone()
            if row is None:
                return None
            try:
                request_hash = hashlib.sha256(encode(command).encode("utf-8")).hexdigest()
            except (TypeError, ValueError, UnicodeError):
                raise PaymentError("invalid_body", "저장 내용을 확인해 주세요.") from None
            if row["sid"] != sid or row["request_hash"] != request_hash:
                raise PaymentError("idempotency_conflict", "같은 작업 번호로 다른 내용을 저장할 수 없습니다.", 409)
            return {**json.loads(row["result_json"]), "replayed": True}

    def execute(self, sid, command, *, student, today, now, actor):
        if not isinstance(command, dict):
            raise PaymentError("invalid_body", "저장 내용을 확인해 주세요.")
        text(sid, "학생 식별 번호", 120, required=True)
        if "sid" in command and command["sid"] != sid:
            raise PaymentError("sid_mismatch", "저장할 학생이 일치하지 않습니다.")
        operation_id = text(command.get("operationId"), "작업 번호", 80, required=True)
        try:
            uuid.UUID(operation_id)
        except ValueError:
            raise PaymentError("invalid_operation", "작업 번호 형식이 올바르지 않습니다.") from None
        base = integer(command.get("baseRevision"), "수정 번호")
        try:
            request_hash = hashlib.sha256(encode(command).encode("utf-8")).hexdigest()
        except (ValueError, TypeError, UnicodeError):
            raise PaymentError("invalid_body", "저장 내용의 숫자와 문자를 확인해 주세요.") from None
        with closing(self._connect(readonly=False)) as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                prior = con.execute("SELECT sid,request_hash,result_json FROM payment_operations WHERE operation_id=?",
                                    (operation_id,)).fetchone()
                if prior:
                    if prior["sid"] != sid or prior["request_hash"] != request_hash:
                        raise PaymentError("idempotency_conflict", "같은 작업 번호로 다른 내용을 저장할 수 없습니다.", 409)
                    result = json.loads(prior["result_json"])
                    con.execute("COMMIT")
                    return {**result, "replayed": True}
                state, revision = self._account(con, sid)
                if base != revision:
                    raise PaymentError("revision_conflict", "다른 화면에서 변경되었습니다. 새로 불러온 뒤 다시 저장해 주세요.", 409)
                state, entity_id = apply_command(state, command, today=today, entity_id=str(uuid.uuid4()))
                summary = account_summary(state)
                result = {"ok": True, "sid": sid, "revision": revision + 1, "entityId": entity_id, "summary": summary}
                con.execute("INSERT INTO payment_accounts(sid,state_json,student_json,summary_json,revision,updated_at) "
                    "VALUES(?,?,?,?,?,?) ON CONFLICT(sid) DO UPDATE SET state_json=excluded.state_json, "
                    "student_json=excluded.student_json,summary_json=excluded.summary_json,revision=excluded.revision,updated_at=excluded.updated_at",
                    (sid, encode(state), encode(student), encode(summary), revision + 1, now))
                con.execute("INSERT INTO payment_operations(operation_id,sid,request_hash,request_json,result_json,action,entity_id,actor,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?)", (operation_id, sid, request_hash, encode(command), encode(result),
                    command["action"], entity_id, actor, now))
                con.execute("COMMIT")
                return result
            except Exception:
                con.execute("ROLLBACK")
                raise
