from __future__ import annotations

import io

from flask import Flask

import routes.api_student_test_ocr as route_module


class FakeService:
    def __init__(self):
        self.calls = []

    def start_capture_session(self, **kwargs):
        self.calls.append(("session", kwargs))
        return {"token": "t" * 43, "expiresAt": "2026-08-28T10:10:00+09:00", "problemCount": 20}

    def submit_full_capture(self, **kwargs):
        self.calls.append(("capture", {**kwargs, "content": f"{len(kwargs['content'])} bytes"}))
        return {"submissionId": "ocr-1", "status": "processing"}

    def status(self, **kwargs):
        self.calls.append(("status", kwargs))
        return {
            "submissionId": kwargs["submission_id"],
            "status": "pending_teacher",
            "revision": 4,
            "answerReleased": True,
            "result": {
                "correctCount": 18,
                "incorrectCount": 1,
                "pendingCount": 1,
                "problemCount": 20,
                "score": None,
                "wrongQuestionNos": [3],
                "pendingQuestionNos": [7],
            },
            "answerUrl": "https://drive.google.com/answer",
        }

    def submit_choice(self, **kwargs):
        self.calls.append(("choice", kwargs))
        return {"submissionId": kwargs["submission_id"], "status": "processing", "revision": 5}

    def submit_answer_value_recapture(self, **kwargs):
        self.calls.append(("recapture", {**kwargs, "content": f"{len(kwargs['content'])} bytes"}))
        return {"submissionId": kwargs["submission_id"], "status": "student_action_required", "revision": 5}

    def submit_full_retake(self, **kwargs):
        self.calls.append(("retake", {**kwargs, "content": f"{len(kwargs['content'])} bytes"}))
        return {"submissionId": kwargs["submission_id"], "status": "processing", "revision": 6}

    def admin_pending(self, **kwargs):
        self.calls.append(("admin-pending", kwargs))
        return {"date": kwargs["assignment_date"], "submissions": [{"submissionId": "ocr-1"}]}

    def admin_detail(self, **kwargs):
        self.calls.append(("admin-detail", kwargs))
        return {"submissionId": kwargs["submission_id"], "status": "pending_teacher", "revision": 6}

    def admin_resolve_pending(self, **kwargs):
        self.calls.append(("admin-resolve", kwargs))
        return {"submissionId": kwargs["submission_id"], "status": "finalized", "revision": 7}

    def admin_correct_wrong(self, **kwargs):
        self.calls.append(("admin-correct", kwargs))
        return {"submissionId": kwargs["submission_id"], "status": "finalized", "revision": 8}

    def admin_solution_crop(self, **kwargs):
        self.calls.append(("admin-solution-crop", kwargs))
        return b"\x89PNG\r\n\x1a\nfixture"


def run() -> dict:
    assertions = 0
    app = Flask(__name__)
    app.json.ensure_ascii = False
    fake = FakeService()
    app.config["STUDENT_TEST_OCR_SERVICE"] = fake
    app.config["ACADEMY_ADMIN_AUTHORIZER"] = lambda authorization: authorization == "Basic test"
    app.register_blueprint(route_module.bp_api_student_test_ocr)
    original_gate = route_module._academy_allowed
    original_isolated = route_module.is_verified_isolated_server_root
    original_academy_gate = route_module.academy_network_allowed
    route_module.is_verified_isolated_server_root = lambda: True
    route_module.academy_network_allowed = lambda: False
    with app.test_request_context("/api/student-test-ocr/capabilities"):
        assert route_module._academy_allowed() is True
        assertions += 1
    route_module.is_verified_isolated_server_root = original_isolated
    route_module.academy_network_allowed = original_academy_gate
    route_module._academy_allowed = lambda: True
    try:
        client = app.test_client()
        capabilities = client.get("/api/student-test-ocr/capabilities")
        assert capabilities.status_code == 200 and capabilities.get_json()["enabled"] is True
        assert capabilities.headers["Cache-Control"].startswith("no-store")
        assertions += 2

        session = client.post(
            "/api/student-test-ocr/session",
            json={
                "sid": "student-1",
                "date": "2026-08-28",
                "testId": "test-1",
                "assignmentLabel": "단원평가 / 공수1 / Lv.3 / 1회차 / 지수",
            },
        )
        assert session.status_code == 200 and session.get_json()["problemCount"] == 20
        assert fake.calls[-1][1]["sid"] == "student-1"
        assertions += 2

        capture = client.post(
            "/api/student-test-ocr/capture",
            data={
                "token": "t" * 43,
                "requestId": "request-0001",
                "capture": (io.BytesIO(b"\xff\xd8\xff" + b"camera" * 20), "capture.jpg"),
            },
            content_type="multipart/form-data",
        )
        assert capture.status_code == 202 and capture.get_json()["submissionId"] == "ocr-1"
        assert fake.calls[-1][0] == "capture"
        assertions += 2

        status = client.get("/api/student-test-ocr/submissions/ocr-1?sid=student-1")
        payload = status.get_json()
        assert status.status_code == 200 and payload["result"]["pendingQuestionNos"] == [7]
        assert payload["answerUrl"].startswith("https://drive.google.com/")
        assert "answerKeys" not in str(payload) and "correctAnswer" not in str(payload)
        assertions += 3

        choice = client.post(
            "/api/student-test-ocr/submissions/ocr-1/choice",
            json={"sid": "student-1", "questionNo": 3, "choice": "4", "revision": 4},
        )
        assert choice.status_code == 200 and fake.calls[-1][0] == "choice"
        assertions += 1

        recapture = client.post(
            "/api/student-test-ocr/submissions/ocr-1/recapture",
            data={
                "sid": "student-1",
                "questionNo": "2",
                "revision": "5",
                "capture": (io.BytesIO(b"\xff\xd8\xff" + b"question" * 20), "question.jpg"),
            },
            content_type="multipart/form-data",
        )
        assert recapture.status_code == 200 and fake.calls[-1][0] == "recapture"
        assert fake.calls[-1][1]["question_no"] == 2
        assertions += 2

        retake = client.post(
            "/api/student-test-ocr/submissions/ocr-1/retake",
            data={
                "sid": "student-1",
                "revision": "5",
                "capture": (io.BytesIO(b"\xff\xd8\xff" + b"sheet" * 20), "retake.jpg"),
            },
            content_type="multipart/form-data",
        )
        assert retake.status_code == 202 and fake.calls[-1][0] == "retake"
        assertions += 1

        admin_blocked = client.get("/api/student-test-ocr/admin/pending?date=2026-08-28")
        assert admin_blocked.status_code == 401 and admin_blocked.headers.get("WWW-Authenticate")
        assertions += 1

        admin_headers = {"Authorization": "Basic test"}
        admin_capabilities = client.get("/api/student-test-ocr/admin/capabilities", headers=admin_headers)
        assert admin_capabilities.status_code == 200 and admin_capabilities.get_json()["enabled"] is True
        admin_pending = client.get(
            "/api/student-test-ocr/admin/pending?date=2026-08-28",
            headers=admin_headers,
        )
        assert admin_pending.status_code == 200 and fake.calls[-1][0] == "admin-pending"
        admin_detail = client.get("/api/student-test-ocr/admin/submissions/ocr-1", headers=admin_headers)
        assert admin_detail.status_code == 200 and fake.calls[-1][0] == "admin-detail"
        solution_crop = client.get(
            "/api/student-test-ocr/admin/submissions/ocr-1/solution-crop/7",
            headers=admin_headers,
        )
        assert solution_crop.status_code == 200 and solution_crop.mimetype == "image/png"
        assert solution_crop.headers["Cache-Control"] == "no-store"
        assert fake.calls[-1][0] == "admin-solution-crop"
        assertions += 6

        admin_resolve = client.post(
            "/api/student-test-ocr/admin/submissions/ocr-1/resolve",
            json={"questionNo": 7, "correct": True, "revision": 6},
            headers=admin_headers,
        )
        assert admin_resolve.status_code == 200 and fake.calls[-1][0] == "admin-resolve"
        admin_correct = client.post(
            "/api/student-test-ocr/admin/submissions/ocr-1/correct",
            json={"questionNo": 3, "revision": 7},
            headers=admin_headers,
        )
        assert admin_correct.status_code == 200 and fake.calls[-1][0] == "admin-correct"
        assertions += 2

        route_module._academy_allowed = lambda: False
        blocked = client.post(
            "/api/student-test-ocr/session",
            json={"sid": "student-1", "date": "2026-08-28", "testId": "test-1", "assignmentLabel": "x"},
        )
        assert blocked.status_code == 403 and blocked.get_json()["code"] == "academy_network_required"
        outside_capabilities = client.get("/api/student-test-ocr/capabilities")
        assert outside_capabilities.status_code == 200 and outside_capabilities.get_json()["enabled"] is False
        assertions += 2
    finally:
        route_module._academy_allowed = original_gate
        route_module.is_verified_isolated_server_root = original_isolated
        route_module.academy_network_allowed = original_academy_gate

    return {"name": "student-test-ocr-routes", "assertions": assertions, "passed": True}


if __name__ == "__main__":
    result = run()
    print(f"{result['name']} passed: {result['assertions']} assertions")
