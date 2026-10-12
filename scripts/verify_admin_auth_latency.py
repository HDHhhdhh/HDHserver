"""Synthetic-only admin auth regression and opt-in source/KDF benchmark.

No app/core.paths imports, network listener, production credential reads, or
runtime data paths. A proposed OS-temp source can be selected with --source-root.
"""
from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import statistics
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace
from unittest import mock

from werkzeug.security import generate_password_hash

ROOT = Path(__file__).resolve().parents[1]
USERNAME_KEY = "ACADEMY_ADMIN_USERNAME"
HASH_KEY = "ACADEMY_ADMIN_PASSWORD_HASH"
USER = "검증관리자"
PASSWORD = "synthetic-only-password:한글"
CHECKS = 0


def check(condition: bool, message: str) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        raise AssertionError(message)


def header(username: str = USER, password: str = PASSWORD) -> str:
    return "Basic " + base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")


def config(password: str = PASSWORD, username: str = USER) -> dict[str, str]:
    # Small parameters are solely behavioral fixtures; production params are untouched.
    return {USERNAME_KEY: username, HASH_KEY: generate_password_hash(password, method="pbkdf2:sha256:1000")}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load explicitly selected source")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class CountedKdf:
    def __init__(self, real_check, before=None):
        self.real_check = real_check
        self.before = before
        self.calls = 0
        self.lock = threading.Lock()

    def __call__(self, stored: str, supplied: str) -> bool:
        with self.lock:
            self.calls += 1
        if self.before is not None:
            self.before(stored, supplied)
        return self.real_check(stored, supplied)


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class ObservedClock:
    """Observe concurrent lookup entry externally while the KDF is blocked."""
    def __init__(self, workers: int):
        self.calls = 0
        self.lock = threading.Lock()
        self.all_looked_up = threading.Event()
        self.workers = workers

    def __call__(self):
        with self.lock:
            self.calls += 1
            if self.calls >= self.workers:
                self.all_looked_up.set()
        return time.monotonic()


@contextmanager
def fixture(auth, Cache, *, clock=None, before=None):
    cache = Cache() if clock is None else Cache(clock=clock)
    counted = CountedKdf(auth.check_password_hash, before)
    with mock.patch.object(auth, "_SUCCESS_CACHE", cache, create=True), mock.patch.object(
        auth, "check_password_hash", counted
    ):
        yield cache, counted


def verify_semantics(auth, Cache):
    values = config()
    with fixture(auth, Cache) as (_, kdf):
        check(auth.verify_admin_authorization(header(), values), "literal valid credentials succeed")
        check(auth.verify_admin_authorization(header(), values), "literal repeated credentials succeed")
        check(kdf.calls == 1, "two successes must perform exactly one real KDF")
        # Same parsed credentials, exact existing Basic parser semantics.
        for encoded in ("bAsIc " + header()[6:], " \t" + header() + " \t", "Basic\t" + header()[6:]):
            check(auth.verify_admin_authorization(encoded, values), "allowed Basic scheme/whitespace unchanged")
        check(kdf.calls == 1, "equivalent parsed headers reuse only the exact successful credentials")
        for wrong in (header(password="wrong"), header(username="other"), header(password=PASSWORD + " ")):
            before = kdf.calls
            check(not auth.verify_admin_authorization(wrong, values), "wrong password/username stays rejected")
            check(not auth.verify_admin_authorization(wrong, values), "repeated wrong credentials stay rejected")
            check(kdf.calls == before + 2, "failures never skip their independent KDF")
        invalid = [
            None, "", "Bearer anything", "Basic", "Basic !!!",
            "Basic " + base64.b64encode(b"\xff:pw").decode(),
            "Basic " + base64.b64encode(b"user-without-colon").decode(),
            header(username=""), header(username="bad\nname"), header(username="bad\rname"),
            header(username="bad\x00name"), header(password="bad\npw"),
            header(password="bad\rpw"), header(password="bad\x00pw"),
        ]
        before = kdf.calls
        for encoded in invalid:
            check(not auth.verify_admin_authorization(encoded, values), "literal malformed credentials rejected")
        check(kdf.calls == before, "malformed credentials do not enter the KDF")
        spaced = {USERNAME_KEY: " \t" + USER + " ", HASH_KEY: " \t" + values[HASH_KEY] + " "}
        check(auth.verify_admin_authorization(header(), spaced), "existing configured-value strip semantics unchanged")
        check(kdf.calls == before, "normalized identical config reuses success")
        snapshot = json.dumps(values, sort_keys=True)
        auth.verify_admin_authorization(header(), values)
        check(json.dumps(values, sort_keys=True) == snapshot, "verification never mutates configuration input")


def verify_configuration(auth, Cache):
    values = config()
    with fixture(auth, Cache) as (_, kdf), mock.patch.object(os, "environ", values):
        check(auth.verify_admin_authorization(header()), "fresh synthetic environment succeeds")
        values[HASH_KEY] = generate_password_hash("new-password", method="pbkdf2:sha256:1000")
        check(not auth.verify_admin_authorization(header()), "hash rotation immediately rejects old password")
        new_header = header(password="new-password")
        check(auth.verify_admin_authorization(new_header), "rotated password succeeds")
        before = kdf.calls
        values[HASH_KEY] = generate_password_hash("new-password", method="pbkdf2:sha256:1000")
        check(auth.verify_admin_authorization(new_header), "same-password hash rotation succeeds after recheck")
        check(kdf.calls == before + 1, "salt/hash change invalidates warm success")
        values[USERNAME_KEY] = "new-admin"
        check(not auth.verify_admin_authorization(new_header), "username change immediately rejects old username")
        new_header = header("new-admin", "new-password")
        check(auth.verify_admin_authorization(new_header), "new username and password succeed")
        for missing in (USERNAME_KEY, HASH_KEY):
            old = values.pop(missing)
            before = kdf.calls
            check(not auth.verify_admin_authorization(None), "missing config invalidates even without a header")
            check(not auth.verify_admin_authorization(new_header), "missing config fails closed")
            check(kdf.calls == before, "missing config does not enter KDF")
            values[missing] = old
            check(auth.verify_admin_authorization(new_header), "restored config must be rechecked")
            check(kdf.calls == before + 1, "removed config cannot resurrect an earlier cached success")
        old_hash = values[HASH_KEY]
        for malformed in ("not-a-hash", "pbkdf2:sha256:bad$salt$hash", "unsupported$salt$hash", 17, ""):
            values[HASH_KEY] = malformed
            check(not auth.verify_admin_authorization(new_header), "malformed hash/config fails closed")
            values[HASH_KEY] = old_hash
            before = kdf.calls
            check(auth.verify_admin_authorization(new_header), "valid restored hash succeeds")
            check(kdf.calls == before + 1, "malformed config clears previously accepted credentials")
        before = kdf.calls
        values[USERNAME_KEY] = 17
        check(not auth.verify_admin_authorization(new_header), "non-string username fails closed")
        values[USERNAME_KEY] = "new-admin"
        check(auth.verify_admin_authorization(new_header), "restored username succeeds")
        check(kdf.calls == before + 1, "non-string username invalidates prior success")

    # Mutation during the KDF, without a second request, must revoke this result.
    values = config()
    def rotate_during_check(*_):
        values.pop(HASH_KEY, None)
    with fixture(auth, Cache, before=rotate_during_check) as (_, kdf):
        check(not auth.verify_admin_authorization(header(), values), "KDF-time config revocation rejects current request")
        check(kdf.calls == 1, "revocation fixture actually executed one KDF")


def verify_unicode_configuration(auth, Cache):
    values = config()
    with fixture(auth, Cache) as (_, kdf):
        check(auth.verify_admin_authorization(header(), values), "Unicode config fixture warms a valid success")
        for key in (USERNAME_KEY, HASH_KEY):
            original = values[key]
            for malformed in ("\ud800", "\udfff", "valid-prefix-\ud800", "\udfff-valid-suffix"):
                values[key] = malformed
                before = kdf.calls
                check(not auth.verify_admin_authorization(header(), values), "unpaired surrogate config fails closed without exception")
                check(not auth.verify_admin_authorization(None, values), "unpaired surrogate config invalidates with malformed header")
                check(kdf.calls == before, "unencodable config never enters the password KDF")
                values[key] = original
                check(auth.verify_admin_authorization(header(), values), "restored UTF-8 config is verified again")
                check(kdf.calls == before + 1, "unpaired surrogate config cannot resurrect a warm success")
    for key in (USERNAME_KEY, HASH_KEY):
        values = config()
        def corrupt_during_check(*_):
            values[key] = "\ud800"
        with fixture(auth, Cache, before=corrupt_during_check) as (_, kdf):
            check(not auth.verify_admin_authorization(header(), values), "KDF-time surrogate corruption revokes current result")
            check(kdf.calls == 1, "Unicode corruption fixture executed the original password KDF")
    cache = Cache()
    generation = cache.observe_configuration("\ud800", "synthetic-hash")
    check(not cache.verify(generation, "fixture-user", "fixture-password", lambda: True), "unencodable configuration cannot populate helper successes")
    generation = cache.observe_configuration("fixture-user", "synthetic-hash")
    check(not cache.verify(generation, "\ud800", "fixture-password", lambda: True), "unencodable helper credential HMAC fails closed")


def verify_ttl(auth, Cache):
    values = config()
    clock = Clock()
    def costly_check(*_):
        clock.now += 2.0
    with fixture(auth, Cache, clock=clock, before=costly_check) as (_, kdf):
        check(auth.verify_admin_authorization(header(), values), "TTL fixture accepts valid credentials")
        clock.now = 105.0
        check(auth.verify_admin_authorization(header(), values), "TTL begins after expensive verification completes")
        clock.now = 106.999
        check(auth.verify_admin_authorization(header(), values), "success valid strictly before completion plus five seconds")
        check(kdf.calls == 1, "warm hits do not repeat KDF")
        clock.now = 107.0
        check(auth.verify_admin_authorization(header(), values), "exact TTL boundary triggers verification")
        check(kdf.calls == 2, "hits do not extend the fixed five-second TTL")
        clock.now = 115.0
        check(auth.verify_admin_authorization(header(), values), "later expiry triggers verification")
        check(kdf.calls == 3, "expired results never authorize without KDF")


def verify_concurrency(auth, Cache):
    for encoded, expected in ((header(), True), (header(password="wrong"), False), (header(username="wrong"), False)):
        workers = 4
        observed = ObservedClock(workers)
        release = threading.Event()
        entered = threading.Event()
        start = threading.Barrier(workers + 1)
        failed_waiters = threading.Barrier(workers - 1)
        attempt_lock = threading.Lock()
        attempts = [0]
        def blocked_check(*_):
            with attempt_lock:
                attempts[0] += 1
                first = attempts[0] == 1
            entered.set()
            if not release.wait(5):
                raise AssertionError("concurrent KDF release timed out")
            if not expected and not first:
                # All failed waiters must run independent KDFs concurrently.
                failed_waiters.wait(5)
        def request():
            start.wait(5)
            return auth.verify_admin_authorization(encoded, values)
        values = config()
        with fixture(auth, Cache, clock=observed, before=blocked_check) as (_, kdf), ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(request) for _ in range(workers)]
            try:
                start.wait(5)
                check(entered.wait(5), "real KDF begins during simultaneous calls")
                check(observed.all_looked_up.wait(5), "all concurrent calls entered cache while KDF was blocked")
                check(kdf.calls == 1, "same-key cold calls share one in-flight check")
            finally:
                release.set()
            check([f.result(timeout=8) for f in futures] == [expected] * workers, "concurrent outcomes match independent literals")
            check(kdf.calls == (1 if expected else workers), "only successes are shared; each failed caller performs KDF")

    # Existing waiters and owner lose authority on rotate/revoke.
    for revoke in (False, True):
        values = config()
        observed = ObservedClock(2)
        release = threading.Event()
        entered = threading.Event()
        def blocked_old(_stored, supplied):
            if supplied == PASSWORD:
                entered.set()
                if not release.wait(5):
                    raise AssertionError("rotation KDF release timed out")
        with fixture(auth, Cache, clock=observed, before=blocked_old) as (_, kdf), ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(auth.verify_admin_authorization, header(), values) for _ in range(2)]
            try:
                check(entered.wait(5) and observed.all_looked_up.wait(5), "old owner and waiter overlap before rotate/revoke")
                if revoke:
                    old_hash = values.pop(HASH_KEY)
                    check(not auth.verify_admin_authorization(None, values), "revocation takes effect while old KDF is in flight")
                else:
                    values[HASH_KEY] = generate_password_hash("new-password", method="pbkdf2:sha256:1000")
                    check(auth.verify_admin_authorization(header(password="new-password"), values), "new config authenticates independently of old in-flight check")
            finally:
                release.set()
            check([f.result(timeout=8) for f in futures] == [False, False], "old owner and waiter both fail after rotate/revoke")
            if revoke:
                values[HASH_KEY] = old_hash
                before = kdf.calls
                check(auth.verify_admin_authorization(header(), values), "restored config succeeds via fresh verification")
                check(kdf.calls == before + 1, "stale in-flight success cannot repopulate restored config")

    # Unexpected errors retain prior exception behavior and always unblock waiters.
    values = config()
    calls = [0]
    real_check = auth.check_password_hash
    def first_error(stored, supplied):
        calls[0] += 1
        if calls[0] == 1:
            raise RuntimeError("synthetic-checker-error")
        return real_check(stored, supplied)
    with mock.patch.object(auth, "_SUCCESS_CACHE", Cache(), create=True), mock.patch.object(auth, "check_password_hash", first_error):
        try:
            auth.verify_admin_authorization(header(), values)
        except RuntimeError:
            check(True, "unexpected KDF exception preserves prior propagation")
        else:
            check(False, "unexpected KDF exception cannot become authorization")
        check(auth.verify_admin_authorization(header(), values), "exception leaves no stuck in-flight record")
        check(calls[0] == 2, "exception was not cached")


def verify_pending_beyond_success_ttl(Cache):
    observed = ObservedClock(2)
    cache = Cache(ttl_seconds=0.025, clock=observed)
    generation = cache.observe_configuration("fixture-user", "fixture-hash")
    release, entered, duplicate = (threading.Event() for _ in range(3))
    lock, calls = threading.Lock(), [0]

    def blocked_check():
        with lock:
            calls[0] += 1
            (entered if calls[0] == 1 else duplicate).set()
        if not release.wait(5):
            raise AssertionError("long pending KDF release timed out")
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        owner = pool.submit(cache.verify, generation, "fixture-user", "fixture-password", blocked_check)
        waiter = None
        try:
            check(entered.wait(2), "long pending owner begins")
            waiter = pool.submit(cache.verify, generation, "fixture-user", "fixture-password", blocked_check)
            check(observed.all_looked_up.wait(2), "long pending waiter reaches the shared cache")
            check(not duplicate.wait(0.15), "positive TTL expiry does not duplicate a pending KDF")
        finally:
            release.set()
        check(owner.result(timeout=3) is True and waiter.result(timeout=3) is True, "long pending callers receive the same completed success")
        check(calls[0] == 1, "pending ownership lasts until completion independently of success TTL")


def verify_bounds_and_retention(Cache):
    cache = Cache()
    generation = cache.observe_configuration("synthetic-config-user", "synthetic-config-hash")
    count = [0]
    def successful():
        count[0] += 1
        return True
    for index in range(66):
        check(cache.verify(generation, "fixture-user", f"fixture-password-{index}", successful), "synthetic bounded-cache insertion succeeds")
    check(count[0] == 66, "all distinct credentials require independent verification")
    cache.verify(generation, "fixture-user", "fixture-password-65", successful)
    check(count[0] == 66, "newest of the 64 retained successes is reused")
    cache.verify(generation, "fixture-user", "fixture-password-0", successful)
    check(count[0] == 67, "oldest success is evicted at the literal 64-entry bound")
    check(len(cache._successes) <= 64, "stored successes never exceed literal capacity")
    check(all(isinstance(k, bytes) and len(k) == 32 and isinstance(v, float) for k, v in cache._successes.items()), "stored successes contain only keyed digests and expiries")
    check(isinstance(cache._configuration, bytes) and len(cache._configuration) == 32, "configuration is retained as a keyed digest")
    # Privacy/bound inspection is complementary to the externally observed races.
    retained = repr(vars(cache))
    check("fixture-password" not in retained and "synthetic-config-hash" not in retained and "synthetic-config-user" not in retained, "cache fields contain no plaintext credentials or hash config")

    second = Cache()
    check(second._secret != cache._secret and len(cache._secret) == 32, "new process-local cache uses an independent 256-bit secret")
    gen2 = second.observe_configuration("synthetic-config-user", "synthetic-config-hash")
    before = count[0]
    second.verify(gen2, "fixture-user", "fixture-password-65", successful)
    check(count[0] == before + 1, "no successes are shared between separate cache instances")
    before = count[0]
    second.verify(gen2, "ab", "c", successful)
    second.verify(gen2, "a", "bc", successful)
    check(count[0] == before + 2, "credential framing prevents concatenation ambiguity")

    # Nine distinct checks overlap even when only eight in-flight records fit.
    cache = Cache()
    generation = cache.observe_configuration("synthetic-config-user", "synthetic-config-hash")
    all_entered = threading.Event()
    release = threading.Event()
    lock = threading.Lock()
    entered = [0]
    def blocked():
        with lock:
            entered[0] += 1
            if entered[0] == 9:
                all_entered.set()
        if not release.wait(5):
            raise AssertionError("distinct KDF release timed out")
        return True
    with ThreadPoolExecutor(max_workers=9) as pool:
        futures = [pool.submit(cache.verify, generation, "fixture-user", f"distinct-{i}", blocked) for i in range(9)]
        try:
            check(all_entered.wait(5), "unrelated checks overlap; saturation never serializes all KDFs globally")
            check(len(cache._inflight) == 8, "stored in-flight records retain the literal eight-entry bound")
            check(all(isinstance(k, bytes) and len(k) == 32 and isinstance(v, threading.Event) for k, v in cache._inflight.items()), "in-flight records contain only keyed digests and events")
        finally:
            release.set()
        check([f.result(timeout=8) for f in futures] == [True] * 9, "saturation falls back to full verification without denial")
    check(not cache._inflight, "completed checks retain no in-flight records")


def verify_existing_boundaries(auth, support: Path):
    from scripts import verify_admin_access_and_student_logs as legacy
    from scripts.student_mobile_app_checks import admin_auth_contract
    with mock.patch.object(legacy, "check", check):
        legacy.run_admin_basic_auth_checks()
    count = [0]
    def adapter(counter, condition, message):
        check(condition, "pre-existing mobile auth: " + message)
        counter[0] += 1
    admin_auth_contract.run_admin_auth_contract(count, adapter, support)
    check(auth.ADMIN_AUTH_CHALLENGE == 'Basic realm="Academy Admin", charset="UTF-8"', "challenge literal unchanged")
    external = SimpleNamespace(remote_addr="203.0.113.8", headers={})
    local = SimpleNamespace(remote_addr="127.0.0.1", headers={})
    for path in ("/api/students", "/api/progress", "/api/logs", "/api/updates", "/api/tests"):
        check(auth.external_admin_api_auth_required(path, external), "literal external protected API requires auth")
        check(not auth.external_admin_api_auth_required(path, local), "existing loopback API policy unchanged")
    for path in (
        "/api/announce-ack", "/api/announce-submit", "/api/feedback", "/api/get-url",
        "/api/kollus/lms-callback", "/api/ping", "/api/student/bootstrap", "/api/watch-status",
        "/api/auth/login", "/api/mobile/student/homework",
    ):
        check(not auth.external_admin_api_auth_required(path, external), "literal existing exemption unchanged")

    # Actual page hook uses the proposed verifier, rather than a always-true test authorizer.
    from flask import Flask
    from routes.pages import bp_pages
    values = config()
    with tempfile.TemporaryDirectory(prefix="verify-admin-auth-page-") as directory:
        static = Path(directory)
        for name in ("admin.html", "tests.html", "all.html", "index.html"):
            (static / name).write_text("<!doctype html><p>합성 검증</p>", encoding="utf-8")
        app = Flask("verify-admin-auth-latency-page", static_folder=str(static), static_url_path="")
        app.config["ACADEMY_ADMIN_AUTHORIZER"] = lambda value: auth.verify_admin_authorization(value, values)
        app.register_blueprint(bp_pages)
        with app.test_client() as client:
            for path in ("/admin", "/admin.html", "/tests", "/tests.html", "/students"):
                missing = client.get(path)
                check(missing.status_code == 401, "real page hook rejects missing credentials")
                check(missing.headers.get("WWW-Authenticate") == 'Basic realm="Academy Admin", charset="UTF-8"', "page challenge header literal unchanged")
                check(missing.headers.get("Cache-Control") == "no-store", "page failure cache header unchanged")
                check(client.get(path, headers={"Authorization": header()}).status_code == 200, "valid header passes real page hook")
                check(client.get(path, headers={"Authorization": header(password="wrong")}).status_code == 401, "wrong header never shares a warm page success")


def protected_hashes(source: str) -> dict[str, str]:
    names = {
        "_configured_value", "_basic_credentials", "admin_network_allowed",
        "external_admin_api_auth_required", "ADMIN_AUTH_CHALLENGE",
        "ADMIN_USERNAME_ENV", "ADMIN_PASSWORD_HASH_ENV",
        "EXTERNAL_ADMIN_API_EXEMPT_PATHS", "EXTERNAL_ADMIN_API_EXEMPT_PREFIXES", "__all__",
    }
    hashes = {}
    for node in ast.parse(source).body:
        name = getattr(node, "name", "") or getattr(getattr(node, "target", None), "id", "")
        if isinstance(node, ast.Assign) and node.targets and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        if name in names:
            segment = ast.get_source_segment(source, node)
            hashes[name] = hashlib.sha256(segment.encode("utf-8")).hexdigest()
    return hashes


def verify_source_preservation(source: Path, baseline: Path | None):
    text = source.read_text("utf-8")
    for expression in (
        'hmac.compare_digest(username.encode("utf-8"), expected_username.encode("utf-8"))',
        "check_password_hash(password_hash, password)",
    ):
        check(expression in text, "original exact username comparison and password-hash call preserved")
    if baseline is not None:
        check(protected_hashes(text) == protected_hashes(baseline.read_text("utf-8")), "all protected functions/config/exemption/challenge source hashes unchanged")
    return protected_hashes(text)


def summary(samples: list[float]):
    ordered = sorted(samples)
    return {
        "median_ms": round(statistics.median(samples), 4),
        "p95_ms": round(ordered[math.ceil(len(ordered) * .95) - 1], 4),
        "samples_ms": [round(value, 4) for value in samples],
    }


def benchmark(auth, Cache, baseline: Path):
    before = load_module("admin_auth_latency_uncached_baseline", baseline)
    result = {
        "label": "synthetic source/KDF only; excludes HTTP, data I/O, browser layout/paint",
        "warmup": 1, "repeat_samples": 12, "cold_concurrent_workers": 4, "methods": {},
        "source_sha256": {
            "before": hashlib.sha256(baseline.read_bytes()).hexdigest(),
            "after": hashlib.sha256(Path(auth.__file__).read_bytes()).hexdigest(),
            "cache": hashlib.sha256(Path(sys.modules["core.admin_auth_cache"].__file__).read_bytes()).hexdigest(),
        },
    }
    for method in ("scrypt:32768:8:1", "pbkdf2:sha256:1000000"):
        values = {USERNAME_KEY: USER, HASH_KEY: generate_password_hash(PASSWORD, method=method)}
        method_result = {}
        for label, module in (("before", before), ("after", auth)):
            with fixture(module, Cache) as (_, counted):
                started = time.perf_counter()
                check(module.verify_admin_authorization(header(), values), "benchmark first request valid")
                cold_first = (time.perf_counter() - started) * 1000
                counted.calls = 0
                samples = []
                for _ in range(12):
                    started = time.perf_counter()
                    check(module.verify_admin_authorization(header(), values), "benchmark repeated result literal True")
                    samples.append((time.perf_counter() - started) * 1000)
                repeats_kdf = counted.calls
            with fixture(module, Cache) as (_, counted), ThreadPoolExecutor(max_workers=4) as pool:
                barrier = threading.Barrier(5)
                def concurrent():
                    barrier.wait(5)
                    return module.verify_admin_authorization(header(), values)
                started = time.perf_counter()
                futures = [pool.submit(concurrent) for _ in range(4)]
                barrier.wait(5)
                check([f.result(timeout=15) for f in futures] == [True] * 4, "benchmark cold concurrent results literal True")
                elapsed = (time.perf_counter() - started) * 1000
                cold_kdf = counted.calls
            method_result[label] = {
                "cold_first_ms": round(cold_first, 4),
                "repeated": summary(samples), "repeated_KDF_calls": repeats_kdf,
                "cold_concurrent_batch_ms": round(elapsed, 4), "cold_concurrent_KDF_calls": cold_kdf,
            }
        result["methods"][method] = method_result
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--support-root", type=Path, default=ROOT)
    parser.add_argument("--cache-source", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--benchmark", action="store_true")
    parser.add_argument("--benchmark-output", type=Path)
    args = parser.parse_args()
    if args.benchmark and args.baseline is None:
        parser.error("--benchmark requires the captured pre-edit --baseline")
    if args.benchmark_output is not None:
        if not args.benchmark_output.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()):
            parser.error("--benchmark-output must be inside OS Temp")
    tempfile.gettempdir()
    support = args.support_root.resolve()
    sys.path.insert(0, str(support))
    source = args.source_root / "core/admin_basic_auth.py"
    cache_source = args.cache_source or args.source_root / "core/admin_auth_cache.py"
    for path in (source, cache_source):
        compile(path.read_text("utf-8"), str(path), "exec")
    Cache = load_module("core.admin_auth_cache", cache_source).SuccessfulAuthCache
    auth = load_module("core.admin_basic_auth", source)
    protected = verify_source_preservation(source, args.baseline)
    with mock.patch.object(os, "environ", {}):
        verify_semantics(auth, Cache)
        verify_configuration(auth, Cache)
        verify_unicode_configuration(auth, Cache)
        verify_ttl(auth, Cache)
        verify_concurrency(auth, Cache)
        verify_pending_beyond_success_ttl(Cache)
        verify_bounds_and_retention(Cache)
        verify_existing_boundaries(auth, support)
        results = benchmark(auth, Cache, args.baseline) if args.benchmark else None
    check("app" not in sys.modules and "core.paths" not in sys.modules, "standalone verifier imported no live app/runtime paths")
    if args.benchmark_output is not None and results is not None:
        args.benchmark_output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "passed": CHECKS, "source": str(source.resolve()),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "cache_sha256": hashlib.sha256(cache_source.read_bytes()).hexdigest(),
        "protected_functions": protected,
        "benchmark": results,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
