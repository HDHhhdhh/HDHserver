from __future__ import annotations

import datetime as dt
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Final, Protocol


RETENTION_DAYS: Final = 7
MAX_CAPTURE_BYTES: Final = 12 * 1024 * 1024
MIN_CAPTURE_BYTES: Final = 32
SAFE_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


@dataclass(frozen=True, slots=True)
class OcrAssetError(ValueError):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


class AssetRepository(Protocol):
    def register_asset(self, **kwargs) -> dict: ...

    def expired_assets(self, *, now: str, limit: int = 100, after_id: str = "") -> list[dict]: ...

    def purge_expired_asset(self, asset_id: str, *, now: str, unlink) -> str: ...


def _fail(code: str, message: str) -> None:
    raise OcrAssetError(code, message)


def _safe_id(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not SAFE_ID_RE.fullmatch(text):
        _fail("invalid_asset_identity", f"{label} is invalid")
    return text


def _image_extension(content: bytes) -> str:
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    _fail("unsupported_capture_format", "only JPEG and PNG camera captures are accepted")


def _validate_content(content: bytes) -> str:
    if not isinstance(content, bytes) or not MIN_CAPTURE_BYTES <= len(content) <= MAX_CAPTURE_BYTES:
        _fail("invalid_capture_size", "camera capture size is invalid")
    return _image_extension(content)


def _resolved_asset_path(root: Path, relative_path: str) -> Path:
    resolved_root = root.resolve()
    candidate = (resolved_root / relative_path).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError:
        _fail("invalid_asset_path", "OCR asset path escapes its storage root")
    return candidate


def expires_at_for(created_at: dt.datetime) -> dt.datetime:
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        _fail("invalid_asset_timestamp", "OCR asset timestamp must include a timezone")
    return created_at + dt.timedelta(days=RETENTION_DAYS)


def store_capture_file(
    *,
    root: Path,
    asset_id: str,
    submission_id: str,
    question_no: int | None,
    kind: str,
    content: bytes,
    created_at: dt.datetime,
) -> dict:
    safe_asset_id = _safe_id(asset_id, "asset id")
    safe_submission_id = _safe_id(submission_id, "submission id")
    extension = _validate_content(content)
    if kind not in {"full_sheet", "student_crop", "solution_crop"}:
        _fail("invalid_asset_kind", "OCR asset kind is invalid")
    if question_no is not None and (
        isinstance(question_no, bool) or not isinstance(question_no, int) or not 1 <= question_no <= 20
    ):
        _fail("invalid_asset_question", "OCR asset question number is invalid")
    if kind == "full_sheet" and question_no is not None:
        _fail("invalid_asset_question", "full-sheet capture cannot belong to one question")
    if kind != "full_sheet" and question_no is None:
        _fail("invalid_asset_question", "question crop must identify its question")

    prefix = "full-sheet" if question_no is None else f"q{question_no:03d}-{kind}"
    relative_path = f"{safe_submission_id}/{prefix}-{safe_asset_id}{extension}"
    target = _resolved_asset_path(root, relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{safe_asset_id}.tmp")
    if target.exists() or temporary.exists():
        _fail("asset_already_exists", "OCR asset already exists")

    try:
        with temporary.open("xb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
        expires_at = expires_at_for(created_at)
    except Exception:
        temporary.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        raise
    return {
        "id": safe_asset_id,
        "submission_id": safe_submission_id,
        "question_no": question_no,
        "kind": kind,
        "relative_path": relative_path,
        "expires_at": expires_at.isoformat(timespec="seconds"),
        "created_at": created_at.isoformat(timespec="seconds"),
        "absolute_path": str(target),
    }


def store_and_register_capture(
    repository: AssetRepository,
    *,
    root: Path,
    asset_id: str,
    submission_id: str,
    question_no: int | None,
    kind: str,
    content: bytes,
    created_at: dt.datetime,
) -> dict:
    stored = store_capture_file(
        root=root,
        asset_id=asset_id,
        submission_id=submission_id,
        question_no=question_no,
        kind=kind,
        content=content,
        created_at=created_at,
    )
    target = Path(stored["absolute_path"])
    try:
        registered = repository.register_asset(
            asset_id=stored["id"],
            submission_id=stored["submission_id"],
            question_no=question_no,
            kind=kind,
            relative_path=stored["relative_path"],
            expires_at=stored["expires_at"],
            created_at=stored["created_at"],
        )
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return {**registered, "absolute_path": str(target)}


def purge_expired_assets(
    repository: AssetRepository,
    *,
    root: Path,
    now: dt.datetime,
    limit: int = 100,
) -> dict:
    page = purge_expired_asset_page(repository, root=root, now=now, limit=limit)
    return {key: page[key] for key in ("examined", "deleted", "failed")}


def _unlink_registered_asset(root: Path, relative_path: str) -> None:
    relative = str(relative_path).replace("\\", "/")
    pieces = relative.split("/")
    if (not relative or relative.startswith("/") or PureWindowsPath(relative).drive
            or ":" in relative or any(piece in {"", ".", ".."} for piece in pieces)):
        _fail("invalid_asset_path", "OCR deletion path must be a contained relative file")
    lexical_root = root.absolute()
    if lexical_root.parent == lexical_root:
        _fail("invalid_asset_path", "OCR deletion root cannot be a drive root")
    target = lexical_root.joinpath(*pieces)
    # Never resolve a link and then unlink its target, even inside this root.
    chain = [*reversed(lexical_root.parents), lexical_root]
    for piece in pieces:
        chain.append(chain[-1] / piece)
    for path in chain:
        try:
            attributes = path.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(attributes.st_mode)
                or getattr(attributes, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024)):
            _fail("invalid_asset_path", "OCR deletion refuses links and reparse points")
        if path == target and not stat.S_ISREG(attributes.st_mode):
            _fail("invalid_asset_path", "OCR deletion accepts ordinary files only")
    if target.resolve() != target:
        _fail("invalid_asset_path", "OCR deletion path changed during validation")
    target.unlink(missing_ok=True)


def purge_expired_asset_page(
    repository: AssetRepository,
    *,
    root: Path,
    now: dt.datetime,
    limit: int = 100,
    after_id: str = "",
) -> dict:
    if now.tzinfo is None or now.utcoffset() is None:
        _fail("invalid_asset_timestamp", "OCR retention timestamp must include a timezone")
    now_text = now.astimezone(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec="seconds")
    rows = repository.expired_assets(now=now_text, limit=limit, after_id=after_id)
    deleted: list[str] = []
    failed: list[str] = []
    busy: list[str] = []
    for row in rows:
        asset_id = str(row.get("id") or "")
        try:
            outcome = repository.purge_expired_asset(
                asset_id, now=now_text,
                unlink=lambda current: _unlink_registered_asset(root, current["relative_path"]),
            )
            if outcome == "deleted":
                deleted.append(asset_id)
            elif outcome == "busy":
                busy.append(asset_id)
        except Exception:
            # Leave the row retryable after filesystem or transaction failures.
            failed.append(asset_id)
    return {"examined": len(rows), "deleted": tuple(deleted), "failed": tuple(failed),
            "busy": tuple(busy), "lastId": rows[-1]["id"] if rows else None}
