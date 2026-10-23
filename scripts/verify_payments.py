"""Synthetic native-SQLite and dedicated-blueprint payment regressions; no app import."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.payment_evidence import project_evidence
from core.payment_repository import PaymentRepository
from core.payment_rules import PaymentError, PLANS

TODAY = "2026-10-24"
STUDENT = {"name": "결제검증 학생", "curriculum": "합성 과목", "personId": "synthetic-person"}


class PaymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="payment-verification-")
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "app.sqlite"
        self.repo = PaymentRepository(self.database)
        self.repo.initialize()
        self.sid = "synthetic-sid"

    def execute(self, action, **fields):
        if action in ("session", "refund", "payment"):
            fields.setdefault("lineIndex", 0)
        body = {"action": action, "sid": self.sid, "operationId": str(uuid.uuid4()),
                "baseRevision": self.repo.get(self.sid)["revision"], **fields}
        return self.submit(body)

    def submit(self, body):
        return self.repo.execute(self.sid, body, student=STUDENT, today=TODAY, now=TODAY+"T12:00:00+09:00", actor="synthetic-admin")

    def package(self, plan=0):
        self.execute("configure", startsOn="2026-10-01", lines=PLANS[plan]["lines"])
        return self.execute("package", date="2026-10-01", lines=PLANS[plan]["lines"], discount=0)["entityId"]

    def session(self, package, date, status="attended", **extra):
        return self.execute("session", date=date, slot=1, kind="regular", status=status, packageId=package, **extra)

    def test_approved_prices_and_snapshot(self):
        for index, total, units in ((0,450000,8),(1,600000,12),(2,700000,16),(3,150000,4),(4,250000,8)):
            self.sid = f"synthetic-{index}"
            self.package(index)
            summary = self.repo.get(self.sid)["summary"]
            self.assertEqual((summary["billed"],summary["remainingUnits"]), (total,units))
            self.execute("configure", startsOn="2026-10-01", lines=[{"label":"다음 요금", "units":1, "unitPrice":1}])
            self.assertEqual(self.repo.get(self.sid)["summary"]["billed"], total)

    def test_absence_zero_makeup_only_on_attendance(self):
        package = self.package()
        original = self.session(package,"2026-10-02","absent")["entityId"]
        self.assertEqual(self.repo.get(self.sid)["summary"]["remainingUnits"],8)
        failed = self.execute("session", date="2026-10-03", slot=1, kind="makeup", status="absent", packageId=package, sourceSessionId=original)["entityId"]
        self.execute("session", date="2026-10-04", slot=1, kind="makeup", status="attended", packageId=package, sourceSessionId=original)
        result = self.repo.get(self.sid)
        self.assertEqual(result["summary"]["remainingUnits"],7)
        self.assertEqual(next(r for r in result["account"]["sessions"] if r["id"] == failed)["status"], "absent")
        with self.assertRaisesRegex(PaymentError,"이미"):
            self.execute("session", date="2026-10-05", slot=1, kind="makeup", status="attended", packageId=package, sourceSessionId=original)

    def test_two_slots_and_no_money_double_billing(self):
        package = self.package()
        self.session(package,"2026-10-02")
        self.execute("session", date="2026-10-02", slot=2, kind="regular", status="attended", packageId=package)
        s = self.repo.get(self.sid)["summary"]
        self.assertEqual((s["remainingUnits"],s["billed"],s["due"]),(6,450000,450000))
        with self.assertRaises(PaymentError):
            self.session(package,"2026-10-02")

    def test_future_and_before_start_reject_without_write(self):
        package = self.package()
        before = self.database.read_bytes()
        for day in ("2026-10-25", "2026-09-30", "2026-02-30"):
            with self.assertRaises(PaymentError): self.session(package,day)
        self.assertEqual(self.database.read_bytes(),before)
        self.session(package,"2026-10-25","planned")
        self.assertEqual(self.repo.get(self.sid)["summary"]["remainingUnits"],8)

    def test_split_payment_and_partial_refund(self):
        package = self.package()
        self.execute("payment",packageId=package,date=TODAY,amount=200000,method="transfer")
        self.execute("payment",packageId=package,date=TODAY,amount=250000,method="card")
        self.session(package,"2026-10-02")
        self.execute("refund",packageId=package,date=TODAY,units=7,amount=393750,memo="합성 환불")
        s = self.repo.get(self.sid)["summary"]
        self.assertEqual((s["billed"],s["paid"],s["due"],s["remainingUnits"]),(56250,56250,0,0))

    def test_unpaid_cancellation_not_cash_refund(self):
        package = self.package()
        self.execute("payment",packageId=package,date=TODAY,amount=225000,method="card")
        with self.assertRaises(PaymentError):
            self.execute("refund",packageId=package,date=TODAY,units=8,amount=450000,memo="초과")
        self.execute("refund",packageId=package,date=TODAY,units=8,amount=225000,memo="전액 취소")
        s = self.repo.get(self.sid)["summary"]
        self.assertEqual((s["billed"],s["paid"],s["due"],s["remainingUnits"]),(0,0,0,0))

    def test_refund_due_can_be_paid_later(self):
        package = self.package()
        self.execute("payment",packageId=package,date=TODAY,amount=450000,method="card")
        self.execute("refund",packageId=package,date=TODAY,units=8,amount=0,memo="취소 확인")
        self.assertEqual(self.repo.get(self.sid)["summary"]["refundDue"],450000)
        self.execute("refund",packageId=package,date=TODAY,units=0,amount=450000,memo="지급 완료")
        self.assertEqual(self.repo.get(self.sid)["summary"]["refundDue"],0)

    def test_capacity_and_session_correction(self):
        package = self.package()
        first = self.session(package,"2026-10-01")["entityId"]
        for i in range(2,9): self.session(package,f"2026-10-{i:02d}")
        with self.assertRaises(PaymentError): self.session(package,"2026-10-09")
        self.execute("session",sessionId=first,date="2026-10-01",slot=1,kind="regular",status="absent",packageId=package)
        self.session(package,"2026-10-09")
        self.assertEqual(self.repo.get(self.sid)["summary"]["usedUnits"],8)

    def test_special_course_refund_is_independent(self):
        for plan, price, units in ((1,37500,4),(2,31250,8)):
            self.sid = f"special-{plan}"
            package = self.package(plan)
            self.execute("payment",packageId=package,lineIndex="all",date=TODAY,amount=600000 if plan==1 else 700000,method="card")
            self.session(package,"2026-10-02",lineIndex=1)
            self.execute("refund",packageId=package,lineIndex=1,date=TODAY,units=units-1,amount=price*(units-1),memo="특강 잔여 환불")
            result = self.repo.get(self.sid)
            self.assertEqual(result["summary"]["remainingUnits"],8)
            self.assertEqual(result["summary"]["billed"],450000+price)
            self.assertEqual(result["account"]["receipts"][-1]["creditAmount"],price*(units-1))
            with self.assertRaises(PaymentError): self.session(package,"2026-10-03",lineIndex=1)
            self.session(package,"2026-10-03",lineIndex=0)

    def test_moving_regular_session_cannot_overfill_special_course(self):
        package = self.package(1)
        original = self.session(package,"2026-10-01")["entityId"]
        for i in range(2,6): self.session(package,f"2026-10-{i:02d}",lineIndex=1)
        with self.assertRaises(PaymentError):
            self.execute("session",sessionId=original,date="2026-10-01",slot=1,kind="regular",status="attended",packageId=package,lineIndex=1)

    def test_component_makeup_and_discount_boundaries(self):
        package = self.package(1)
        original = self.session(package,"2026-10-01","absent",lineIndex=1)["entityId"]
        with self.assertRaises(PaymentError):
            self.execute("session",date="2026-10-02",slot=1,kind="makeup",status="attended",packageId=package,lineIndex=0,sourceSessionId=original)
        with self.assertRaises(PaymentError):
            self.execute("package",date=TODAY,lines=PLANS[1]["lines"],discount=1)
        with self.assertRaises(PaymentError):
            self.execute("refund",packageId=package,lineIndex=1,date=TODAY,units=0,amount=150000,memo="수업권 유지 환불 불가")

    def test_partial_special_payment_refunds_only_that_course(self):
        package = self.package(1)
        with self.assertRaises(PaymentError):
            self.execute("payment",packageId=package,lineIndex="all",date=TODAY,amount=100000,method="card")
        self.execute("payment",packageId=package,lineIndex=1,date=TODAY,amount=100000,method="card")
        self.execute("refund",packageId=package,lineIndex=1,date=TODAY,units=4,amount=100000,memo="특강 취소")
        summary = self.repo.get(self.sid)["summary"]
        self.assertEqual((summary["billed"],summary["paid"],summary["due"],summary["remainingUnits"]),(450000,0,450000,8))

    def test_split_refund_rounding_and_correction(self):
        self.execute("configure",startsOn="2026-10-01",lines=[{"label":"반올림 검증", "units":3, "unitPrice":100}])
        package = self.execute("package",date=TODAY,lines=[{"label":"반올림 검증", "units":3, "unitPrice":100}],discount=1)["entityId"]
        self.execute("payment",packageId=package,date=TODAY,amount=299,method="cash")
        ids = []
        for amount in (99,100,100):
            ids.append(self.execute("refund",packageId=package,date=TODAY,units=1,amount=amount,memo="회차별 취소")["entityId"])
        summary = self.repo.get(self.sid)["summary"]
        self.assertEqual((summary["billed"],summary["paid"],summary["remainingUnits"]),(0,0,0))
        self.execute("void",targetType="receipt",targetId=ids[-1],memo="마지막 환불 오입력")
        summary = self.repo.get(self.sid)["summary"]
        self.assertEqual((summary["billed"],summary["paid"],summary["remainingUnits"]),(100,100,1))

    def test_void_keeps_record_and_audit(self):
        package = self.package()
        session = self.session(package,"2026-10-02")["entityId"]
        self.execute("void",targetType="session",targetId=session,memo="오입력")
        result = self.repo.get(self.sid)
        self.assertTrue(result["account"]["sessions"][0]["voided"])
        self.assertEqual(result["summary"]["remainingUnits"],8)
        self.assertEqual(result["audit"][0]["action"],"void")

    def test_idempotency_precedes_revision_and_body_reuse_rejected(self):
        package = self.package()
        body = dict(action="payment",sid=self.sid,operationId=str(uuid.uuid4()),baseRevision=2,packageId=package,lineIndex=0,date=TODAY,amount=100,method="cash")
        first = self.submit(body)
        replay = self.submit(body)
        self.assertTrue(replay["replayed"])
        self.assertEqual(first["revision"],replay["revision"])
        with self.assertRaises(PaymentError): self.submit({**body,"amount":200})
        self.assertEqual(len(self.repo.get(self.sid)["account"]["receipts"]),1)

    def test_concurrent_same_command_commits_once(self):
        package = self.package()
        body = dict(action="payment",sid=self.sid,operationId=str(uuid.uuid4()),baseRevision=2,packageId=package,lineIndex=0,date=TODAY,amount=100,method="cash")
        with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(self.submit,[body,body]))
        self.assertEqual(sum(bool(r.get("replayed")) for r in results),1)
        self.assertEqual(self.repo.get(self.sid)["summary"]["paid"],100)

    def test_concurrent_different_command_same_revision(self):
        package = self.package()
        body = dict(action="payment",sid=self.sid,baseRevision=2,packageId=package,lineIndex=0,date=TODAY,amount=100,method="cash")
        def attempt(_):
            try: self.submit({**body,"operationId":str(uuid.uuid4())}); return "ok"
            except PaymentError as exc: return exc.code
        with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(attempt,range(2)))
        self.assertCountEqual(results,["ok","revision_conflict"])
        self.assertEqual(self.repo.get(self.sid)["summary"]["paid"],100)

    def test_operation_failure_rolls_back_account_and_summary(self):
        package = self.package()
        with closing(sqlite3.connect(self.database)) as con:
            con.execute("CREATE TRIGGER fail_payment BEFORE INSERT ON payment_operations BEGIN SELECT RAISE(ABORT,'injected'); END")
        before = self.repo.get(self.sid)
        with self.assertRaises(sqlite3.Error): self.execute("payment",packageId=package,date=TODAY,amount=100,method="cash")
        self.assertEqual(self.repo.get(self.sid),before)

    def test_read_does_not_create_database_or_schema(self):
        target = Path(self.temp.name)/"absent.sqlite"
        with self.assertRaises(PaymentError): PaymentRepository(target).get("s")
        self.assertFalse(target.exists())
        legacy = Path(self.temp.name)/"legacy.sqlite"
        with closing(sqlite3.connect(legacy)) as con: con.execute("CREATE TABLE legacy(value)")
        before = legacy.read_bytes()
        with self.assertRaises(PaymentError): PaymentRepository(legacy).overview()
        self.assertEqual(legacy.read_bytes(),before)

    def test_malformed_commands_never_commit(self):
        self.package()
        before = self.database.read_bytes()
        for body in ([],None,{"action":[]},{"action":{}},{"action":"configure","lines":None}):
            request = {"operationId":str(uuid.uuid4()),"baseRevision":2,**body} if isinstance(body,dict) else body
            with self.assertRaises(PaymentError): self.submit(request)
        self.assertEqual(self.database.read_bytes(),before)

    def test_corrupt_account_is_not_reset(self):
        self.package()
        with closing(sqlite3.connect(self.database)) as con:
            con.execute("UPDATE payment_accounts SET state_json='[]'")
            con.commit()
        before = self.database.read_bytes()
        with self.assertRaisesRegex(PaymentError,"원장 형식"):
            self.repo.get(self.sid)
        self.assertEqual(self.database.read_bytes(),before)

    def test_makeup_target_sid_and_legacy_aliases(self):
        source = dict(attendance={},arrivals={},absence={},extra={},makeup={"by_absence":{
            "2026-10-01":{"origin-sid":{"scheduled_makeup":{"student_id":self.sid,"makeup_date":"2026-10-03","slot":2}}}}})
        rows = project_evidence(self.sid,"2026-10",**source)
        self.assertEqual([(r["date"],r["slot"],r["kind"]) for r in rows],[("2026-10-03",2,"makeup")])
        self.assertEqual(project_evidence("origin-sid","2026-10",**source),[])

    def test_evidence_is_not_an_attendance_count(self):
        source = dict(attendance={"2026-10-12":{self.sid:1}},arrivals={"2026-10-12":{self.sid:"18:00"}},
            absence={"by_date":{"2026-10-11":[self.sid]},"by_slot":{"2026-10-11":{self.sid:[1,2]}}},
            makeup={"by_absence":{"2026-10-11":{self.sid:{"scheduledMakeup":{"status":"scheduled","makeupDate":"2026-10-25","makeupTimes":[1,2]}}}}},extra={})
        before = copy.deepcopy(source)
        rows = project_evidence(self.sid,"2026-10",**source)
        self.assertEqual(len(rows),6)
        self.assertTrue(all(r["requiresConfirmation"] for r in rows))
        self.assertEqual([r["slot"] for r in rows if r["kind"]=="attendance"],[None])
        self.assertEqual(source,before)
        self.assertEqual(project_evidence("other","2026-10",**source),[])

    def test_blueprint_auth_public_and_payload(self):
        from flask import Flask, g
        from routes import api_payments as routes
        app = Flask(__name__)
        app.config["ACADEMY_ADMIN_AUTHORIZER"] = lambda value: value == "synthetic-auth"
        @app.before_request
        def mark_public():
            from flask import request
            g.student_app_public_request = request.headers.get("X-Synthetic-Public") == "1"
        app.register_blueprint(routes.bp_api_payments)
        with patch.object(routes,"repository",return_value=self.repo), patch.object(routes,"read_admin_students",return_value=[{"id":self.sid,**STUDENT}]):
            browser = app.test_client()
            before = self.database.read_bytes()
            self.assertEqual(browser.get('/api/payments/overview').status_code,401)
            self.assertEqual(browser.get('/api/payments/overview',headers={"Authorization":"synthetic-auth","X-Synthetic-Public":"1"}).status_code,404)
            headers = {"Authorization":"synthetic-auth"}
            self.assertEqual(browser.get('/api/payments/overview',headers=headers).status_code,200)
            self.assertEqual(browser.post('/api/payments/command',headers=headers,json=[]).status_code,400)
            self.assertEqual(browser.post('/api/payments/command',headers={**headers,"Sec-Fetch-Site":"cross-site"},json={}).status_code,403)
            self.assertEqual(browser.get('/api/payments/evidence?sid=s&month=2026-13',headers=headers).status_code,400)
            self.assertEqual(self.database.read_bytes(),before)
            body = {"sid":self.sid,"operationId":str(uuid.uuid4()),"baseRevision":0,"action":"configure","lines":PLANS[0]["lines"],"startsOn":"2026-10-01"}
            response = browser.post('/api/payments/command',headers=headers,json=body)
            self.assertEqual(response.status_code,200,response.get_json())
            self.assertEqual(response.headers["Cache-Control"],"no-store")
            self.assertTrue(browser.post('/api/payments/command',headers=headers,json=body).get_json()["replayed"])
            with patch.object(routes,"read_admin_students",return_value=[]):
                self.assertTrue(browser.post('/api/payments/command',headers=headers,json=body).get_json()["replayed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
