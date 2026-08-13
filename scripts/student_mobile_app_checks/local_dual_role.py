"""Temp-only checks for development admin/student dual-role provisioning."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

from werkzeug.security import check_password_hash

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import provision_local_dual_role_account as provisioner


def _check(state: list[int], condition: bool, message: str) -> None:
    state[0] += 1
    if not condition:
        raise AssertionError(message)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _expect_blocked(state: list[int], callback, message: str) -> None:
    try:
        callback()
    except (provisioner.ProvisioningError, ValueError):
        _check(state, True, message)
    else:
        raise AssertionError(message)


def run_checks() -> dict[str, object]:
    state = [0]
    password = "safe-dev-pass!"
    with tempfile.TemporaryDirectory(prefix="local-dual-role-") as raw:
        base = Path(raw)
        runtime = base / "runtime"
        backup_parent = base / "backups"
        sid = "dev-student-001"
        account_id = "dual-role-admin"
        _write(runtime / "students.json", [{"id": sid, "name": "개발용 학생", "synthetic": True}])
        _write(
            runtime / "auth_accounts.json",
            {
                "_meta": {"version": 9, "keep": True},
                "other": {"sids": ["other-sid"], "unknown": {"keep": True}},
            },
        )
        sessions = provisioner.StudentSessionRepository(runtime / "app.sqlite", clock=lambda: 1000.0)
        stale_session = sessions.create(account_id, sid, [sid], now=1000.0)
        paths = provisioner.resolve_paths(runtime)
        receipt = provisioner.provision(paths, account_id, password, sid, backup_parent)
        _check(state, receipt.get("ok") is True, "provisioning did not return a success receipt")
        _check(state, receipt.get("accountId") == account_id and receipt.get("studentSid") == sid, "receipt lost the requested synthetic binding")
        _check(state, receipt.get("revokedSessions") == 1 and sessions.resolve(stale_session["token"], now=1001.0) is None, "provisioning did not revoke an existing student session")
        _check(state, Path(str(receipt.get("backupDirectory"))).is_dir(), "provisioning did not create an external backup")
        _check(state, paths.admin_credentials.is_file(), "development admin credential file was not written")

        accounts = json.loads(paths.accounts.read_text(encoding="utf-8"))
        admin = json.loads(paths.admin_credentials.read_text(encoding="utf-8"))
        record = accounts[account_id]
        _check(state, accounts["_meta"] == {"version": 9, "keep": True}, "account metadata was not preserved")
        _check(state, accounts["other"] == {"sids": ["other-sid"], "unknown": {"keep": True}}, "unrelated account fields were not preserved")
        _check(state, record["sids"] == [sid], "provisioned account escaped the synthetic SID")
        _check(state, record["synthetic"] is True and record["disabled"] is False and record["must_change_credentials"] is False, "provisioned student account state is not ready")
        _check(state, check_password_hash(record["pw_hash"], password), "student password hash does not verify")
        _check(state, admin["schemaVersion"] == 1 and admin["scope"] == "development-local-admin", "admin credential scope is not development-only")
        _check(state, admin["username"] == account_id and check_password_hash(admin["passwordHash"], password), "admin password hash does not verify")
        _check(state, record["pw_hash"] != admin["passwordHash"], "student and admin surfaces reused one stored hash")
        _check(state, password not in paths.accounts.read_text(encoding="utf-8") and password not in paths.admin_credentials.read_text(encoding="utf-8"), "plaintext password entered runtime files")
        _check(state, provisioner.verify_provisioned(paths, account_id, password, sid), "verification did not accept both provisioned roles")
        _check(state, not provisioner.verify_provisioned(paths, account_id, "wrong-dev-pass!", sid), "verification accepted a wrong password")

        backup = Path(str(receipt["backupDirectory"]))
        manifest = json.loads((backup / "MANIFEST.json").read_text(encoding="utf-8"))
        _check(state, (backup / "auth_accounts.before.json").is_file(), "original account store was not backed up")
        backup_names = {item["name"] for item in manifest["files"]}
        _check(state, backup_names == {"auth_accounts.before.json", "app.before.sqlite"}, "initial private backup has the wrong file set")
        _check(state, (backup / "app.before.sqlite").is_file(), "SQLite session backup was not created")

        accounts[account_id]["unknown"] = {"preserve": True}
        _write(paths.accounts, accounts)
        rotated_session = sessions.create(account_id, sid, [sid], now=1002.0)
        second = provisioner.provision(paths, account_id, "second-dev-pass!", sid, backup_parent)
        refreshed = json.loads(paths.accounts.read_text(encoding="utf-8"))[account_id]
        _check(state, refreshed["unknown"] == {"preserve": True}, "re-provisioning erased unknown account fields")
        _check(state, check_password_hash(refreshed["pw_hash"], "second-dev-pass!"), "re-provisioning did not rotate the student hash")
        _check(state, second.get("revokedSessions") == 1 and sessions.resolve(rotated_session["token"], now=1003.0) is None, "password rotation left an old session active")
        second_backup = Path(str(second["backupDirectory"]))
        _check(state, (second_backup / f"{provisioner.ADMIN_CREDENTIAL_NAME}.before").is_file(), "existing admin credential was not backed up before rotation")

        before_accounts = paths.accounts.read_bytes()
        before_admin = paths.admin_credentials.read_bytes()
        original_private_write = provisioner._write_private_atomic
        injected = [False]

        def fail_once(path: Path, payload: object) -> None:
            if path == paths.admin_credentials and not injected[0]:
                injected[0] = True
                raise OSError("injected credential write failure")
            original_private_write(path, payload)  # type: ignore[arg-type]

        provisioner._write_private_atomic = fail_once
        try:
            _expect_blocked(
                state,
                lambda: provisioner.provision(paths, account_id, "third-dev-pass!", sid, backup_parent),
                "credential write failure was not rejected",
            )
        finally:
            provisioner._write_private_atomic = original_private_write
        _check(state, paths.accounts.read_bytes() == before_accounts and paths.admin_credentials.read_bytes() == before_admin, "partial provisioning was not rolled back")

        original_save = provisioner.save_atomic
        save_injected = [False]

        def fail_account_save(path: Path, payload: object, **kwargs: object) -> None:
            if path == paths.accounts and not save_injected[0]:
                save_injected[0] = True
                raise OSError("injected account save failure")
            original_save(path, payload, **kwargs)

        provisioner.save_atomic = fail_account_save
        try:
            _expect_blocked(
                state,
                lambda: provisioner.provision(paths, account_id, "third-dev-pass!", sid, backup_parent),
                "account save failure was not rejected",
            )
        finally:
            provisioner.save_atomic = original_save
        _check(state, paths.accounts.read_bytes() == before_accounts and paths.admin_credentials.read_bytes() == before_admin, "account save failure left the admin credential rotated")

        original_load = provisioner._load_json
        roster_reads = [0]

        def change_roster_during_provision(path: Path, expected: type) -> object:
            value = original_load(path, expected)
            if path == paths.students:
                roster_reads[0] += 1
                if roster_reads[0] > 1:
                    return [{"id": sid, "synthetic": False}]
            return value

        provisioner._load_json = change_roster_during_provision
        try:
            _expect_blocked(
                state,
                lambda: provisioner.provision(paths, account_id, "third-dev-pass!", sid, backup_parent),
                "roster change before commit was not rejected",
            )
        finally:
            provisioner._load_json = original_load
        _check(state, paths.accounts.read_bytes() == before_accounts and paths.admin_credentials.read_bytes() == before_admin, "roster race left a partial credential change")

        _expect_blocked(
            state,
            lambda: provisioner.provision(paths, account_id, "third-dev-pass!", "other-sid", backup_parent),
            "missing synthetic SID was accepted",
        )
        _check(state, paths.accounts.read_bytes() == before_accounts and paths.admin_credentials.read_bytes() == before_admin, "failed provisioning changed runtime credentials")

        accounts = json.loads(paths.accounts.read_text(encoding="utf-8"))
        accounts[account_id]["sids"] = [sid, "real-student"]
        _write(paths.accounts, accounts)
        _expect_blocked(
            state,
            lambda: provisioner.provision(paths, account_id, "third-dev-pass!", sid, backup_parent),
            "existing cross-SID account was repointed",
        )

        _expect_blocked(
            state,
            lambda: provisioner.resolve_paths(runtime, base / provisioner.ADMIN_CREDENTIAL_NAME),
            "credential file outside instance was accepted",
        )
        _expect_blocked(
            state,
            lambda: provisioner.resolve_paths(runtime, runtime / "instance" / "nested" / provisioner.ADMIN_CREDENTIAL_NAME),
            "nested credential file escaped the backup exclusion contract",
        )
        students = json.loads(paths.students.read_text(encoding="utf-8"))
        students.append({"id": "other-synthetic", "synthetic": True})
        _write(paths.students, students)
        _expect_blocked(
            state,
            lambda: provisioner.provision(paths, "new-safe-id", "third-dev-pass!", "other-synthetic", backup_parent),
            "a non-canonical synthetic SID was accepted",
        )
        _expect_blocked(
            state,
            lambda: provisioner.provision(paths, "new-safe-id", "third-dev-pass!", sid, runtime / "backups"),
            "backup inside runtime root was accepted",
        )

    source = (provisioner.ROOT / "scripts" / "provision_local_dual_role_account.py").read_text(encoding="utf-8")
    _check(state, "getpass.getpass" in source and '"--password"' not in source, "CLI does not keep the password off argv")
    _check(state, "generate_password_hash" in source and "passwordHash" in source, "CLI omitted hashed dual-role credentials")
    _check(state, "development-local-admin" in source and "synthetic" in source, "CLI omitted development/synthetic gates")
    return {"name": "local-dual-role", "assertions": state[0], "passed": True}


if __name__ == "__main__":
    result = run_checks()
    print(f"local dual-role checks passed: {result['assertions']} assertions")
