"""Network-denied adapter for the existing local OCR worker; no application imports."""
from __future__ import annotations
import json, os, subprocess, uuid
from pathlib import Path
from typing import TypedDict

class OcrLine(TypedDict, total=False):
    text: str
    confidence: float

class OcrError(RuntimeError):
    pass

def run_local_ocr(image_path: Path, workspace: Path, *, worker_runner=subprocess.run) -> list[OcrLine]:
    # New isolated runtime only. Never write existing model caches or operational data.
    workspace=workspace.resolve()
    roots=(Path(__file__).resolve().parent,Path("C:/server-ocr"))
    if not any(workspace.is_relative_to(root.resolve()) for root in roots):
        raise OcrError("local OCR workspace must stay inside an experiment root")
    run=workspace / ("run_"+uuid.uuid4().hex)
    run.mkdir(parents=True,exist_ok=False)
    runtime=Path("C:/server-ocr")
    worker=runtime/"ocr_worker.py"
    python=runtime/".venv/Scripts/python.exe"
    if not worker.is_file() or not python.is_file():
        raise OcrError("existing local OCR runtime is unavailable")
    launcher=(
        "import runpy,socket,urllib.request,sys;"
        "deny=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('offline network denied'));"
        "socket.socket.connect=deny;socket.create_connection=deny;urllib.request.urlopen=deny;"
        "sys.argv=[sys.argv[1],'--image',sys.argv[2]];"
        "runpy.run_path(sys.argv[0],run_name='__main__')"
    )
    env={name:os.environ[name] for name in ("SYSTEMROOT","WINDIR","PATH") if name in os.environ}
    env.update({"PYTHONDONTWRITEBYTECODE":"1","HF_HUB_OFFLINE":"1","TRANSFORMERS_OFFLINE":"1",
                "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK":"True","PADDLE_PDX_CACHE_HOME":str(run/"paddle_cache"),
                "HOME":str(run),"USERPROFILE":str(run),"TEMP":str(run),"TMP":str(run)})
    try:
        completed=worker_runner([str(python),"-B","-c",launcher,str(worker),str(image_path.resolve())],
                               cwd=run,env=env,capture_output=True,text=True,timeout=90,
                               creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        result=json.loads(completed.stdout)
    except (OSError,subprocess.TimeoutExpired,ValueError) as exc:
        raise OcrError("local OCR worker unavailable") from exc
    if completed.returncode or result.get("ok") is not True or not isinstance(result.get("lines"),list):
        raise OcrError("local OCR needs available offline weights; no download is allowed")
    lines=result["lines"]
    if any(not isinstance(line,dict) or not isinstance(line.get("text"),str) for line in lines):
        raise OcrError("local OCR line contract is invalid")
    return lines


def run_local_ocr_batch(image_paths: list[Path], workspace: Path, *, worker_runner=subprocess.run) -> tuple[list[dict], Path, dict]:
    """Use the installed Paddle worker once for 20 known crops, with private weight copies."""
    import hashlib, shutil
    from importlib.metadata import version
    workspace = workspace.resolve()
    roots = (Path(__file__).resolve().parent, Path('C:/server-ocr'))
    if not any(workspace.is_relative_to(root.resolve()) for root in roots):
        raise OcrError('offline batch workspace must stay inside the experiment roots')
    numbers = [int(p.stem[1:]) for p in image_paths if p.stem.startswith('q') and p.stem[1:].isdigit()]
    if numbers != list(range(1, 21)) or len(image_paths) != 20 or any(not p.is_file() for p in image_paths):
        raise OcrError('offline batch requires ordered existing q001..q020 crops')
    if any(not any(p.resolve().is_relative_to(r.resolve()) for r in roots) for p in image_paths):
        raise OcrError('offline input must stay in an experiment root')
    run = workspace / ('run_' + uuid.uuid4().hex)
    run.mkdir(parents=True, exist_ok=False)
    runtime = Path('C:/server-ocr')
    python = runtime / '.venv/Scripts/python.exe'
    worker = runtime / 'ocr_worker.py'
    models = {'detection': 'PP-OCRv5_server_det', 'recognition': 'korean_PP-OCRv5_mobile_rec'}
    provenance = {'engine': 'PaddleOCR', 'models': {}, 'weights_sha256': {}, 'package_versions': {}}
    model_dirs = {}
    for role, name in models.items():
        source = runtime / 'paddlex-cache/official_models' / name
        if not (source / 'inference.pdiparams').is_file():
            raise OcrError('installed offline Paddle weights are missing')
        target = run / 'weights' / name
        shutil.copytree(source, target)
        digest = hashlib.sha256((source / 'inference.pdiparams').read_bytes()).hexdigest()
        if hashlib.sha256((target / 'inference.pdiparams').read_bytes()).hexdigest() != digest:
            raise OcrError('offline weight copy identity mismatch')
        model_dirs[role] = str(target)
        provenance['models'][role] = name
        provenance['weights_sha256'][role] = digest
    for name in ('paddleocr', 'paddlepaddle', 'paddlex'):
        try: provenance['package_versions'][name] = version(name)
        except Exception: provenance['package_versions'][name] = 'unavailable'
    _write_batch_json(run/'request.json', {'images': [str(p.resolve()) for p in image_paths], 'image_sha256': [hashlib.sha256(p.read_bytes()).hexdigest() for p in image_paths], 'model_dirs': model_dirs})
    _write_batch_json(run/'model_provenance.json', provenance)
    launcher = run / 'offline_worker.py'
    launcher.write_text(_BATCH_LAUNCHER, encoding='utf-8')
    env = {n: os.environ[n] for n in ('SYSTEMROOT', 'WINDIR', 'PATH') if n in os.environ}
    env.update({'PYTHONDONTWRITEBYTECODE': '1', 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
                'PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK': 'True', 'PADDLE_PDX_CACHE_HOME': str(run/'cache'),
                'HOME': str(run), 'USERPROFILE': str(run), 'TEMP': str(run), 'TMP': str(run),
                'OMP_NUM_THREADS': '2', 'FLAGS_use_mkldnn': '0'})
    try:
        result = worker_runner([str(python), '-B', str(launcher), str(worker), str(run)], cwd=run,
                              env=env, capture_output=True, text=True, encoding='utf-8', errors='replace',
                              timeout=240, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except subprocess.TimeoutExpired as exc:
        (run/'stdout.txt').write_text(str(exc.stdout or ''), encoding='utf-8')
        (run/'stderr.txt').write_text(str(exc.stderr or ''), encoding='utf-8')
        raise OcrError('actual offline Paddle execution timed out') from exc
    (run/'stdout.txt').write_text(result.stdout, encoding='utf-8')
    (run/'stderr.txt').write_text(result.stderr, encoding='utf-8')
    if result.returncode != 0 or not (run/'parsed.json').is_file():
        raise OcrError('actual offline Paddle execution failed; preserved diagnostics are in its new run folder')
    parsed = json.loads((run/'parsed.json').read_text(encoding='utf-8'))
    if len(parsed) != 20 or [x.get('question') for x in parsed] != list(range(1,21)):
        raise OcrError('actual offline Paddle coverage is incomplete')
    return parsed, run, provenance


def _write_batch_json(path: Path, value) -> None:
    with path.open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)


_BATCH_LAUNCHER = r'''
import json, sys, socket, urllib.request, runpy, traceback, hashlib
from pathlib import Path
from contextlib import redirect_stdout
root=Path(sys.argv[2]); attempts=[]
def deny(*a, **k):
    attempts.append('blocked_before_network')
    raise RuntimeError('offline network denied')
socket.socket.connect=deny; socket.socket.connect_ex=deny; socket.socket.sendto=deny
socket.create_connection=deny; socket.getaddrinfo=deny; urllib.request.urlopen=deny
def write(name,value):
    with (root/name).open('x',encoding='utf-8') as f: json.dump(value,f,ensure_ascii=False,indent=2)
try:
    worker=runpy.run_path(sys.argv[1])
    request=json.loads((root/'request.json').read_text(encoding='utf-8'))
    with redirect_stdout(sys.stderr):
        from paddleocr import PaddleOCR
        ocr=worker['_build_paddle_ocr'](PaddleOCR, model_dirs=request['model_dirs'])
    rows=[]
    for n,image in enumerate(request['images'],1):
        expected=request['image_sha256'][n-1]
        if hashlib.sha256(Path(image).read_bytes()).hexdigest()!=expected: raise RuntimeError('crop changed before OCR')
        with redirect_stdout(sys.stderr): raw=worker['_run_paddle_on_file'](ocr,Path(image))
        if hashlib.sha256(Path(image).read_bytes()).hexdigest()!=expected: raise RuntimeError('crop changed during OCR')
        # Paddle's own JSON serialization is saved before our line parser is invoked.
        records=[getattr(record,'json',record) for record in raw]
        write('raw_q%03d.json'%n,records)
        lines=worker['_collect_lines_from_paddle_result'](raw)
        fragments=[]
        for record in records:
            native=record.get('res',record)
            texts=native.get('rec_texts',[]);boxes=native.get('rec_boxes',[])
            for index,text in enumerate(texts):
                fragments.append({'text':text,'box':boxes[index] if index<len(boxes) else None})
        # Preserve row separation, without guessing a fraction or mathematical operator.
        stacked=any(a['box'] is not None and b['box'] is not None and
                    (a['box'][3] <= b['box'][1] or b['box'][3] <= a['box'][1])
                    for i,a in enumerate(fragments) for b in fragments[i+1:])
        value=('\n' if stacked else ' ').join(fragment['text'] for fragment in fragments)
        rows.append({'question':n,'recognized':value,'lines':lines,'raw_fragments':fragments,
                     'layout_unresolved':len(fragments)>1,'unreadable':not value.strip(),
                     'needs_review':True,'uncertainty':'spatial_layout_unresolved' if len(fragments)>1 else 'local_model_unverified'})
        write('parsed_q%03d.json'%n,rows[-1])
    write('parsed.json',rows)
except Exception as exc:
    write('error.json',{'type':type(exc).__name__,'message':str(exc),'traceback':traceback.format_exc()})
    sys.exit(1)
finally:
    write('network_guard.json',{'external_calls':0,'blocked_attempts':len(attempts)})
'''