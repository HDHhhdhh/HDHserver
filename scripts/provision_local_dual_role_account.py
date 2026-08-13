"""Provision one development-only admin/student test credential without logging it."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import locale
import os
import sqlite3
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
import sys
import subprocess
import uuid

from werkzeug.security import check_password_hash, generate_password_hash


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.storage import file_lock, save_atomic  # noqa: E402
from core.student_account_rules import account_id_key, normalize_account_id, validate_password  # noqa: E402
from core.student_sessions import StudentSessionRepository  # noqa: E402


ADMIN_CREDENTIAL_NAME = "student-app-dev-admin-auth.json"
DEV_STUDENT_SID = "dev-student-001"


class ProvisioningError(RuntimeError):
    """Fail closed without including account or credential material in errors."""


@dataclass(frozen=True, slots=True)
class ProvisioningPaths:
    runtime_root: Path
    students: Path
    accounts: Path
    database: Path
    admin_credentials: Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def resolve_paths(runtime_root: Path, admin_credential_file: Path | None = None) -> ProvisioningPaths:
    root = Path(runtime_root).resolve(strict=True)
    instance = (root / "instance").resolve()
    expected_credential = (instance / ADMIN_CREDENTIAL_NAME).resolve()
    credential = Path(admin_credential_file or expected_credential).resolve()
    if credential != expected_credential:
        raise ProvisioningError("admin credential file must be the exact ignored development file inside instance")
    students = root / "students.json"
    accounts = root / "auth_accounts.json"
    database = root / "app.sqlite"
    if not students.is_file() or not accounts.is_file() or not database.is_file():
        raise ProvisioningError("runtime roster, account store, or session database is missing")
    return ProvisioningPaths(root, students, accounts, database, credential)


def _load_json(path: Path, expected: type) -> object:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProvisioningError("runtime JSON is unavailable or malformed") from exc
    if not isinstance(value, expected):
        raise ProvisioningError("runtime JSON has an unexpected shape")
    return value


def _find_account_key(accounts: dict[str, object], account_id: str) -> str | None:
    wanted = account_id_key(account_id)
    for candidate in accounts:
        try:
            if account_id_key(candidate) == wanted:
                return candidate
        except ValueError:
            continue
    return None


def _require_synthetic_student(students: list[object], sid: str) -> None:
    matches = [row for row in students if isinstance(row, dict) and row.get("id") == sid]
    if len(matches) != 1 or matches[0].get("synthetic") is not True:
        raise ProvisioningError("exactly one synthetic development student is required")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_private_atomic(path: Path, payload: dict[str, object] | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        _harden_private_file(temporary)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


@lru_cache(maxsize=1)
def _windows_user_sid() -> str:
    encoding = locale.getpreferredencoding(False) or "utf-8"
    identity = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", "[Security.Principal.WindowsIdentity]::GetCurrent().User.Value"],
        check=False,
        capture_output=True,
        text=True,
        encoding=encoding,
        errors="replace",
    )
    user_sid = identity.stdout.strip()
    if identity.returncode != 0 or not user_sid.startswith("S-1-"):
        raise ProvisioningError("could not resolve the current Windows security identity")
    return user_sid


def _harden_private_path(path: Path, *, directory: bool) -> None:
    """Restrict private artifacts; chmod alone is not a Windows ACL."""

    if os.name != "nt":
        os.chmod(path, 0o700 if directory else 0o600)
        return
    encoding = locale.getpreferredencoding(False) or "utf-8"
    user_sid = _windows_user_sid()
    rights = "(OI)(CI)(F)" if directory else "(F)"
    hardened = subprocess.run(
        [
            "icacls.exe",
            str(path),
            "/inheritance:r",
            "/grant:r",
            f"*{user_sid}:{rights}",
            f"*S-1-5-18:{rights}",
            f"*S-1-5-32-544:{rights}",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding=encoding,
        errors="replace",
    )
    if hardened.returncode != 0:
        raise ProvisioningError("could not restrict the private path ACL")


def _harden_private_file(path: Path) -> None:
    _harden_private_path(path, directory=False)


def _create_backup(paths: ProvisioningPaths, backup_parent: Path, originals: dict[Path, bytes | None]) -> Path:
    parent = Path(backup_parent).resolve()
    if _is_within(parent, paths.runtime_root):
        raise ProvisioningError("backup directory must be outside the runtime root")
    backup = parent / f"dual-role-{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}-{uuid.uuid4().hex[:8]}"
    backup.mkdir(parents=True, exist_ok=False)
    _harden_private_path(backup, directory=True)
    manifest: dict[str, object] = {"createdAt": _utc_now(), "files": []}
    files = manifest["files"]
    assert isinstance(files, list)
    for source, data in originals.items():
        if data is None:
            continue
        name = "auth_accounts.before.json" if source == paths.accounts else f"{ADMIN_CREDENTIAL_NAME}.before"
        target = backup / name
        _write_private_atomic(target, data)
        files.append({"name": name, "size": len(data), "sha256": _sha256(data)})
    sqlite_target = backup / "app.before.sqlite"
    source_uri = f"file:{paths.database.resolve().as_posix()}?mode=ro"
    source_db = sqlite3.connect(source_uri, uri=True, timeout=5.0)
    target_db = sqlite3.connect(sqlite_target, timeout=5.0)
    try:
        source_db.backup(target_db)
    finally:
        target_db.close()
        source_db.close()
    _harden_private_file(sqlite_target)
    sqlite_data = sqlite_target.read_bytes()
    files.append({"name": sqlite_target.name, "size": len(sqlite_data), "sha256": _sha256(sqlite_data)})
    _write_private_atomic(backup / "MANIFEST.json", manifest)
    return backup


def provision(
    paths: ProvisioningPaths,
    account_id: str,
    password: str,
    student_sid: str,
    backup_parent: Path,
) -> dict[str, str | int | bool]:
    normalized_id = normalize_account_id(account_id)
    valid_password = validate_password(password, normalized_id)
    sid = student_sid.strip()
    if sid != DEV_STUDENT_SID or sid != student_sid:
        raise ProvisioningError("student SID must be the exact development synthetic SID")

    paths.admin_credentials.parent.mkdir(parents=True, exist_ok=True)
    lock_paths = sorted((paths.students, paths.accounts, paths.admin_credentials), key=lambda value: str(value).casefold())
    with ExitStack() as stack:
        for lock_path in lock_paths:
            stack.enter_context(file_lock(lock_path))
        students = _load_json(paths.students, list)
        accounts = _load_json(paths.accounts, dict)
        assert isinstance(students, list) and isinstance(accounts, dict)
        _require_synthetic_student(students, sid)

        stored_key = _find_account_key(accounts, normalized_id)
        if stored_key is not None:
            stored = accounts.get(stored_key)
            if not isinstance(stored, dict) or stored.get("sids") != [sid]:
                raise ProvisioningError("existing account is not exclusively linked to the synthetic student")
            record = dict(stored)
        else:
            stored_key = normalized_id
            record = {"created_at": _utc_now()}

        original_accounts = paths.accounts.read_bytes()
        original_admin = paths.admin_credentials.read_bytes() if paths.admin_credentials.is_file() else None
        backup = _create_backup(
            paths,
            backup_parent,
            {paths.accounts: original_accounts, paths.admin_credentials: original_admin},
        )
        sessions = StudentSessionRepository(paths.database)
        revoked_sessions = 0
        for session_aid in dict.fromkeys((normalized_id, stored_key)):
            revoked_sessions += sessions.revoke_account(session_aid)
        now = _utc_now()
        record.update(
            {
                "sids": [sid],
                "pw_hash": generate_password_hash(valid_password),
                "must_change_credentials": False,
                "disabled": False,
                "synthetic": True,
                "updated_at": now,
                "credentials_updated_at": now,
            }
        )
        accounts[stored_key] = record
        admin_payload: dict[str, object] = {
            "schemaVersion": 1,
            "scope": "development-local-admin",
            "username": normalized_id,
            "passwordHash": generate_password_hash(valid_password),
            "updatedAt": now,
        }
        try:
            # Publish the private admin file first. The running process never
            # rereads it, so a later account-save failure can restore it while
            # leaving the account primary and mirror completely unchanged.
            _write_private_atomic(paths.admin_credentials, admin_payload)
            current_students = _load_json(paths.students, list)
            assert isinstance(current_students, list)
            _require_synthetic_student(current_students, sid)
            save_atomic(paths.accounts, accounts)
            stored_accounts = _load_json(paths.accounts, dict)
            stored_admin = _load_json(paths.admin_credentials, dict)
            assert isinstance(stored_accounts, dict) and isinstance(stored_admin, dict)
            stored_record = stored_accounts.get(stored_key)
            if (
                not isinstance(stored_record, dict)
                or stored_record.get("sids") != [sid]
                or not isinstance(stored_record.get("pw_hash"), str)
                or not check_password_hash(stored_record["pw_hash"], valid_password)
                or stored_admin.get("username") != normalized_id
                or not isinstance(stored_admin.get("passwordHash"), str)
                or not check_password_hash(stored_admin["passwordHash"], valid_password)
            ):
                raise ProvisioningError("written credentials did not verify")
        except Exception as exc:
            rollback_errors: list[Exception] = []
            try:
                save_atomic(paths.accounts, json.loads(original_accounts.decode("utf-8-sig")))
            except Exception as rollback_exc:  # noqa: BROAD_EXCEPT_OK
                rollback_errors.append(rollback_exc)
            try:
                if original_admin is None:
                    paths.admin_credentials.unlink(missing_ok=True)
                else:
                    _write_private_atomic(paths.admin_credentials, original_admin)
            except Exception as rollback_exc:  # noqa: BROAD_EXCEPT_OK
                rollback_errors.append(rollback_exc)
            if rollback_errors:
                raise ProvisioningError("provisioning failed and rollback was incomplete; restore the private backup") from None
            raise ProvisioningError("provisioning failed; original credentials were restored") from exc

    return {
        "ok": True,
        "accountId": normalized_id,
        "studentSid": sid,
        "revokedSessions": revoked_sessions,
        "backupDirectory": str(backup),
        "adminCredentialFile": str(paths.admin_credentials),
    }


def verify_provisioned(paths: ProvisioningPaths, account_id: str, password: str, student_sid: str) -> bool:
    normalized_id = normalize_account_id(account_id)
    validate_password(password, normalized_id)
    if student_sid != DEV_STUDENT_SID:
        return False
    with ExitStack() as stack:
        for lock_path in sorted((paths.students, paths.accounts, paths.admin_credentials), key=lambda value: str(value).casefold()):
            stack.enter_context(file_lock(lock_path))
        students = _load_json(paths.students, list)
        accounts = _load_json(paths.accounts, dict)
        admin = _load_json(paths.admin_credentials, dict)
    assert isinstance(students, list) and isinstance(accounts, dict) and isinstance(admin, dict)
    try:
        _require_synthetic_student(students, student_sid)
    except ProvisioningError:
        return False
    stored_key = _find_account_key(accounts, normalized_id)
    record = accounts.get(stored_key) if stored_key is not None else None
    student_hash = record.get("pw_hash") if isinstance(record, dict) else None
    admin_hash = admin.get("passwordHash")
    return (
        isinstance(record, dict)
        and record.get("sids") == [student_sid]
        and record.get("synthetic") is True
        and record.get("disabled") is False
        and record.get("must_change_credentials") is False
        and isinstance(student_hash, str)
        and check_password_hash(student_hash, password)
        and admin.get("schemaVersion") == 1
        and admin.get("scope") == "development-local-admin"
        and admin.get("username") == normalized_id
        and isinstance(admin_hash, str)
        and check_password_hash(admin_hash, password)
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("provision", "verify"))
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--student-sid", default=DEV_STUDENT_SID)
    parser.add_argument("--admin-credential-file", type=Path)
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--confirm-local-development", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    paths = resolve_paths(args.runtime_root, args.admin_credential_file)
    if args.action == "provision":
        if not args.confirm_local_development or args.backup_dir is None:
            raise ProvisioningError("provision requires confirmation and an external backup directory")
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Confirm password: "):
            raise ProvisioningError("password confirmation did not match")
        receipt = provision(paths, args.account_id, password, args.student_sid, args.backup_dir)
    else:
        password = getpass.getpass("Password: ")
        receipt = {"ok": verify_provisioned(paths, args.account_id, password, args.student_sid), "verified": True}
        if receipt["ok"] is not True:
            raise ProvisioningError("provisioned credential verification failed")
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
