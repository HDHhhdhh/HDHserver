"""Server-side document rendering; no upstream authority in JSON responses."""
from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import time
from urllib.parse import quote, urlparse, parse_qs
from urllib.request import Request, urlopen

from flask import Response, redirect

from .contracts import ApiError
from .ledger import Ledger

FILE_ID = re.compile(r"^[A-Za-z0-9_-]{1,160}$")
MAX_BYTES = 32 * 1024 * 1024


def _file_id(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"drive.google.com", "docs.google.com"}:
        raise ApiError("content_unavailable", 503)
    match = re.search(r"/d/([A-Za-z0-9_-]+)", parsed.path)
    value = match[1] if match else parse_qs(parsed.query).get("id", [""])[0]
    if not FILE_ID.fullmatch(value):
        raise ApiError("content_unavailable", 503)
    return value


def source(assignment: dict, kind: str) -> tuple[str, str]:
    definition = assignment["definition"]
    files = definition.get("sourceFiles") or {}
    if kind == "solution":
        from routes import api_basic
        metadata = assignment["metadata"]
        # Assignment direct URL precedes assignment/config file IDs and map.
        direct = api_basic._assignment_direct_answer_url(metadata)
        if direct:
            return _file_id(direct), direct
        value = (metadata.get("solutionFileId") or (metadata.get("sourceFiles") or {}).get("solutionFileId")
                 or files.get("solutionFileId") or definition.get("solutionFileId"))
        if not value:
            direct = api_basic._test_assignment_answer_url(metadata)
            if direct:
                return _file_id(direct), direct
    else:
        value = files.get("problemFileId") or definition.get("problemFileId")
    if not isinstance(value, str) or not FILE_ID.fullmatch(value):
        raise ApiError("content_unavailable", 503)
    return value, f"https://drive.google.com/file/d/{value}/view"


def can_proxy() -> bool:
    return bool(os.environ.get("STUDENT_APP_CONTENT_ROOT") or os.environ.get("STUDENT_APP_DRIVE_ACCESS_TOKEN"))


def read_document(assignment: dict, kind: str) -> bytes:
    file_id, _ = source(assignment, kind)
    root = os.environ.get("STUDENT_APP_CONTENT_ROOT")
    try:
        if root:
            path = Path(root).resolve() / file_id
            # IDs cannot contain separators; resolving also rejects symlink escape.
            if not path.resolve().is_relative_to(Path(root).resolve()) or path.stat().st_size > MAX_BYTES:
                raise ApiError("content_unavailable", 503)
            data = path.read_bytes()
        else:
            token = os.environ.get("STUDENT_APP_DRIVE_ACCESS_TOKEN", "")
            url = (f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media" if token
                   else f"https://drive.google.com/uc?export=download&id={file_id}")
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            with urlopen(Request(url, headers=headers), timeout=15) as response:
                data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES or not (data.startswith(b"%PDF-") or data.startswith(b"\x89PNG\r\n\x1a\n")):
            raise ApiError("content_unavailable", 503)
        return data
    except ApiError:
        raise
    except Exception:
        raise ApiError("content_unavailable", 503) from None


def document(assignment: dict, kind: str, page: int | None = None):
    data = read_document(assignment, kind)
    if data.startswith(b"\x89PNG"):
        if page is None:
            return 1
        if page != 1:
            raise ApiError("invalid_page")
        return Response(data, mimetype="image/png")
    try:
        import fitz
        with fitz.open(stream=data, filetype="pdf") as pdf:
            if page is None:
                return len(pdf)
            if not 1 <= page <= len(pdf):
                raise ApiError("invalid_page")
            image = pdf[page - 1].get_pixmap(dpi=120).tobytes("png")
            return Response(image, mimetype="image/png")
    except ApiError:
        raise
    except Exception:
        raise ApiError("content_unavailable", 503) from None


def solution_redirect(assignment: dict, sid: str, ticket: str | None):
    ledger = Ledger()
    identifier = assignment["assignmentId"]
    if ticket:
        # Atomic consume is the authority; HMAC binds the issue path and the
        # nonce is never a reusable upstream link.
        target = ledger.consume_ticket(ticket, sid, identifier, int(time.time()))
        return redirect(target, 302)
    _, target = source(assignment, "solution")
    secret = os.environ.get("STUDENT_APP_SOLUTION_SIGNING_SECRET", "")
    if not secret:
        raise ApiError("solution_unavailable", 503)
    nonce = secrets.token_urlsafe(32)
    expiry = int(time.time()) + 60
    payload = f"{sid}\0{identifier}\0{expiry}\0{nonce}"
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    ticket = f"{nonce}.{expiry}.{signature}"
    ledger.issue_ticket(ticket, sid, identifier, target, expiry)
    return redirect(f"/api/mobile/student/tests/{quote(identifier, safe='')}/solution?ticket={ticket}", 302)
