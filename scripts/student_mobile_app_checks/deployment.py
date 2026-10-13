"""Temp-only deployment runbook and PowerShell contract checks."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import tempfile
import uuid
import zipfile
from html import escape
from pathlib import Path
from typing import Final

from scripts import backup_runtime_data


ROOT: Final = Path(__file__).resolve().parents[2]
VERIFY = ROOT / "scripts" / "verify_student_app_deployment.ps1"
RUNNER = ROOT / "scripts" / "run_student_push_worker.ps1"
WAITRESS_RUNNER = ROOT / "scripts" / "run_waitress_server.ps1"
DOC = ROOT / "docs" / "student-mobile-app-deploy.md"
WORKFLOW = ROOT / ".github" / "workflows" / "refactor-safety.yml"
POWERSHELL = "powershell.exe"
RUNTIME_ISOLATION: Final = "temporary fixtures and dry-run subprocesses only"


def _check(state: list[int], condition: bool, message: str) -> None:
    state[0] += 1
    if not condition:
        raise AssertionError(message)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


def _parse_result(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise AssertionError(f"deployment verifier emitted no JSON (exit {result.returncode})")
    return json.loads(lines[-1])


def _codes(payload: dict[str, object]) -> set[str]:
    checks = payload.get("checks")
    if not isinstance(checks, list):
        return set()
    return {str(item.get("code")) for item in checks if isinstance(item, dict)}


def _fixture(root: Path) -> dict[str, Path]:
    fake_key = _write(root / "fake-private-key.pem", "NOT-A-PRIVATE-KEY\n")
    credential = _write(root / "tunnel-credential.json", "{}\n")
    env_file = _write(
        root / "environment.txt",
        "\n".join(
            (
                "STUDENT_APP_PUBLIC_ENABLED=0",
                "STUDENT_APP_PUBLIC_HOST=app.5a-math.com",
                "STUDENT_APP_LEGACY_HOST=5a-math.com",
                "STUDENT_APP_LEGACY_REDIRECT_ENABLED=0",
                "STUDENT_APP_TRUSTED_PROXIES=127.0.0.1/32,::1/128",
                "STUDENT_APP_CANARY_SIDS=test-sid",
                "STUDENT_APP_SESSION_COOKIE_SECURE=1",
                "STUDENT_APP_SESSION_SAMESITE=Lax",
                "STUDENT_APP_VAPID_SUBJECT=mailto:ops@example.test",
                f"STUDENT_APP_VAPID_PRIVATE_KEY_PATH={fake_key}",
                "ACADEMY_ADMIN_USERNAME=fixture-admin",
                "ACADEMY_ADMIN_PASSWORD_HASH=scrypt:32768:8:1$fixture$suffix",
                "TRUST_PROXY_HEADERS=1",
            )
        )
        + "\n",
    )
    runner = escape(str(RUNNER))
    working = escape(str(ROOT))
    task_xml = _write(
        root / "task.xml",
        f"""<?xml version="1.0"?><Task><Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy></Settings>
<Triggers><TimeTrigger><Repetition><Interval>PT1M</Interval></Repetition></TimeTrigger></Triggers>
<Actions><Exec><Command>powershell.exe</Command><Arguments>-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File &quot;{runner}&quot;</Arguments><WorkingDirectory>{working}</WorkingDirectory></Exec></Actions></Task>""",
    )
    tunnel = _write(
        root / "config.yml",
        f'tunnel: fixture\ncredentials-file: "{credential}"\ningress:\n  - hostname: app.5a-math.com\n    service: http://127.0.0.1:8003\n  - service: http_status:404\n',
    )
    return {
        "key": fake_key,
        "env": env_file,
        "task": task_xml,
        "tunnel": tunnel,
        "listener": _write(root / "listener.json", '{"port":8003,"processCount":1}\n'),
        "health": _write(root / "health.json", '{"host":"app.5a-math.com","scheme":"https","status":404,"cacheControl":""}\n'),
        "python": _write(root / "python.json", '{"exists":true,"version":"3.12","pywebpush":"2.3.0"}\n'),
        "key_policy": _write(root / "key-policy.json", '{"aclPrivate":true,"tracked":false,"ignored":true}\n'),
    }


def _verify_args(paths: dict[str, Path], phase: str = "Preflight") -> list[str]:
    return [
        "-File", str(VERIFY), "-DryRun", "-FixtureMode", "-Phase", phase,
        "-EnvironmentFile", str(paths["env"]), "-PythonSnapshotPath", str(paths["python"]),
        "-KeyPolicySnapshotPath", str(paths["key_policy"]), "-TaskXmlPath", str(paths["task"]),
        "-TunnelConfigPath", str(paths["tunnel"]), "-ListenerSnapshotPath", str(paths["listener"]),
        "-HealthSnapshotPath", str(paths["health"]),
    ]


def _backup_contract(state: list[int], temp_root: Path) -> None:
    runtime = temp_root / "runtime"
    _write(runtime / "auth_accounts.json", "{}")
    con = sqlite3.connect(runtime / "app.sqlite")
    con.execute("CREATE TABLE backup_fixture (id INTEGER)")
    con.commit()
    con.close()
    _write(runtime / "instance" / "student-app-vapid-private.pem", "secret")
    _write(runtime / "instance" / "student-app-vapid-private.pem.tmp", "secret-sidecar")
    _write(runtime / "instance" / "student-app-vapid-public.txt", "public")
    _write(runtime / "instance" / "student-test-push-approval.json", "approval")
    _write(runtime / "instance" / "student-test-push-approval.json.tmp", "approval-temp")
    _write(runtime / "instance" / "student-test-push-approval.json.consumed.opaque", "approval-consumed")
    _write(runtime / "instance" / "other-runtime.txt", "keep")
    selected = {path.relative_to(runtime).as_posix() for path in backup_runtime_data.iter_runtime_files(runtime)}
    _check(state, "instance/student-app-vapid-private.pem" not in selected, "private key entered backup selection")
    _check(state, "instance/student-app-vapid-private.pem.tmp" not in selected, "private key sidecar entered backup selection")
    _check(state, "instance/student-test-push-approval.json" not in selected, "test Push approval entered backup selection")
    _check(state, "instance/student-test-push-approval.json.tmp" not in selected, "test Push approval temp entered backup selection")
    _check(state, "instance/student-test-push-approval.json.consumed.opaque" not in selected, "consumed test Push approval entered backup selection")
    _check(state, "instance/student-app-vapid-public.txt" in selected, "public key output was incorrectly excluded")
    _check(state, "instance/other-runtime.txt" in selected, "unrelated instance data was excluded")
    original_root = backup_runtime_data.ROOT
    try:
        backup_runtime_data.ROOT = runtime
        archive = backup_runtime_data.make_backup(temp_root / "backups")
    finally:
        backup_runtime_data.ROOT = original_root
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        manifest = json.loads(bundle.read("MANIFEST.json"))
    manifest_names = {item["path"] for item in manifest["files"]}
    _check(state, "instance/student-app-vapid-private.pem" not in names | manifest_names, "archive contains private key")
    _check(state, "instance/student-app-vapid-private.pem.tmp" not in names | manifest_names, "archive contains private key sidecar")
    _check(state, "instance/student-test-push-approval.json" not in names | manifest_names, "archive contains test Push approval")
    _check(state, "instance/student-test-push-approval.json.tmp" not in names | manifest_names, "archive contains test Push approval temp")
    _check(state, "instance/student-test-push-approval.json.consumed.opaque" not in names | manifest_names, "archive contains consumed test Push approval")
    _check(state, {"auth_accounts.json", "app.sqlite", "instance/other-runtime.txt"} <= names, "archive lost runtime files")


def _static_contract(state: list[int]) -> None:
    verify_source = VERIFY.read_text(encoding="utf-8")
    runner_source = RUNNER.read_text(encoding="utf-8")
    waitress_source = WAITRESS_RUNNER.read_text(encoding="utf-8")
    doc = DOC.read_text(encoding="utf-8")
    workflow = WORKFLOW.read_text(encoding="utf-8")
    windows_ci_job = workflow.partition("verify-student-deployment-windows:")[2]
    for value in (
        "app.5a-math.com", "Academy Student Push Delivery",
        "STUDENT_APP_PUBLIC_ENABLED", "STUDENT_APP_LEGACY_HOST", "STUDENT_APP_LEGACY_REDIRECT_ENABLED", "STUDENT_APP_CANARY_SIDS", "STUDENT_APP_TRUSTED_PROXIES",
        "STUDENT_APP_VAPID_SUBJECT", "STUDENT_APP_VAPID_PRIVATE_KEY_PATH", "TRUST_PROXY_HEADERS",
        "ACADEMY_ADMIN_USERNAME", "ACADEMY_ADMIN_PASSWORD_HASH",
        "instance\\student-app-vapid-private.pem", "BLOCKED_NO_CLOUDFLARE_AUTH", "IgnoreNew", "PT1M",
    ):
        _check(state, value in verify_source, f"deployment verifier omitted {value}")
        _check(state, value in doc, f"deployment runbook omitted {value}")
    _check(state, "http://127.0.0.1:8003" in doc, "deployment runbook omitted production origin")
    _check(state, "venv\\Scripts\\python.exe" in runner_source, "worker runner does not use exact venv Python")
    for worker in (
        "deliver_student_push_outbox.py", "enqueue_student_reminders.py",
        "deliver_student_notification_outbox.py",
    ):
        _check(state, worker in runner_source and "--once" in runner_source,
               f"worker runner omitted {worker}")
    _check(state, "WaitOne(0)" in runner_source and "worker_overlap" in runner_source, "worker overlap guard missing")
    _check(state, "ContractFixtureId requires DryRun" in runner_source, "worker contract fixture is not fail-closed")
    _check(state, "Local\\AcademyStudentPushDelivery-ContractFixture-" in runner_source, "worker fixture still shares the production mutex")
    _check(state, "Global\\AcademyStudentPushDelivery-v1" in runner_source, "production worker mutex contract changed")
    _check(
        state,
        "runs-on: windows-latest" in windows_ci_job
        and "python-version: \"3.12\"" in windows_ci_job
        and "python -m venv venv" in windows_ci_job
        and "--only-student-mobile-deployment" in windows_ci_job,
        "Windows CI does not execute the full deployment contract",
    )
    for override in (
        "PublicHostOverride", "PublicEnabledOverride", "RemindersEnabledOverride",
        "CanarySidsOverride", "VapidSubjectOverride", "VapidPrivateKeyPathOverride",
        "RuntimeRootOverride", "DevelopmentIsolation",
    ):
        _check(state, override in runner_source, f"worker runner omitted process override {override}")
    _check(state, "Development worker isolation requires" in runner_source, "development worker lacks fail-closed isolation validation")
    _check(state, "ls-files --error-unmatch" not in verify_source and "$tracked.Count -gt 0" in verify_source, "live untracked-key check can terminate under Windows PowerShell ErrorActionPreference")
    _check(state, "FixtureMode requires DryRun and every snapshot path" in verify_source, "fixture verifier can fall back to live state")
    _check(state, "Add-Type -AssemblyName System.Net.Http" in verify_source, "Windows PowerShell live health check does not load System.Net.Http")
    _check(state, 'TryAddWithoutValidation("CF-Connecting-IP"' in verify_source, "live health check omits the trusted tunnel client header")
    _check(state, 'ValidateSet("app.5a-math.com", "dev-app.5a-math.com")' in verify_source, "deployment verifier omits exact dev/prod hosts")
    _check(state, '$originPort = if ($PublicHost -eq "dev-app.5a-math.com") { 8004 } else { 8003 }' in verify_source, "deployment verifier omits dev/prod port split")
    _check(state, "GetEnvironmentVariable($name, \"Machine\")" in waitress_source, "Waitress runner does not refresh machine environment")
    _check(state, 'Remove-Item -LiteralPath "Env:$name"' in waitress_source, "Waitress runner leaves deleted machine variables inherited")
    _check(state, "STUDENT_APP_LEGACY_HOST" in waitress_source and "STUDENT_APP_LEGACY_REDIRECT_ENABLED" in waitress_source, "Waitress runner omitted legacy rollout gates")
    for flag in (
        "STUDENT_APP_DASHBOARD_ENABLED", "STUDENT_APP_HOMEWORK_ENABLED",
        "STUDENT_APP_REMINDERS_ENABLED", "STUDENT_APP_FOCUS_ENABLED",
    ):
        _check(state, flag in waitress_source, f"Waitress runner omitted feature flag {flag}")
    for override in (
        "PublicHostOverride", "PublicEnabledOverride", "CanarySidsOverride",
        "VapidSubjectOverride", "VapidPrivateKeyPathOverride",
    ):
        _check(state, override in waitress_source, f"Waitress runner omitted process override {override}")
    _check(state, "exact DNS hostname" in waitress_source, "Waitress runner does not reject malformed host overrides")
    _check(state, "VAPID overrides must be provided together" in waitress_source, "Waitress runner permits partial VAPID overrides")
    _check(state, "repository instance directory" in waitress_source, "development VAPID key is not isolated to the instance directory")
    for option in ("--trusted-proxy=127.0.0.1", "--trusted-proxy-count=1", "--trusted-proxy-headers=x-forwarded-proto", "--clear-untrusted-proxy-headers"):
        _check(state, option in waitress_source, f"Waitress runner omitted {option}")
    _check(state, "--trusted-proxy-headers=x-forwarded-for" not in waitress_source, "Waitress bypasses CF client identity validation")
    _check(state, all(len(source.splitlines()) <= 250 for source in (verify_source, runner_source, waitress_source)), "new PowerShell module exceeds 250 lines")
    rollback = doc.split("## 8. rollback", 1)[1]
    _check(state, rollback.index("STUDENT_APP_PUBLIC_ENABLED=0") < rollback.index("Cloudflare") < rollback.index("Disable-ScheduledTask"), "rollback order is not flag, Tunnel, task")


def run_portable_checks() -> dict[str, object]:
    """Validate source and backup contracts without invoking Windows PowerShell."""
    state = [0]
    _static_contract(state)
    with tempfile.TemporaryDirectory(prefix="student-app-deploy-portable-") as directory:
        _backup_contract(state, Path(directory))
    return {
        "name": "deployment-portable",
        "assertions": state[0],
        "passed": True,
        "runtimeIsolation": RUNTIME_ISOLATION,
    }


def run_checks() -> dict[str, object]:
    state = [0]
    _static_contract(state)
    fixture_id = f"phase14-{os.getpid()}-{uuid.uuid4().hex[:12]}"
    syntax = _run("-Command", f"$t=$null;$e=$null;[Management.Automation.Language.Parser]::ParseFile('{VERIFY}',[ref]$t,[ref]$e)|Out-Null;if($e.Count){{exit 1}}")
    _check(state, syntax.returncode == 0, "deployment verifier has PowerShell syntax errors")
    syntax = _run("-Command", f"$t=$null;$e=$null;[Management.Automation.Language.Parser]::ParseFile('{RUNNER}',[ref]$t,[ref]$e)|Out-Null;if($e.Count){{exit 1}}")
    _check(state, syntax.returncode == 0, "Push runner has PowerShell syntax errors")
    syntax = _run("-Command", f"$t=$null;$e=$null;[Management.Automation.Language.Parser]::ParseFile('{WAITRESS_RUNNER}',[ref]$t,[ref]$e)|Out-Null;if($e.Count){{exit 1}}")
    _check(state, syntax.returncode == 0, "Waitress runner has PowerShell syntax errors")
    incomplete_fixture = _run("-File", str(VERIFY), "-DryRun", "-FixtureMode")
    _check(state, incomplete_fixture.returncode != 0
           and "requires DryRun and every snapshot path" in incomplete_fixture.stderr,
           "incomplete FixtureMode invocation did not fail before live-state fallback")
    runner = _run("-File", str(RUNNER), "-DryRun", "-ContractFixtureId", fixture_id)
    runner_payload = _parse_result(runner)
    _check(state, runner.returncode == 0
           and runner_payload.get("contractFixture") is True
           and runner_payload.get("publicEnabled") == "0"
           and runner_payload.get("remindersEnabled") == "0"
           and all(worker in runner.stdout for worker in (
               "deliver_student_push_outbox.py --once", "enqueue_student_reminders.py --once",
               "deliver_student_notification_outbox.py --once",
           )), "isolated worker dry-run contract failed")
    unsafe_fixture = _run("-File", str(RUNNER), "-ContractFixtureId", fixture_id)
    _check(state, unsafe_fixture.returncode != 0 and "requires DryRun" in unsafe_fixture.stderr,
           "worker contract fixture allowed a non-dry-run invocation")
    runner_literal = str(RUNNER).replace("'", "''")
    fixture_id_literal = fixture_id.replace("'", "''")
    fixture_mutex = f"Local\\AcademyStudentPushDelivery-ContractFixture-{fixture_id}".replace("'", "''")
    overlap = _run(
        "-Command",
        f"$m=[Threading.Mutex]::new($true,'{fixture_mutex}');$code=1;try{{"
        f"$runner='{runner_literal}';& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $runner -DryRun -ContractFixtureId '{fixture_id_literal}';$code=$LASTEXITCODE"
        "}finally{$m.ReleaseMutex();$m.Dispose()};exit $code",
    )
    _check(state, overlap.returncode == 3 and "worker_overlap" in overlap.stdout, "worker overlap was not rejected")
    with tempfile.TemporaryDirectory(prefix="student-app-deploy-") as directory:
        root = Path(directory)
        _backup_contract(state, root)
        paths = _fixture(root)
        happy = _run(*_verify_args(paths))
        payload = _parse_result(happy)
        _check(state, happy.returncode == 0 and payload.get("status") == "PASS", "fixture preflight did not pass")
        originals = {key: paths[key].read_text(encoding="utf-8") for key in ("env", "tunnel", "listener", "health")}
        _write(paths["env"], originals["env"].replace("app.5a-math.com", "dev-app.5a-math.com"))
        _write(paths["tunnel"], originals["tunnel"].replace("app.5a-math.com", "dev-app.5a-math.com").replace("127.0.0.1:8003", "127.0.0.1:8004"))
        _write(paths["listener"], '{"port":8004,"processCount":1}\n')
        _write(paths["health"], '{"host":"dev-app.5a-math.com","scheme":"https","status":404,"cacheControl":""}\n')
        dev = _run(*_verify_args(paths), "-PublicHost", "dev-app.5a-math.com")
        _check(state, dev.returncode == 0 and _parse_result(dev).get("status") == "PASS", "dev fixture preflight did not pass")
        for key, content in originals.items():
            _write(paths[key], content)
        _check(state, "NOT-A-PRIVATE-KEY" not in happy.stdout + happy.stderr, "verifier leaked fake key material")
        public_output = _write(root / "existing-public.txt", "existing-public\n")
        before_key = paths["key"].read_bytes()
        second_key = subprocess.run(
            [str(ROOT / "venv" / "Scripts" / "python.exe"), str(ROOT / "scripts" / "generate_student_vapid_key.py"),
             "--private-path", str(paths["key"]), "--public-output", str(public_output)],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        )
        _check(state, second_key.returncode == 2 and paths["key"].read_bytes() == before_key, "second key generation was not refused")

        cases = (
            ("python", '{"exists":true,"version":"3.12","pywebpush":""}', 3, "BLOCKED_NO_PYWEBPUSH"),
            ("python", '{"exists":true,"version":"3.11","pywebpush":"2.3.0"}', 2, "FAIL_PYTHON_OR_PYWEBPUSH_VERSION"),
            ("key_policy", '{"aclPrivate":false,"tracked":false,"ignored":true}', 2, "FAIL_VAPID_KEY_ACL"),
            ("key_policy", '{"aclPrivate":true,"tracked":true,"ignored":false}', 2, "FAIL_VAPID_KEY_TRACKED"),
            ("listener", '{"port":8003,"processCount":0}', 3, "BLOCKED_PORT_8003_DOWN"),
        )
        for key, content, expected_exit, expected_code in cases:
            original = paths[key].read_text(encoding="utf-8")
            _write(paths[key], content)
            result = _run(*_verify_args(paths)); result_payload = _parse_result(result)
            _check(state, result.returncode == expected_exit and expected_code in _codes(result_payload), f"failure injection missed {expected_code}")
            _write(paths[key], original)

        wrong_task = paths["task"].read_text(encoding="utf-8").replace("run_student_push_worker.ps1", "wrong.ps1")
        _write(paths["task"], wrong_task)
        result = _run(*_verify_args(paths)); _check(state, result.returncode == 2 and "FAIL_PUSH_TASK_CONTRACT" in _codes(_parse_result(result)), "wrong task command passed")
        _write(paths["task"], wrong_task.replace("wrong.ps1", "run_student_push_worker.ps1"))
        tunnel = paths["tunnel"].read_text(encoding="utf-8"); paths["tunnel"].unlink()
        result = _run(*_verify_args(paths)); _check(state, result.returncode == 3 and "BLOCKED_NO_CLOUDFLARE_AUTH" in _codes(_parse_result(result)), "missing Cloudflare auth passed")
        _write(paths["tunnel"], tunnel)
        env_text = paths["env"].read_text(encoding="utf-8").replace("127.0.0.1/32,::1/128", "0.0.0.0/0")
        _write(paths["env"], env_text)
        result = _run(*_verify_args(paths)); _check(state, result.returncode == 2 and "FAIL_ENV_OR_ROLLOUT_GATE" in _codes(_parse_result(result)), "untrusted proxy passed")
        _write(paths["env"], env_text.replace("0.0.0.0/0", "127.0.0.1/32,::1/128"))
        original_env = paths["env"].read_text(encoding="utf-8")
        _write(paths["env"], original_env.replace("STUDENT_APP_VAPID_SUBJECT=mailto:ops@example.test\n", ""))
        result = _run(*_verify_args(paths)); _check(state, result.returncode == 3 and "BLOCKED_MISSING_ENV_NAMES" in _codes(_parse_result(result)), "missing VAPID subject passed")
        missing_key_env = original_env.replace(str(paths["key"]), str(root / "missing-private-key.pem"))
        _write(paths["env"], missing_key_env)
        result = _run(*_verify_args(paths)); _check(state, result.returncode == 3 and "BLOCKED_NO_VAPID_KEY" in _codes(_parse_result(result)), "missing VAPID key passed")
        _write(paths["env"], original_env)
        original_tunnel = paths["tunnel"].read_text(encoding="utf-8")
        _write(paths["tunnel"], original_tunnel.replace("127.0.0.1:8003", "127.0.0.1:9000"))
        result = _run(*_verify_args(paths)); _check(state, result.returncode == 2 and "FAIL_TUNNEL_MAPPING" in _codes(_parse_result(result)), "wrong Tunnel origin passed")
        _write(paths["tunnel"], original_tunnel)
        _write(paths["env"], original_env.replace("STUDENT_APP_PUBLIC_ENABLED=0", "STUDENT_APP_PUBLIC_ENABLED=1"))
        _write(paths["health"], '{"host":"app.5a-math.com","scheme":"https","status":200,"cacheControl":"no-store","externalStatus":200,"externalScheme":"https","externalHost":"app.5a-math.com"}')
        result = _run(*_verify_args(paths, "Canary")); _check(state, result.returncode == 0 and _parse_result(result).get("status") == "PASS", "canary fixture did not pass")
        expanded_env = paths["env"].read_text(encoding="utf-8").replace("STUDENT_APP_CANARY_SIDS=test-sid", "STUDENT_APP_CANARY_SIDS=").replace("STUDENT_APP_LEGACY_REDIRECT_ENABLED=0", "STUDENT_APP_LEGACY_REDIRECT_ENABLED=1")
        _write(paths["env"], expanded_env)
        result = _run(*_verify_args(paths, "Expanded")); expanded_payload = _parse_result(result); _check(state, result.returncode == 2 and "FAIL_ENV_OR_ROLLOUT_GATE" in _codes(expanded_payload), f"expanded rollout passed without approval: exit={result.returncode} codes={sorted(_codes(expanded_payload))}")
        result = _run(*_verify_args(paths, "Expanded"), "-RolloutApproved"); _check(state, result.returncode == 0, "approved expanded fixture did not pass")
        _write(paths["env"], original_env)
        _write(paths["health"], '{"host":"app.5a-math.com","scheme":"https","status":404,"cacheControl":""}')
        result = _run(*_verify_args(paths)); _check(state, result.returncode == 0, "flag-off rollback preflight did not return to 404")
    return {
        "name": "deployment",
        "assertions": state[0],
        "passed": True,
        "runtimeIsolation": RUNTIME_ISOLATION,
    }


if __name__ == "__main__":
    outcome = run_checks()
    print(f"deployment checks passed: {outcome['assertions']} assertions")
