from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor

from flask import Flask

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import routes.api_school_calendar as api_school_calendar


REVISION_HEADER = "X-School-Calendar-Revision"


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def independent_revision(document: dict) -> str:
    raw = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def read_json(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def make_app() -> Flask:
    app = Flask("verify-school-calendar-revision")
    app.register_blueprint(api_school_calendar.bp_api_school_calendar)
    app.config.update(TESTING=True)
    return app


def verify_route_boundary() -> None:
    basic_source = (ROOT / "routes" / "api_basic.py").read_text(encoding="utf-8")
    app_source = (ROOT / "app.py").read_text(encoding="utf-8")
    dedicated_source = (ROOT / "routes" / "api_school_calendar.py").read_text(
        encoding="utf-8"
    )

    check(
        "/api/school-calendar" not in basic_source
        and "school_calendar_store" not in basic_source,
        "api_basic must not retain the extracted school-calendar route or store imports",
    )
    check(
        'Blueprint("api_school_calendar"' in dedicated_source
        and '@bp_api_school_calendar.route("/api/school-calendar"' in dedicated_source,
        "the dedicated blueprint owns the school-calendar route",
    )
    check(
        "from routes.api_school_calendar import bp_api_school_calendar" in app_source
        and "app.register_blueprint(bp_api_school_calendar)" in app_source,
        "app.py explicitly imports and registers the dedicated blueprint",
    )


def run_sequential_contract(app: Flask, path: pathlib.Path) -> None:
    initial = {
        "version": 2,
        "activeYear": "2026",
        "years": {"2026": {"activeSemester": "1", "schools": {"가람고": {}}}},
    }
    path.write_text(json.dumps(initial, ensure_ascii=False), encoding="utf-8")

    client = app.test_client()
    first = client.get("/api/school-calendar")
    check(first.status_code == 200, "calendar GET succeeds")
    check(first.get_json() == initial, "calendar GET preserves the document")
    initial_revision = first.headers.get(REVISION_HEADER, "")
    check(
        initial_revision == independent_revision(initial),
        "GET revision matches an independent canonical JSON hash",
    )
    check(first.headers.get("ETag") == f'"{initial_revision}"', "GET exposes matching ETag")

    missing_before = path.read_bytes()
    missing = client.post("/api/school-calendar", json={"version": 2})
    check(missing.status_code == 428, "missing revision is rejected")
    check(path.read_bytes() == missing_before, "missing revision makes no write")
    check(
        missing.headers.get(REVISION_HEADER) == initial_revision,
        "428 returns the current revision",
    )

    winner = {
        "version": 2,
        "activeYear": "2026",
        "years": {"2026": {"activeSemester": "2", "schools": {"가람고": {"common": {"textbook": "수학"}}}}},
    }
    saved = client.post(
        "/api/school-calendar",
        json=winner,
        headers={"If-Match": f'W/"{initial_revision}"'},
    )
    check(saved.status_code == 200, "matching weak quoted revision saves")
    check(saved.get_json() == winner, "successful POST keeps the legacy response shape")
    winner_revision = saved.headers.get(REVISION_HEADER, "")
    check(winner_revision == independent_revision(winner), "POST returns the saved revision")
    check(read_json(path) == winner, "successful POST persists exactly one document")

    stale_before = path.read_bytes()
    stale = client.post(
        "/api/school-calendar",
        json={"version": 2, "activeYear": "stale"},
        headers={"If-Match": initial_revision},
    )
    check(stale.status_code == 409, "stale revision is rejected")
    check(path.read_bytes() == stale_before, "stale revision leaves the file byte-for-byte unchanged")
    check(
        stale.headers.get(REVISION_HEADER) == winner_revision,
        "409 returns the winning revision",
    )

    invalid_before = path.read_bytes()
    invalid = client.post(
        "/api/school-calendar",
        json=["not", "a", "document"],
        headers={"If-Match": winner_revision},
    )
    check(invalid.status_code == 400, "non-object calendar is rejected")
    check(path.read_bytes() == invalid_before, "invalid shape makes no write")


def run_competing_writers(app: Flask, path: pathlib.Path) -> None:
    baseline = {"version": 2, "activeYear": "2027", "years": {}}
    path.write_text(json.dumps(baseline, ensure_ascii=False), encoding="utf-8")
    revision = app.test_client().get("/api/school-calendar").headers[REVISION_HEADER]
    payloads = [
        {"version": 2, "activeYear": "2027", "years": {"2027": {"writer": "A"}}},
        {"version": 2, "activeYear": "2027", "years": {"2027": {"writer": "B"}}},
    ]
    barrier = threading.Barrier(2)

    def write(payload: dict) -> tuple[int, dict, str]:
        with app.test_client() as client:
            barrier.wait(timeout=5)
            response = client.post(
                "/api/school-calendar",
                json=payload,
                headers={"If-Match": revision},
            )
            return (
                response.status_code,
                response.get_json(),
                response.headers.get(REVISION_HEADER, ""),
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, payloads))

    statuses = sorted(result[0] for result in results)
    check(statuses == [200, 409], "two same-revision writers produce one winner and one conflict")
    persisted = read_json(path)
    check(persisted in payloads, "the persisted document is exactly one contender")
    persisted_revision = independent_revision(persisted)
    check(
        all(result[2] == persisted_revision for result in results),
        "winner and loser both observe the persisted revision",
    )
    loser = next(result for result in results if result[0] == 409)
    check(loser[1].get("code") == "school_calendar_conflict", "loser receives conflict code")


def run_unavailable_store(app: Flask, path: pathlib.Path) -> None:
    path.write_text("{broken", encoding="utf-8")
    before = path.read_bytes()
    response = app.test_client().get("/api/school-calendar")
    check(response.status_code == 503, "malformed store fails closed")
    check(path.read_bytes() == before, "malformed store is not repaired or overwritten")


def main() -> int:
    verify_route_boundary()
    original_path = api_school_calendar.CAL_PATH
    try:
        with tempfile.TemporaryDirectory(prefix="school-calendar-revision-") as tmp:
            path = pathlib.Path(tmp) / "school_calendar.json"
            api_school_calendar.CAL_PATH = path
            app = make_app()
            run_sequential_contract(app, path)
            run_competing_writers(app, path)
            run_unavailable_store(app, path)
    finally:
        api_school_calendar.CAL_PATH = original_path

    print(
        "school calendar revision checks passed: independent hash, 428, 409, "
        "two-writer race, fail-closed store, dedicated route boundary"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
