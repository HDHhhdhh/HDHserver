"""Attach image identity to key-free review payloads; never grade or call OCR here."""
from __future__ import annotations
import base64, hashlib, json
from pathlib import Path
from .ocr_run_identity import REVIEW_SCHEMA, validate_run_identity
from .phase2e_stable_cache import deidentified_png_bytes
from .ocr_review_schema import find_forbidden_answer_key_paths


def validate_pipeline_input(pipeline, identity: dict) -> None:
    if hashlib.sha256(Path(pipeline.source_image).read_bytes()).hexdigest()!=identity["photo_sha256"]:
        raise ValueError("pipeline photograph changed")
    request_manifest=Path(pipeline.case_dir)/"request_manifest.json" if hasattr(pipeline,"case_dir") else None
    asset_manifest=Path(pipeline.asset_manifest) if hasattr(pipeline,"asset_manifest") else None
    if request_manifest is not None and request_manifest.is_file():
        data=json.loads(request_manifest.read_text(encoding="utf-8"))
        if data.get("photo_sha256")!=identity["photo_sha256"]:
            raise ValueError("pipeline manifest photograph mismatch or missing identity")
        if data.get("test_id")!=identity["test_id"] or str(data.get("round"))!=identity["round"]:
            raise ValueError("pipeline manifest test mismatch")
        for field in ("form_id","preprocessing_version"):
            if data.get(field)!=identity[field]: raise ValueError("pipeline manifest version mismatch")
    elif asset_manifest is not None and asset_manifest.is_file():
        data=json.loads(asset_manifest.read_text(encoding="utf-8"))
        original=validate_run_identity(data.get("identity"))
        for field in ("photo_sha256","test_id","round","form_id","preprocessing_version"):
            if original[field]!=identity[field]: raise ValueError("prepared crop identity mismatch")
    else:
        raise ValueError("prepared image provenance is missing")


def bind_review_payload(payload: dict, pipeline, identity: dict) -> dict:
    checked=validate_run_identity(identity)
    validate_pipeline_input(pipeline,checked)
    if find_forbidden_answer_key_paths(payload):
        raise ValueError("answer-key information is forbidden in review")
    seen=set();rows=[]
    for raw in payload["items"]:
        n=raw["question_no"]
        if type(n) is not int or n not in range(1,21) or n in seen:raise ValueError("review coverage invalid")
        seen.add(n)
        values=[]
        for candidate in raw.get("candidates",[]):
            value=candidate.get("value") if isinstance(candidate,dict) else candidate
            if isinstance(value,str) and value.strip() and "?" not in value and value.strip() not in values:
                values.append(value.strip())
        png=deidentified_png_bytes(Path(pipeline.crop_dir)/f"q{n:03d}.png")
        rows.append({"question_no":n,"status":raw["status"],"recognized":raw["recognized"],
            "candidates":values[:5],"warnings":list(raw.get("warnings",[])),
            "final_answer":raw.get("final_answer"),"source":raw.get("source"),
            "identity_sha256":checked["identity_sha256"],"review_history":list(raw.get("review_history",[])),
            "needs_review":raw.get("needs_review",True),"uncertainty":raw.get("uncertainty","unverified"),
            "crop_preview":"data:image/png;base64,"+base64.b64encode(png).decode("ascii"),
            "crop_sha256":hashlib.sha256(png).hexdigest()})
    if seen!=set(range(1,21)):raise ValueError("review requires exactly 20 questions")
    result={"schema":REVIEW_SCHEMA,"identity":checked,"test_id":checked["test_id"],
            "round":checked["round"],"problem_count":20,"source":payload.get("source","local_review"),
            "items":sorted(rows,key=lambda i:i["question_no"])}
    from .ocr_review_payload_validator import validate_payload
    from .ocr_review_schema import PayloadMode
    validate_payload(result,PayloadMode.REVIEW,"bound_review")
    return result
