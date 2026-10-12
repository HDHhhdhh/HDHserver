"""Offline acceptance suite: synthetic image -> real crops -> fake transport -> real review UI -> bridge."""
from __future__ import annotations
import argparse, io, shutil, base64, dataclasses, hashlib, json, socket, subprocess, sys, urllib.error, urllib.request, uuid
from pathlib import Path
LAB=Path(__file__).resolve().parent
REPO=LAB.parents[1]
for path in (REPO,LAB,Path(r"C:\server-ocr")):
    sys.path.insert(0,str(path))
# Never import app, route, database, model runtimes or environment-key readers.
socket.create_connection=lambda *a,**k: (_ for _ in ()).throw(AssertionError("network forbidden"))
socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError("network forbidden"))
urllib.request.urlopen=lambda *a,**k: (_ for _ in ()).throw(AssertionError("HTTP forbidden"))
from PIL import Image, ImageDraw, ImageFont
import extract_answer_sheet_crops as crop
import prepare_incoming_case as prep
from incoming_case_support import IntakeConfig
from tools.subjective_sheet_lab import gemini_provider as g
from tools.subjective_sheet_lab.ocr_provider_session import LAST_SESSION
from tools.subjective_sheet_lab.ocr_run_identity import *
from tools.subjective_sheet_lab.ocr_answers_text_bridge import convert_json_payload
from tools.subjective_sheet_lab.ocr_review_payload_validator import validate_payload
from tools.subjective_sheet_lab.ocr_review_schema import PayloadMode
from tools.subjective_sheet_lab.phase2e_stable_cache import StableOcrCacheRequest, stable_recognized_path_or_none
from tools.subjective_sheet_lab.phase2d_cached_review_payload_adapter import Phase2DRequest, load_recognized_cache, Phase2DCacheUnavailable
from types import SimpleNamespace
from unittest.mock import patch
import batch_prepare_incoming_cases as batch
from tools.subjective_sheet_lab import human_transcription_eval as human

VISUAL=("1","-3","2*3","2 3","1/2","0.25","x<=2","ㄱ,ㄷ","sqrt(2)","7",
        "3.5","-1/2","2+3","1/2,9/2","ㄴ,ㄹ","23","6","0","x=2","5")
# Fake provider response is deliberately wrong on q2; reviewer must reject all candidates.
OCR=("1","-7","2*3","2 3","1/2","0.25","x<=2","ㄱ,ㄷ","sqrt(2)","7",
     "3.5","-1/2","2+3","1/2,9/2","ㄴ,ㄹ","23","6","0","x=2","5")
TEST_ID="t_unit_offline_audit_r1"
def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("x",encoding="utf-8") as f: json.dump(value,f,ensure_ascii=False,indent=2)
def must_fail(fn):
    try: fn()
    except Exception: return
    raise AssertionError("invalid input unexpectedly passed")
def response(numbers, *, mutate=None):
    rows=[{"question":n,"recognized":OCR[n-1],"candidates":(["-7","3"] if n==2 else ([] if n==4 else [OCR[n-1]])),
           "uncertainty":"clear" if n!=2 else "ambiguous","needs_review":n==2} for n in numbers]
    if mutate: rows=mutate(rows)
    return {"candidates":[{"content":{"parts":[{"text":json.dumps({"items":rows},ensure_ascii=False)}]}}]}
def question_numbers(payload):
    result=[]
    for part in payload["contents"][0]["parts"]:
        text=part.get("text","")
        if text.startswith("contact_sheet="):
            result.extend(int(v.strip()) for v in text.split("questions=",1)[1].split(","))
        elif text.startswith("question="): result.append(int(text.split("=",1)[1]))
    assert result
    return result
class Fake:
    def __init__(self,failures=(),mutate=None): self.calls=[];self.failures=list(failures);self.mutate=mutate
    def __call__(self,payload,key,model):
        self.calls.append({"questions":question_numbers(payload),"image_count":sum("inline_data" in p for p in payload["contents"][0]["parts"])})
        serialized=json.dumps(payload,ensure_ascii=False)
        assert "answer_key" not in serialized.lower() and "expected" not in serialized.lower()
        assert "C:\\" not in serialized and "file://" not in serialized
        if self.failures:
            value=self.failures.pop(0)
            if value is not None: raise value
        return response(self.calls[-1]["questions"],mutate=self.mutate)
def config(root,prepared,**kw):
    root.mkdir(parents=True,exist_ok=True)
    base=dict(crop_dir=None,contact_dir=prepared.contact_dir,image_files=(),out_path=root/"recognized.json",
              model="gemini-2.5-flash-lite",resume=False,max_calls=4,test_id=TEST_ID,
              source_image=prepared.source_image,round_no="1",form_id=FORM_ID,prompt_version=PROMPT_VERSION,
              preprocessing_version=PREPROCESSING_VERSION)
    base.update(kw)
    return g.CliConfig(**base)
def make_photo(path):
    image=Image.new("RGB",(1600,2200),"white");draw=ImageDraw.Draw(image)
    fontpath=Path("C:/Windows/Fonts/malgun.ttf")
    font=ImageFont.truetype(str(fontpath),44) if fontpath.is_file() else ImageFont.load_default()
    for x,y in ((140,140),(1460,140),(1460,2060),(140,2060)):
        draw.rectangle((x-24,y-24,x+24,y+24),fill="black")
    for n,value in enumerate(VISUAL,1):
        x=295 if n<=10 else 920;y=438+((n-1)%10)*151
        draw.rectangle((x,y,x+485,y+116),outline="black",width=5)
        draw.text((x+18,y+25),str(n),fill="black",font=font)
        draw.text((x+115,y+25),value,fill="black",font=font)
    image.save(path)
def build_review(prepared,items,identity):
    rows=[]
    for item in items:
        data=(prepared.crop_dir/f"q{item.question:03d}.png").read_bytes()
        safe=item.question==1
        rows.append({"question_no":item.question,"status":"safe_auto_grade" if safe else "review_required",
            "recognized":item.recognized,"candidates":list(item.candidates),"warnings":[],
            "final_answer":item.recognized if safe else None,"source":"safe_auto_grade" if safe else None,
            "needs_review":item.needs_review,"uncertainty":item.uncertainty,"review_history":[],
            "identity_sha256":identity["identity_sha256"],
            "crop_preview":"data:image/png;base64,"+base64.b64encode(data).decode("ascii"),
            "crop_sha256":hashlib.sha256(data).hexdigest()})
    return {"schema":REVIEW_SCHEMA,"identity":identity,"test_id":TEST_ID,"round":"1","problem_count":20,
            "source":"offline_fake","items":rows,
            "photo_preview":"data:image/png;base64,"+base64.b64encode(prepared.source_image.read_bytes()).decode("ascii")}
def main():
    ap=argparse.ArgumentParser();ap.add_argument("--out-root",required=True,type=Path);args=ap.parse_args()
    out=args.out_root.resolve()
    if out.exists(): raise RuntimeError("fresh workspace required; existing artifacts preserved")
    out.mkdir(parents=True)
    results=[]
    def check(name,fn):
        try: detail=fn();results.append({"name":name,"status":"pass","detail":detail})
        except Exception as e: results.append({"name":name,"status":"fail","detail":f"{type(e).__name__}: {e}"})
    image=out/"synthetic_sheet.png";make_photo(image)
    # Key is independent of image transcription and never fed to provider/UI.
    expected=out/"independent_exam_key.json";dump(expected,{"items":[{"question":n,"expected":"99"} for n in range(1,21)]})
    dump(out/"independent_human_transcription.json",{"items":[{"question":n,"human_answer":v,"confidence":"high"} for n,v in enumerate(VISUAL,1)]})
    prepared=None
    def prepare():
        nonlocal prepared
        prepared=prep.prepare_case(IntakeConfig("offline_case",out/"incoming",out/"prepared",expected,image,(3,),
            test_id=TEST_ID,round_no="1",form_id=FORM_ID,model="gemini-2.5-flash-lite",
            prompt_version=PROMPT_VERSION,preprocessing_version=PREPROCESSING_VERSION))
        assert len(list(prepared.crop_dir.glob("q*.png")))==20 and len(prepared.contact_sheets)==4
        quality=json.loads((prepared.crop_root/"crop_quality.json").read_text(encoding="utf-8"))
        assert quality["ok"] and quality["answer_box_source"]!="fixed_fallback"
        ink_counts=[]
        for path in sorted(prepared.crop_dir.glob("q*.png")):
            pixels=crop.cv2.imread(str(path),crop.cv2.IMREAD_GRAYSCALE)
            ink_counts.append(int((pixels<180).sum()))
        assert len(ink_counts)==20 and min(ink_counts)>50, "blank or truncated synthetic answer crop"
        return {"crops":20,"contacts":4,"detection":quality["answer_box_source"],"min_answer_ink_pixels":min(ink_counts)}
    check("synthetic_photo_real_detection_crops_contacts",prepare)
    if prepared is None:
        dump(out/"verification.json",{"status":"fail","external_calls":0,"checks":results});print(json.dumps(results,ensure_ascii=False));return 1
    items=[];identity=None
    def normal():
        nonlocal items,identity
        fake=Fake();cfg=config(out/"normal",prepared)
        items=g.recognize_from_config(cfg,"",transport=fake,sleeper=lambda _:None)
        session=LAST_SESSION.get();identity=session.identity
        assert len(items)==20 and session.calls==4 and len(fake.calls)==4
        g.write_recognized_json(cfg.out_path,items,identity=identity)
        review=build_review(prepared,items,identity);validate_payload(review,PayloadMode.REVIEW,"normal")
        dump(out/"normal_review.json",review)
        return session.counts()
    check("fake_provider_strict_normal_run",normal)
    def mixed_batch():
        incoming=out/"mixed_incoming";incoming.mkdir()
        for name in ("good","bad","missing"):
            folder=incoming/name;folder.mkdir()
            dump(folder/"expected.json",{"items":[{"question":n,"expected":"99"} for n in range(1,21)]})
        shutil.copyfile(image,incoming/"good"/"full_sheet.png")
        Image.new("RGB",(1600,2200),"white").save(incoming/"bad"/"full_sheet.png")
        cfg=batch.BatchConfig(incoming,out/"mixed_output",("good","bad","missing"),(),(3,),False,TEST_ID,"1",FORM_ID)
        argv=["batch","--incoming-root",str(incoming),"--out-root",str(out/"mixed_output"),
              "--cases","good,bad,missing","--test-id",TEST_ID,"--round","1","--form-id",FORM_ID,"--debug-questions","3"]
        with patch.object(sys,"argv",argv):
            assert batch.main()==1
        report=json.loads((incoming/"batch_intake_report.json").read_text(encoding="utf-8"))
        states={r["case"]:r["status"] for r in report["results"]}
        assert states=={"good":"prepared","bad":"failed","missing":"missing_inputs"}
        assert all(row.get("stage") for row in report["results"])
        empty=incoming/"empty";empty.mkdir()
        argv2=["batch","--incoming-root",str(empty),"--out-root",str(out/"empty_output"),
               "--test-id",TEST_ID,"--round","1","--form-id",FORM_ID]
        with patch.object(sys,"argv",argv2):assert batch.main()==1
        return {"mixed":states,"stages_recorded":True,"empty_not_success":True}
    check("real_mixed_batch_bad_missing_empty_are_not_success",mixed_batch)
    def independent_evaluation():
        cfg=human.CliConfig(out/"independent_evaluation",expected,out/"normal"/"recognized.json",out/"independent_human_transcription.json")
        truth={n:human.Answer(n,v) for n,v in enumerate(VISUAL,1)}
        key={n:human.Answer(n,"99") for n in range(1,21)}
        # Independent visual transcription, separately wrong exam key.
        transcribed={n:human.Answer(n,v) for n,v in enumerate(VISUAL,1)}
        with patch.object(human,"infer_crop_dir",return_value=prepared.crop_dir):
            summary=human.summarize(human.evaluate_rows(cfg,key,transcribed,truth,{}))
        assert summary.ocr_recognition_accuracy_against_human_transcription==100.0
        assert summary.answer_key_grading_accuracy_recognized_vs_expected==0.0
        assert not human.answers_match("2*3","23") and not human.answers_match("2 3","23")
        for value in ("-3","0.25","1/2","x<=2","ㄱ,ㄷ"):
            assert human.answers_match(value,value)
        dump(out/"independent_evaluation.json",dataclasses.asdict(summary))
        return {"synthetic_transcription_match":100,"exam_key_match":0,"real_accuracy_claim":False}
    check("independent_transcription_separate_from_exam_grading",independent_evaluation)
    def resume():
        cfg=config(out/"resume",prepared,max_calls=2);f=Fake()
        must_fail(lambda:g.recognize_from_config(cfg,"",transport=f,sleeper=lambda _:None))
        assert len(f.calls)==2 and len(LAST_SESSION.get().items)==10
        cfg=dataclasses.replace(cfg,resume=True,max_calls=2);f2=Fake()
        rows=g.recognize_from_config(cfg,"",transport=f2,sleeper=lambda _:None)
        assert len(rows)==20 and len(f2.calls)==2 and min(f2.calls[0]["questions"])==11
        untouched=list(cfg.out_path.parent.glob("gemini_provider_cache.v1.*.json"))
        assert len(untouched)==4
        return {"initial_attempts":2,"resumed_attempts":2,"immutable_checkpoints":4}
    check("partial_resume_continues_unfinished_units",resume)
    def pending_manifest_and_source_guard():
        cfg=config(out/"resume",prepared,resume=True,max_calls=1,contact_batch_size=4)
        fake=Fake();must_fail(lambda:g.recognize_from_config(cfg,"",transport=fake));assert not fake.calls
        unit=config(out/"pending_changed",prepared,max_calls=1)
        must_fail(lambda:g.recognize_from_config(unit,"",transport=Fake()))
        changed=out/"changed_contacts";changed.mkdir()
        for path in prepared.contact_dir.glob("*.png"):
            shutil.copyfile(path,changed/path.name)
        target=sorted(changed.glob("*.png"))[-1]
        target.write_bytes(target.read_bytes()+b"changed pending bytes")
        f=Fake();must_fail(lambda:g.recognize_from_config(dataclasses.replace(unit,resume=True,contact_dir=changed,max_calls=4),"",transport=f));assert not f.calls
        changing=out/"changing_photo.png";shutil.copyfile(image,changing)
        cfg=config(out/"source_changed_during_retry",prepared,source_image=changing,max_calls=4,max_retries=1)
        calls=[]
        def change_source(payload,key,model):
            calls.append(1);changing.write_bytes(changing.read_bytes()+b"change")
            raise urllib.error.HTTPError("offline",503,"busy",None,io.BytesIO(b'{"error":"busy","api_key":"SYNTHETIC_PRIVATE","headers":{"authorization":"SYNTHETIC_HEADER"}}'))
        must_fail(lambda:g.recognize_from_config(cfg,"",transport=change_source,sleeper=lambda _:None))
        assert len(calls)==1
        raw="".join(path.read_text(encoding="utf-8") for path in LAST_SESSION.get().run_dir.glob("raw_*.json"))
        assert "busy" in raw and "SYNTHETIC_PRIVATE" not in raw and "SYNTHETIC_HEADER" not in raw
        return {"partition_changed_attempts":0,"pending_image_changed_attempts":0,"changed_source_retry_attempts":1,"error_body_sanitized":True}
    check("pending_partition_source_change_and_sensitive_error_body",pending_manifest_and_source_guard)
    def stale():
        cfg=config(out/"resume",prepared,resume=True,max_calls=4)
        variants=[dataclasses.replace(cfg,test_id="t_unit_other_r1"),dataclasses.replace(cfg,round_no="2"),
                  dataclasses.replace(cfg,form_id="other_form"),dataclasses.replace(cfg,model="other-model"),
                  dataclasses.replace(cfg,prompt_version="other_prompt"),dataclasses.replace(cfg,preprocessing_version="other_preprocess")]
        other=out/"other_photo.png";other.write_bytes(image.read_bytes()+b"changed")
        variants.append(dataclasses.replace(cfg,source_image=other))
        for variant in variants:
            f=Fake();must_fail(lambda:g.recognize_from_config(variant,"",transport=f));assert not f.calls
        req=StableOcrCacheRequest("synthetic",TEST_ID,1,image,out/"stable")
        base=stable_recognized_path_or_none(req)
        assert all(stable_recognized_path_or_none(dataclasses.replace(req,**v))!=base for v in
                   ({"provider_model":"other"},{"prompt_version":"other"},{"form_id":"other"},{"preprocessing_version":"other"},{"source_image":other}))
        return {"changed_identities_blocked":7,"stable_keys_changed":5}
    check("stale_photo_exam_round_form_model_prompt_preprocess_blocked",stale)
    def malformed():
        sample=[g.CropImage(n,Path(f"q{n:03d}.png"),"image/png","") for n in range(1,21)]
        mutations=[lambda r:r+r[:1],lambda r:r[:-1]]
        for bad in (0,21,True,1.5):
            mutations.append(lambda r,bad=bad:[{**r[0],"question":bad}]+r[1:])
        for mutate in mutations:
            text=g.extract_response_text(response(range(1,21),mutate=mutate))
            must_fail(lambda:g.parse_recognized_items(text,sample))
        must_fail(lambda:g.parse_recognized_items("{broken",sample))
        must_fail(lambda:g.parse_recognized_items('{"items":[],"items":[]}',sample))
        cfg=config(out/"malformed",prepared,contact_batch_size=4,max_calls=1)
        f=Fake(mutate=lambda r:r[:-1]);must_fail(lambda:g.recognize_from_config(cfg,"",transport=f))
        assert list(LAST_SESSION.get().run_dir.glob("raw_*.json")) and not LAST_SESSION.get().items
        return {"invalid_structures":8,"raw_preserved_before_parse":True}
    check("malformed_duplicate_missing_extra_boolean_fractional_questions",malformed)
    def failures():
        summaries=[]
        for branch in ("contact","crop"):
            extras={} if branch=="contact" else {"crop_dir":prepared.crop_dir,"contact_dir":None}
            for kind in ("429","503","timeout","retry_budget"):
                path=out/f"errors_{branch}_{kind}"
                err=(urllib.error.HTTPError("offline",429,"quota",None,None) if kind=="429" else
                     TimeoutError("offline timeout") if kind=="timeout" else urllib.error.HTTPError("offline",503,"busy",None,None))
                limit=1 if kind in {"429","retry_budget"} else 5
                cfg=config(path,prepared,max_calls=limit,max_retries=1,**extras)
                f=Fake(failures=(err,None))
                if kind in {"429","retry_budget"}:must_fail(lambda:g.recognize_from_config(cfg,"",transport=f,sleeper=lambda _:None))
                else:assert len(g.recognize_from_config(cfg,"",transport=f,sleeper=lambda _:None))==20
                assert len(f.calls)<=limit
                assert list(LAST_SESSION.get().run_dir.glob("raw_*.json"))
                summaries.append({"branch":branch,"kind":kind,"attempts":len(f.calls),"limit":limit})
        zero=config(out/"budget_zero",prepared,max_calls=0);z=Fake()
        must_fail(lambda:g.recognize_from_config(zero,"",transport=z));assert not z.calls
        numeric=config(out/"numeric_bad",prepared,numeric_only=True);n=Fake()
        must_fail(lambda:g.recognize_from_config(numeric,"",transport=n));assert not n.calls
        return summaries
    check("contact_crop_429_503_timeout_attempt_budget_raw",failures)
    def explicit_cache():
        req=Phase2DRequest("synthetic",TEST_ID,1,SimpleNamespace(source_image=image))
        cached=load_recognized_cache(out/"normal"/"recognized.json",req)
        assert cached.review_payload["identity"]==identity
        wrong=dataclasses.replace(req,test_id="t_unit_other_r1")
        must_fail(lambda:load_recognized_cache(out/"normal"/"recognized.json",wrong))
        old=out/"legacy_recognized.json";dump(old,{"items":[{"question":n,"recognized":"1"} for n in range(1,21)]})
        must_fail(lambda:load_recognized_cache(old,req))
        return {"valid_hit":True,"relabel_blocked":True,"legacy_preserved_not_reused":old.is_file()}
    check("explicit_cache_cannot_repackage_other_exam_or_legacy",explicit_cache)
    def wrapper_and_fallback():
        from tools.subjective_sheet_lab import phase2e_live_provider_runner as runner
        from tools.subjective_sheet_lab.phase2e_gemini_live_ocr_adapter import Phase2ERequest,Phase2EFeatureFlags
        from tools.subjective_sheet_lab import phase2f_local_paddle_review_adapter as local
        from tools.subjective_sheet_lab import phase2g_texteller_review_adapter as formula
        pipeline=SimpleNamespace(source_image=image,case_dir=prepared.crop_root,crop_dir=prepared.crop_dir,
            crop_quality=prepared.crop_root/"crop_quality.json",asset_manifest=prepared.asset_manifest,
            overwritten_ambiguity=None,contact_sheets=prepared.contact_sheets,crop_count=20,contact_sheet_count=4,
            case_id="offline_case")
        req=Phase2ERequest("synthetic",TEST_ID,1,pipeline,"cache_miss",{})
        flags=Phase2EFeatureFlags(True,True,False,True,2,True,True)
        fake=Fake()
        with patch.object(runner,"phase2e_variant_cache_root",return_value=out/"wrapper"),              patch.object(runner,"phase2e_provider_model",return_value="gemini-2.5-flash-lite"),              patch.object(runner,"phase2e_provider_prompt_version",return_value=PROMPT_VERSION),              patch.object(runner,"pipeline_ambiguity_warnings",return_value={}),              patch.object(g,"read_gemini_key",return_value=""),patch.object(g,"post_gemini",fake):
            result=runner.run_phase2e_live_provider(req,flags)
        assert result.provider_call_count==1 and result.review_payload["identity"]==identity
        validate_payload(result.review_payload,PayloadMode.REVIEW,"wrapper")
        typed=Phase2DRequest("synthetic",TEST_ID,1,pipeline)
        cached=load_recognized_cache(result.recognized_path,typed)
        assert cached.review_payload["identity"]==identity
        lines=[]
        for n in range(1,11):
            lines.extend([{"text":str(n)},{"text":str(n+10)},{"text":VISUAL[n-1],"confidence":0.99},
                          {"text":VISUAL[n+9],"confidence":0.99}])
        lreq=local.Phase2FRequest("synthetic",TEST_ID,1,pipeline)
        with patch.object(local,"run_local_ocr",return_value=lines),patch.object(local,"numeric_only_enabled",return_value=False),patch.object(local,"pipeline_ambiguity_warnings",return_value={}):
            local_payload=local.load_phase2f_local_review_payload(lreq)
        assert local_payload["schema"]==REVIEW_SCHEMA
        assert all(i["status"]=="review_required" for i in local_payload["items"])
        with patch.object(local,"numeric_only_enabled",return_value=True),patch.object(local,"run_local_ocr") as engine:
            must_fail(lambda:local.load_phase2f_local_review_payload(lreq));engine.assert_not_called()
        freq=formula.Phase2GRequest("synthetic",TEST_ID,1,pipeline,("answer_value",)*20)
        with patch.object(formula,"texteller_review_enabled",return_value=True),patch.object(formula,"load_overwritten_ambiguity_warnings",return_value={}):
            formula_payload=formula.load_phase2g_texteller_review_payload(freq,recognizer=lambda crops:{n:VISUAL[n-1] for n,_ in crops})
        assert formula_payload["items"][2]["recognized"]=="2*3"
        assert formula_payload["items"][3]["recognized"]=="2 3"
        return {"wrapper_attempts":1,"cache_bound":True,"paddle_fake_only":True,"formula_fake_only":True,
                "local_transcripts_preserved":True}
    check("wrapper_explicit_cache_local_fallback_share_run_contract",wrapper_and_fallback)
    def browser():
        completed=subprocess.run(["node",str(LAB/"verify_bulk_ocr_review_browser.js"),str(out)],cwd=REPO,capture_output=True,text=True,timeout=120)
        if completed.returncode:raise AssertionError(completed.stderr[-1200:] or completed.stdout[-1200:])
        evidence=json.loads((out/"browser_verification.json").read_text(encoding="utf-8"))
        assert evidence["status"]=="pass"
        return evidence
    if items:
        check("desktop_mobile_real_review_ui",browser)
        def bridge():
            final=json.loads((out/"final_review_payload.json").read_text(encoding="utf-8"))
            result=convert_json_payload(final);lines=result.answers_text.splitlines()
            assert len(lines)==20 and lines==list(VISUAL)
            assert final["items"][1]["recognized"]=="-7" and final["items"][1]["final_answer"]=="-3"
            assert any(h["action"]=="manual_input" for h in final["items"][1]["review_history"])
            (out/"answersText.txt").write_text(result.answers_text+"\n",encoding="utf-8")
            for bad in ("?","x?2","","a\nb"):
                clone=json.loads(json.dumps(final));clone["items"][0]["final_answer"]=bad;must_fail(lambda:convert_json_payload(clone))
            clone=json.loads(json.dumps(final));clone["items"][0]["expected"]="forbidden";must_fail(lambda:convert_json_payload(clone))
            clone=json.loads(json.dumps(final));clone["items"]=clone["items"][:-1];must_fail(lambda:convert_json_payload(clone))
            return {"lines":20,"manual_raw_preserved":True,"comma_formula_preserved":True,"invalid_final_blocked":6}
        check("actual_ui_export_strong_bridge_exact_20_lines",bridge)
    summary={"status":"pass" if all(r["status"]=="pass" for r in results) else "fail",
             "external_calls":0,"operational_imports":False,"synthetic_only":True,"checks":results}
    dump(out/"verification.json",summary)
    print(json.dumps({"status":summary["status"],"checks":[{"name":r["name"],"status":r["status"],"detail":r["detail"] if r["status"]!="pass" else None} for r in results],"evidence":str(out)},ensure_ascii=False))
    return 0 if summary["status"]=="pass" else 1
if __name__=="__main__":raise SystemExit(main())
