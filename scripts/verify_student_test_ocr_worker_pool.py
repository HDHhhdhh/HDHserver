from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from core.student_test_ocr_engine import OcrCrop, OcrEngineError, WorkerSpec
from core.student_test_ocr_rules import ANSWER_VALUE
from core.student_test_ocr_worker_pool import ResidentWorkerPool
from scripts import student_test_choice_worker as choice
from scripts import student_test_formula_worker as formula
from scripts import student_test_paddle_worker as paddle
from scripts import student_test_unimernet_worker as unimernet

ROOT = Path(__file__).resolve().parents[1]
FAKE_WORKER = r'''
import argparse, json, os, sys, time
sys.path.insert(0, __SCRIPTS__)
from student_test_ocr_worker_server import serve
from student_test_unimernet_worker import parse_request
parser = argparse.ArgumentParser()
parser.add_argument('--serve-jsonl', action='store_true')
parser.add_argument('--no-read', action='store_true')
args = parser.parse_args()
if args.no_read:
    time.sleep(5)
count = 0
runtime = None
request_id = ''
original_loads = json.loads
def track_request(*args, **kwargs):
    global request_id
    value = original_loads(*args, **kwargs)
    if isinstance(value, dict) and 'requestId' in value:
        request_id = value['requestId']
    return value
json.loads = track_request
def event(kind, number=None):
    with open(os.environ['OCR_TEST_LOG'], 'a', encoding='utf-8') as stream:
        stream.write(json.dumps({'event':kind, 'pid':os.getpid(), 'questionNo':number})+'\n')
def run(items, options):
    global runtime, count
    if runtime is None:
        count += 1
        runtime = object()
        event('load')
    event('start', items[0][0])
    behavior = items[0][1].read_text(encoding='utf-8')
    if behavior == 'timeout': time.sleep(5)
    if behavior == 'slow': time.sleep(.25)
    if behavior == 'eof': os._exit(3)
    if behavior == 'garbage':
        sys.__stdout__.write('not-json\n'); sys.__stdout__.flush()
    if behavior == 'stale':
        sys.__stdout__.write(json.dumps({'schema':'student_test_ocr_worker_transport_v1',
          'requestId':'0'*32,'response':{'ok':True,'engine':'unimernet','items':[]}})+'\n')
        sys.__stdout__.flush()
    if behavior == 'oversize':
        sys.__stdout__.write('x'*1000001+'\n'); sys.__stdout__.flush()
    if behavior == 'logs': print('l'*250000, file=sys.stderr)
    if behavior == 'duplicate':
        response = {'ok':True,'engine':'unimernet','items':[{'questionNo':items[0][0]}]}
        sys.__stdout__.write('{"schema":"student_test_ocr_worker_transport_v1",'
          '"requestId":'+json.dumps(request_id)+',"requestId":'+json.dumps(request_id)+
          ',"response":'+json.dumps(response)+'}\n')
        sys.__stdout__.flush()
    if behavior == 'mutation':
        path = os.path.join(os.environ['STUDENT_TEST_OCR_UNIMERNET_MODEL_DIR'], 'weights.pth')
        with open(path,'ab') as stream: stream.write(b'changed during request')
    event('end', items[0][0])
    if behavior == 'missing': return []
    return [{'questionNo':number,'pid':os.getpid(),'loads':count,'options':options,
             'profile':os.environ.get('STUDENT_TEST_OCR_FORMULA_DATA_PROFILE','')}
            for number,path in items]
raise SystemExit(serve(engine='unimernet',parse_request=parse_request,run=run))
'''


def _expect(code: str, call) -> None:
    try:
        call()
    except OcrEngineError as error:
        assert error.code == code, (error.code, code)
    else:
        raise AssertionError(f"expected {code}")


def _events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def run() -> dict:
    assertions = 0
    for worker in (choice, paddle, formula, unimernet):
        original = worker._RUNTIME
        worker._RUNTIME = None
        try:
            marker = object()
            with patch.object(worker, "load_runtime", return_value=marker) as load:
                assert worker.cached_runtime() is marker and worker.cached_runtime() is marker
                assert load.call_count == 1
                assertions += 2
        finally:
            worker._RUNTIME = original
    with tempfile.TemporaryDirectory(prefix="student-test-resident-worker-") as directory:
        root = Path(directory)
        script = root / "fake_worker.py"
        script.write_text(FAKE_WORKER.replace("__SCRIPTS__", repr(str(ROOT / "scripts"))), encoding="utf-8")
        log = root / "events.jsonl"
        files = {}
        for behavior in ("normal", "slow", "timeout", "eof", "garbage", "stale", "oversize", "logs", "duplicate", "mutation", "missing"):
            path = root / f"{behavior}.txt"
            path.write_text(behavior, encoding="utf-8")
            files[behavior] = path
        spec = WorkerSpec("unimernet", Path(sys.executable), script, timeout_seconds=5,
                          environment={"OCR_TEST_LOG": str(log), "STUDENT_TEST_OCR_FORMULA_DATA_PROFILE": "m3_h1"})
        crop = lambda behavior="normal", number=1: (OcrCrop(number, ANSWER_VALUE, files[behavior]),)
        pool = ResidentWorkerPool()
        try:
            first = pool.run(spec, crop())["items"][0]
            second = pool.run(spec, crop(number=2))["items"][0]
            assert first["pid"] == second["pid"] and first["loads"] == second["loads"] == 1
            assert first["options"] == {"secondPass": False, "variantPass": False}
            assert sum(event["event"] == "load" for event in _events(log)) == 1
            assertions += 3
            options_spec = replace(spec, environment={**spec.environment,
                "STUDENT_TEST_OCR_UNIMERNET_SECOND_PASS": "1", "STUDENT_TEST_OCR_UNIMERNET_VARIANT_PASS": "true"})
            variant = pool.run(options_spec, crop())["items"][0]
            assert variant["pid"] == first["pid"] and variant["options"] == {"secondPass": True, "variantPass": True}
            assert pool.run(spec, crop())["items"][0]["options"] == {"secondPass": False, "variantPass": False}
            assertions += 2
            before = len(_events(log))
            barrier = threading.Barrier(3)
            def concurrent(number):
                barrier.wait(timeout=2)
                return pool.run(spec, crop("slow", number))
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(concurrent, number) for number in (3, 4)]
                barrier.wait(timeout=2)
                results = [future.result(timeout=5) for future in futures]
            observed = _events(log)[before:]
            assert [event["event"] for event in observed] == ["start", "end", "start", "end"]
            assert observed[0]["questionNo"] == observed[1]["questionNo"]
            assert observed[2]["questionNo"] == observed[3]["questionNo"]
            assert all(result["items"][0]["pid"] == first["pid"] for result in results)
            assertions += 4
            before = len(_events(log))
            with ThreadPoolExecutor(max_workers=1) as executor:
                active = executor.submit(pool.run, spec, crop("slow", 5))
                deadline = time.monotonic() + 2
                while len(_events(log)) <= before and time.monotonic() < deadline:
                    time.sleep(.005)
                assert len(_events(log)) > before
                _expect("ocr_engine_timeout", lambda: pool.run(replace(spec, timeout_seconds=.03), crop(number=6)))
                assert active.result(timeout=5)["items"][0]["pid"] == first["pid"]
            assert pool.run(spec, crop())["items"][0]["pid"] == first["pid"]
            assertions += 4
            changed = replace(spec, environment={**spec.environment, "STUDENT_TEST_OCR_FORMULA_DATA_PROFILE": "m3_h1_h2_h3"})
            upper = pool.run(changed, crop())["items"][0]
            assert upper["pid"] != first["pid"] and upper["profile"] == "m3_h1_h2_h3" and upper["loads"] == 1
            pid = upper["pid"]
            script.write_text(script.read_text(encoding="utf-8") + "\n# changed fixture\n", encoding="utf-8")
            assert pool.run(changed, crop())["items"][0]["pid"] != pid
            assertions += 2
            model_root = root / "model"
            model_root.mkdir()
            for name in ("weights.pth", "config.json", "preprocessor_config.json", "tokenizer_config.json", "tokenizer.json"):
                (model_root / name).write_bytes(b"model fixture")
            model_spec = replace(spec, environment={**spec.environment,
                "STUDENT_TEST_OCR_UNIMERNET_MODEL_DIR": str(model_root), "STUDENT_TEST_OCR_UNIMERNET_WEIGHT": "weights.pth"})
            pid = pool.run(model_spec, crop())["items"][0]["pid"]
            for name in ("weights.pth", "config.json", "preprocessor_config.json", "tokenizer_config.json", "tokenizer.json"):
                (model_root / name).write_bytes(b"changed model fixture")
                observed = pool.run(model_spec, crop())["items"][0]["pid"]
                assert observed != pid
                pid = observed
                assertions += 1
            _expect("ocr_engine_unavailable", lambda: pool.run(model_spec, crop("mutation")))
            assert pool.run(model_spec, crop())["items"][0]["pid"] != pid
            assertions += 2
            for model_key in ("STUDENT_TEST_OCR_CHOICE_MODEL_PATH", "STUDENT_TEST_OCR_PADDLE_MODEL_DIR", "STUDENT_TEST_OCR_FORMULA_MODEL_DIR"):
                value = model_root / "weights.pth" if model_key.endswith("MODEL_PATH") else model_root
                model_spec = replace(spec, environment={**spec.environment, model_key: str(value)})
                pid = pool.run(model_spec, crop())["items"][0]["pid"]
                path = model_root / "weights.pth"
                path.write_bytes(path.read_bytes() + b"different")
                assert pool.run(model_spec, crop())["items"][0]["pid"] != pid
                assertions += 1
            for behavior, code in (("timeout", "ocr_engine_timeout"), ("eof", "ocr_engine_failed"),
                                   ("garbage", "invalid_worker_response"), ("stale", "invalid_worker_response"),
                                   ("oversize", "invalid_worker_response"), ("duplicate", "invalid_worker_response"),
                                   ("missing", "invalid_worker_response")):
                previous = pool.run(spec, crop())["items"][0]["pid"]
                failed_spec = replace(spec, timeout_seconds=.5 if behavior == "timeout" else 5)
                _expect(code, lambda: pool.run(failed_spec, crop(behavior)))
                recovered = pool.run(spec, crop())["items"][0]
                assert recovered["pid"] != previous and recovered["loads"] == 1
                assertions += 2
            assert pool.run(spec, crop("logs"))["items"][0]["loads"] == 1
            assertions += 1
            started = time.monotonic()
            no_read = replace(spec, arguments=("--no-read",), timeout_seconds=.3)
            oversized_pipe_payload = (OcrCrop(1, ANSWER_VALUE, Path("x" * 14000)),)
            _expect("ocr_engine_timeout", lambda: pool.run(no_read, oversized_pipe_payload))
            assert time.monotonic() - started < 3
            assert pool.run(spec, crop())["items"][0]["loads"] == 1
            assertions += 3
            _expect("unsafe_worker_environment", lambda: pool.run(
                replace(spec, environment={"OCR_API_SECRET": "not-forwarded"}), crop()))
            assertions += 1
        finally:
            pool.shutdown()
        pool.shutdown()
        _expect("ocr_engine_unavailable", lambda: pool.run(spec, crop()))
        assertions += 1
        base = {"schema": "student_test_ocr_worker_transport_v1", "requestId": "a" * 32,
                "payload": {"schema": "student_test_ocr_worker_v1", "items": [{"questionNo": 1, "imagePath": str(files["normal"])}]},
                "options": {"secondPass": False, "variantPass": False}}
        for invalid in ({**base, "answerKeys": ["3"]}, {**base, "schema": "wrong"},
                        {**base, "options": {"secondPass": 1, "variantPass": False}},
                        {**base, "payload": {**base["payload"], "answerKeys": ["3"]}}):
            completed = subprocess.run([sys.executable, "-B", str(script), "--serve-jsonl"],
                input=json.dumps(invalid) + "\n", text=True, capture_output=True, timeout=5,
                env={**os.environ, "OCR_TEST_LOG": str(log)})
            assert completed.returncode == 1 and json.loads(completed.stdout)["response"]["ok"] is False
            assertions += 1
        encoded = json.dumps(base)
        duplicate = encoded[:-1] + ',"options":{"secondPass":false,"variantPass":false}}'
        completed = subprocess.run([sys.executable, "-B", str(script), "--serve-jsonl"],
            input=duplicate + "\n", text=True, capture_output=True, timeout=5,
            env={**os.environ, "OCR_TEST_LOG": str(log)})
        assert completed.returncode == 1 and json.loads(completed.stdout)["response"]["ok"] is False
        assertions += 1
    return {"name": "student-test-ocr-worker-pool", "assertions": assertions, "passed": True}


if __name__ == "__main__":
    result = run()
    print(f"{result['name']} passed: {result['assertions']} assertions")
