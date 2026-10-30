"""Retry only failed local formula startup with explicit process-local Windows caches."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

LAB = Path(__file__).resolve().parent
OUT = LAB / 'comparison_20261030_01'
RETRY = OUT / 'local_formula_retry_01'
RUNNER = LAB / 'compare_openai_ocr_20261030.py'
PYTHON = Path('C:/server-ocr/.venv-unimernet/Scripts/python.exe')


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def main():
    if RETRY.exists():
        raise ValueError('new retry output required')
    manifest = json.loads((OUT / 'RUN_MANIFEST.json').read_text(encoding='utf-8'))
    if digest(RUNNER) != manifest['sourceHashes'][str(RUNNER)]:
        raise ValueError('frozen inference source changed')
    RETRY.mkdir(exist_ok=False)
    for name in ('MODEL_INPUTS.json', 'RUN_MANIFEST.json'):
        shutil.copyfile(OUT / name, RETRY / name)
    records = []
    for engine in ('m3_h1', 'm3_h1_h2_h3'):
        engine_cache = RETRY / ('cache_' + engine)
        engine_cache.mkdir(exist_ok=False)
        env = {name: os.environ[name] for name in ('SYSTEMROOT', 'WINDIR', 'PATH', 'USERNAME', 'USERDOMAIN', 'LOCALAPPDATA', 'APPDATA')
               if name in os.environ}
        env.update({'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'NO_ALBUMENTATIONS_UPDATE': '1',
                    'PYTHONDONTWRITEBYTECODE': '1', 'STUDENT_TEST_OCR_DEVICE': 'cpu', 'OMP_NUM_THREADS': '2',
                    'MKL_NUM_THREADS': '2', 'HF_HOME': str(engine_cache / 'hf'), 'TORCH_HOME': str(engine_cache / 'torch'),
                    'TORCHINDUCTOR_CACHE_DIR': str(engine_cache / 'inductor'), 'MPLCONFIGDIR': str(engine_cache / 'matplotlib'),
                    'TEMP': str(engine_cache), 'TMP': str(engine_cache)})
        started = time.perf_counter()
        with (RETRY / f'{engine}_stdout.txt').open('x', encoding='utf-8') as stdout, \
             (RETRY / f'{engine}_stderr.txt').open('x', encoding='utf-8') as stderr:
            try:
                completed = subprocess.run([str(PYTHON), '-B', str(RUNNER), 'worker', '--output', str(RETRY), '--engine', engine],
                                           cwd=RETRY, env=env, stdout=stdout, stderr=stderr, timeout=600,
                                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                state = 'succeeded' if completed.returncode == 0 else 'failed'
            except subprocess.TimeoutExpired:
                state = 'timeout'
        records.append({'engine': engine, 'state': state, 'wallSecondsIncludingStartupAndHashes': time.perf_counter() - started})
        if state == 'succeeded':
            for suffix in ('predictions.jsonl', 'metadata.json'):
                source = RETRY / f'local_{engine}_{suffix}'
                target = OUT / f'local_retry_{engine}_{suffix}'
                if target.exists():
                    raise ValueError('preserve existing retry result')
                shutil.copyfile(source, target)
                assert digest(source) == digest(target)
        print(json.dumps(records[-1]), flush=True)
    with (OUT / 'LOCAL_RETRY_EXECUTION.json').open('x', encoding='utf-8') as stream:
        json.dump({'results': records, 'providerCallCount': 0, 'processEnvironmentOnly': True,
                   'packagesInstalled': False, 'originalFailuresPreserved': True, 'retryRunnerSha256': digest(Path(__file__))},
                  stream, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
