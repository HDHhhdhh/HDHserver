"""Independent synthetic-only checks for bulk preparation/evaluation repairs."""
from __future__ import annotations
import argparse
import dataclasses
import importlib
import json
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch
LAB = Path(__file__).resolve().parent
OCR = Path(r"C:\server-ocr")
sys.path[:0] = [str(LAB), str(OCR)]
import human_transcription_eval as human
import evaluate_ocr_result as evaluate
import review_policy_evaluator as policy
import gemini_contact_io as contact
import apply_contact_review_policy as apply_policy
import ocr_benchmark_gate as gate
import run_ocr_regression_suite as suite

def expect_error(action, label):
    try:
        action()
    except (ValueError, human.HumanEvalError, evaluate.EvaluateOcrError, policy.ReviewPolicyError):
        return
    raise AssertionError(label)

def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-root", type=Path, required=True)
    out = parser.parse_args().out_root.resolve()
    qa = (LAB / "_qa_tmp" / "verify_bulk_eval_repair_20261009").resolve()
    if not out.is_relative_to(qa) or out.exists():
        raise ValueError("fresh verifier-specific lab QA output is required")
    out.mkdir(parents=True)
    checks = []
    expected = {"items": [{"question": q, "expected": str(q)} for q in range(1,21)]}
    recognized = {"items": [{"question": q, "recognized": str(q), "needs_review": False, "warnings": []} for q in range(1,21)]}
    labels = {"answers": [{"question_no": q, "human_answer": str(q), "confidence": "high", "notes": "independent synthetic label"} for q in range(1,21)]}
    expected_path = write_json(out / "expected_synthetic.json", expected)
    recognized_path = write_json(out / "recognized_synthetic.json", recognized)
    human_path = write_json(out / "human_synthetic.json", labels)
    assert not human.answers_match("2*3", "23")
    assert not human.answers_match("2 3", "23")
    assert human.answers_match("x = 2", "x=2")
    assert not human.answers_match("?", "?") and not human.answers_match("", "")
    checks.append("normalization_preserves_answer_tokens")
    for module in (evaluate, policy, contact):
        matcher = module.normalize if module is evaluate else module.compact if module is policy else module._compact
        assert matcher("2 3") != matcher("23") and matcher("2*3") != matcher("23")
    for mutation in ("bool", "duplicate", "missing", "range", "answer_type", "review_type", "warnings_type", "uncertainty_type"):
        payload = json.loads(json.dumps(recognized))
        if mutation == "bool": payload["items"][0]["question"] = True
        elif mutation == "duplicate": payload["items"][1]["question"] = 1
        elif mutation == "missing": payload["items"].pop()
        elif mutation == "range": payload["items"][0]["question"] = 21
        elif mutation == "answer_type": payload["items"][0]["recognized"] = 1
        elif mutation == "review_type": payload["items"][0]["needs_review"] = 0
        elif mutation == "warnings_type": payload["items"][0]["warnings"] = "uncertain"
        else: payload["items"][0]["uncertainty"] = []
        path = write_json(out / (mutation+".json"), payload)
        for action in (lambda: human.load_recognized(path), lambda: evaluate.load_recognized(path), lambda: policy.load_items(path,"recognized"), lambda: contact.parse_gemini_json(json.dumps(payload)), lambda: apply_policy.load_recognized(path)):
            expect_error(action, "accepted invalid schema: "+mutation)
    checks.append("strict_twenty_question_schema_eight_negative_cases_five_loaders")
    for bad in ("?", "", "2 3", "2*3"):
        e=evaluate.ExpectedItem(1, "23" if bad not in {"?", ""} else bad, ("23" if bad not in {"?", ""} else bad,))
        row=evaluate.evaluate_item(e,evaluate.RecognizedItem(1,bad,()))
        assert not row.accepted_match and row.review_policy != "safe_auto_grade"
        assert policy.evaluate_item(1,e.expected,bad).review_policy != "safe_auto_grade"
        assert contact.evaluate((contact.ExpectedAnswer(1,e.expected),),(contact.RecognitionItem(1,bad,False,()),))[0].review_policy != "safe_auto_grade"
    assert evaluate.evaluate_item(evaluate.ExpectedItem(1,"1",("1",)),evaluate.RecognizedItem(1,"1",(),True)).review_policy == "review_required"
    assert policy.evaluate_item(1,"1","1",needs_review=True).review_policy == "review_required"
    checks.append("placeholder_mismatch_and_model_review_are_never_safe")
    altered = json.loads(json.dumps(recognized))
    altered["items"][0]["recognized"] = "?"
    altered["items"][1]["needs_review"] = True
    altered_path = write_json(out / "uncertain_synthetic.json",altered)
    config=human.CliConfig(out,expected_path,altered_path,human_path)
    rows=human.evaluate_rows(config,human.load_expected(expected_path),human.load_recognized(altered_path),human.load_human(human_path),{q:"safe_auto_grade" for q in range(1,21)})
    summary=human.summarize(rows)
    assert summary.source_wrong_safe_auto_grade_against_human_transcription == 2
    assert summary.wrong_safe_auto_grade_against_human_transcription == 0
    assert summary.missing == 1 and summary.exact_or_normalized_match == 19
    # Answer-key agreement cannot stand in for independent human recognition.
    independent = {q:human.Answer(q,"independent" if q==3 else str(q)) for q in range(1,21)}
    independent_rows=human.evaluate_rows(config,human.load_expected(expected_path),human.load_recognized(recognized_path),independent,{})
    assert independent_rows[2].match_to_expected and not independent_rows[2].match_to_human
    checks.append("independent_human_truth_and_wrong_safe_placeholder_count")
    policy_dir=out/"policy_only"
    policy_dir.mkdir()
    old_raw=policy_dir/"gemini_raw.json"
    old_raw.write_bytes(b"preserved legacy raw evidence")
    before=old_raw.read_bytes()
    contact.write_outputs(policy_dir,contact.load_expected(expected_path),apply_policy.load_recognized(recognized_path),None,"synthetic")
    assert old_raw.read_bytes()==before and not (policy_dir/"raw_runs").exists()
    malformed="{not valid JSON"
    raw=contact.persist_raw_response(out/"raw",{"response":malformed},run_id="synthetic-run",request_index=1)
    expect_error(lambda:contact.parse_gemini_json(malformed),"invalid raw parsed")
    assert json.loads(raw.read_text())["response"] == malformed
    try: contact.persist_raw_response(out/"raw",{"response":"replacement"},run_id="synthetic-run",request_index=1)
    except FileExistsError: pass
    else: raise AssertionError("raw was overwritten")
    checks.append("raw_before_parse_exclusive_and_policy_preserves_raw")
    assert gate.scan_payload_for_leaks({"items":[{"recognized":"1"}]})["status"]=="passed"
    assert gate.scan_payload_for_leaks({"expected":"1","recognized":r"C:\private\q001.png"})["status"]=="failed"
    assert gate.scan_student_payloads(out)["status"]=="not_run"
    missing_case=gate.read_case(out,gate.CaseConfig("absent","absent","eval.json","synthetic",True,False))
    assert missing_case.wrong_safe_auto_grade is None and gate.feature_flag_blockers_for((missing_case,))
    result=suite.run_command(suite.CommandSpec("missing","core",("never-run",),out/"missing.py"))
    assert result.status=="blocked" and suite.summary_payload([result])["ok"] is False and suite.summary_payload([])["ok"] is False
    empty_gate=gate.build_gate_report(out/"empty_gate")
    assert empty_gate["ok"] is False and empty_gate["feature_flag_integration_allowed"] is False and empty_gate["gate_status"].startswith("BLOCKED")
    assert empty_gate["student_facing_leak_scan"]["status"]=="not_run"
    checks.append("missing_evidence_and_required_verifier_block_not_pass")
    # Mock image primitives only; execute the real preparation/batch control flow.
    @dataclasses.dataclass
    class Marker:
        x:int=0
    @dataclasses.dataclass
    class AssetConfig:
        crop_dir:Path
        out_dir:Path
        prefix:str
        debug_questions:tuple
    detection=types.SimpleNamespace(source="detected", boxes={q:(0,0,1,1) for q in range(1,21)})
    extract=types.ModuleType("extract_answer_sheet_crops")
    extract.read_image=lambda path: "synthetic_image"
    extract.find_markers=lambda image:(Marker(),)*4
    extract.select_markers=lambda markers:markers
    extract.warp_sheet=lambda image,markers:"synthetic_warp"
    extract.detect_answer_boxes=lambda warped:detection
    extract.analyze_warp_quality=lambda warped,boxes:{"ok":True,"failures":[],"answer_box_source":boxes.source}
    def crops(path,warped,boxes):
        assert boxes is detection
        for q in range(1,21):(path/f"q{q:03d}.png").write_bytes(b"synthetic crop")
    extract.write_question_crops=crops
    extract.write_warp_debug=lambda path,warped,markers,boxes: None
    extract.write_quality=lambda path,quality:write_json(path/"crop_quality.json",quality)
    images=types.ModuleType("gemini_contact_images")
    def enhance(crop_dir,out_dir):
        path=out_dir/"enhanced"/"q001.png";path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b"synthetic");return(path,)
    images.prepare_enhanced=enhance
    images.prepare_hard_enhanced=enhance
    images.build_contact_sheet=lambda crop,enhanced,questions,path:(path.parent.mkdir(parents=True,exist_ok=True),path.write_bytes(b"synthetic contact"))
    assets=types.ModuleType("make_review_contact_assets")
    assets.AssetConfig=AssetConfig
    assets.prompt_text=lambda:"Synthetic image-only prompt"
    def sheets(config,enhanced):
        paths=tuple(config.out_dir/"contact_sheets"/f"contact_{i}.png" for i in range(4))
        for path in paths:path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b"synthetic sheet")
        return paths
    assets.write_contact_sheets=sheets
    assets.write_debug_sheets=lambda *args:()
    assets.write_manifest=lambda config,*args:write_json(config.out_dir/"asset_manifest.json",{"synthetic":True})
    with patch.dict(sys.modules,{"extract_answer_sheet_crops":extract,"gemini_contact_images":images,"make_review_contact_assets":assets}):
        prep=importlib.import_module("prepare_incoming_case")
        batch=importlib.import_module("batch_prepare_incoming_cases")
        support=importlib.import_module("incoming_case_support")
        incoming=out/"incoming"/"synthetic_case"
        incoming.mkdir(parents=True)
        (incoming/"full_sheet.jpg").write_bytes(b"independently generated synthetic photo bytes")
        write_json(incoming/"expected.json",expected)
        cfg=support.IntakeConfig("synthetic_case",incoming.parent,out/"prepared",None,None,(),"synthetic_exam","1","answer_sheet_20_v1")
        prepared=prep.prepare_case(cfg)
        validation=support.validate_prepared_case(prepared)
        assert validation.crops==20 and validation.contact_sheets==4 and validation.labels_outside_answer_boxes is None
        assert prepared.provenance["test_id"]=="synthetic_exam"
        support.write_case_metadata(prepared,validation)
        support.write_pending_eval_files(prepared)
        pending=json.loads((prepared.pending_eval_dir/"pending_evaluation.json").read_text())
        assert "--source-image" in pending["safe_provider_command"] and "--identity-file" not in pending["safe_provider_command"]
        detection.source="fixed_fallback"
        fallback=dataclasses.replace(cfg,out_root=out/"fallback")
        try:prep.prepare_case(fallback)
        except support.IntakeError:pass
        else:raise AssertionError("fixed fallback silently prepared")
        detection.source="detected"
        bc=batch.BatchConfig(incoming.parent,out/"batch_out",("missing_case","synthetic_case"),(),(),False,"synthetic_exam","1","answer_sheet_20_v1")
        with patch.object(batch,"parse_args",return_value=bc), patch.object(batch,"prepare_case",side_effect=TypeError("synthetic dependency mismatch")):
            assert batch.main()==1
        report=json.loads((incoming.parent/batch.REPORT_JSON).read_text())
        assert [r["status"] for r in report["results"]]==["missing_inputs","failed"]
        assert [r["stage"] for r in report["results"]]==["input_discovery","preparation"]
        report_path=incoming.parent/batch.REPORT_JSON
        old_report=report_path.read_bytes()
        new_report=batch.write_report(incoming.parent,())
        assert new_report != report_path and report_path.read_bytes()==old_report
        benchmark=importlib.import_module("gemini_contact_benchmark")
        args=types.SimpleNamespace(allow_provider_call=True,max_calls=1,append=False,crop_dir=str(prepared.crop_dir),expected=str(expected_path),out_dir=str(out/"legacy_benchmark"),model="synthetic",only_groups="1")
        with patch.object(benchmark,"_parse_args",return_value=args),patch.object(benchmark.os,"environ",{"GEMINI_API_KEY":"synthetic-no-key"}),patch.object(benchmark,"_client",return_value=object()),patch.object(benchmark,"_call_gemini",return_value=malformed):
            expect_error(benchmark.main,"malformed legacy response should fail")
        saved=list((out/"legacy_benchmark"/"raw_runs").glob("*/request_001.json"))
        assert len(saved)==1 and json.loads(saved[0].read_text())["response"]==malformed
        class FakeSdkError(Exception):
            body={"message":"synthetic failure", "api_key":"never-store-this", "headers":{"x":"private"}, "path":r"C:\private\secret.png"}
        error_args=types.SimpleNamespace(**vars(args))
        error_args.out_dir=str(out/"legacy_sdk_error")
        with patch.object(benchmark,"_parse_args",return_value=error_args),patch.object(benchmark.os,"environ",{"GEMINI_API_KEY":"synthetic-no-key"}),patch.object(benchmark,"_client",return_value=object()),patch.object(benchmark,"_call_gemini",side_effect=FakeSdkError("do not print exception text")):
            try:benchmark.main()
            except benchmark.GeminiBenchmarkError as exc:
                assert "do not print" not in str(exc)
            else:raise AssertionError("SDK error accepted")
        sdk_raw=list((out/"legacy_sdk_error"/"raw_runs").glob("*/request_001.json"))
        assert len(sdk_raw)==1
        sdk_text=sdk_raw[0].read_text()
        sdk_data=json.loads(sdk_text)
        assert sdk_data["response_body_available"] is True and sdk_data["response_body"]["message"]=="synthetic failure"
        assert "never-store-this" not in sdk_text and "headers" not in sdk_text and "C:" not in sdk_text
    checks.append("crop_contract_identity_quality_batch_and_legacy_parse_failure")
    # Import pure cached helper only, never its operational main.
    cached=importlib.import_module("verify_cached_ocr_regression_suite")
    missing=cached.summarize_existing_eval("synthetic_missing",out/"absent_eval.json")
    assert missing.evidence_status=="missing" and not cached.cached_gate_passes([missing])
    cached_dir=out/"cached_synthetic"
    good_rows=human.evaluate_rows(config,human.load_expected(expected_path),human.load_recognized(recognized_path),human.load_human(human_path),{q:"safe_auto_grade" for q in range(1,21)})
    good_summary=human.summarize(good_rows)
    cached_path=write_json(cached_dir/"human_transcription_eval.json",{"summary":dataclasses.asdict(good_summary),"items":[dataclasses.asdict(row) for row in good_rows]})
    existing=cached.summarize_existing_eval("synthetic",cached_path)
    assert existing.leak_scan_status=="not_run" and not cached.cached_gate_passes([existing])
    write_json(cached_dir/"student_review_payload.json",{"items":[{"question_no":q,"recognized":str(q)} for q in range(1,21)]})
    assert cached.cached_gate_passes([cached.summarize_existing_eval("synthetic",cached_path)])
    stale=json.loads(cached_path.read_text())
    stale["items"][0]["recognized"]="?"
    write_json(cached_path,stale)
    unsafe=cached.summarize_existing_eval("synthetic",cached_path)
    assert unsafe.wrong_safe_auto_grade==1 and not cached.cached_gate_passes([unsafe])
    assert gate.wrong_safe_auto_grade_for(cached_dir,{})==1
    assert gate.transcription_metric(cached_dir).available is False
    checks.append("cached_missing_evaluator_cannot_pass")
    report={"ok":True,"checks":checks,"checks_passed":len(checks),"provider_calls":0,"student_operational_files_read":0,"database_calls":0,"output":str(out)}
    write_json(out/"verification.json",report)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0
if __name__=="__main__":raise SystemExit(main())
