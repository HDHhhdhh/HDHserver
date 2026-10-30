"""Bounded, isolated OCR comparison. Never imports app or writes production state."""
from __future__ import annotations

import argparse
import base64
from collections import Counter
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import random
import re
import socket
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path('C:/server')
LAB = ROOT / 'tools/subjective_sheet_lab'
RUNTIME = Path('C:/server-ocr')
sys.path.insert(0, str(ROOT))
from core.student_test_ocr_rules import answer_values_equivalent, canonicalize_answer_text, numeric_answer_value

MODELS = ('gpt-6-luna', 'gpt-6.1-terra')
RATES = {'gpt-6-luna': (0.10, 0.01, 0.50), 'gpt-6.1-terra': (1.00, 0.05, 5.00)}
SEED = 20261030
GRADES = ('M_G3', 'H_G1', 'H_G2', 'H_G3')
PROMPT = ('Transcribe the single handwritten answer in the image exactly as written. '
          'Do not solve, simplify, correct, complete, or infer an intended answer. '
          'Preserve signs, decimal points, fraction structure, radicals and separated numbers. '
          'Use LaTeX for fractions and square roots. Do not merge separated numbers. '
          'If blank or unreadable, return recognized as an empty string and unreadable true. '
          'Set uncertain true for unclear, overwritten, crossed-out or multiple answers. '
          'Return only the required JSON. You have no answer key.')
FORMAT = {'type': 'json_schema', 'name': 'handwritten_answer', 'strict': True,
          'schema': {'type': 'object', 'additionalProperties': False,
                     'properties': {'recognized': {'type': 'string'}, 'unreadable': {'type': 'boolean'},
                                    'uncertain': {'type': 'boolean'}},
                     'required': ['recognized', 'unreadable', 'uncertain']}}


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_new(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def append(path, row):
    with Path(path).open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def jsonl(path):
    with Path(path).open(encoding='utf-8-sig') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def now():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat()


def kind(label):
    if len(label) > 60:
        return None
    try:
        numeric_answer_value(label)
    except Exception:
        return None
    if label in '12345' and len(label) == 1:
        return 'choice_digit'
    if '\\sqrt' in label or 'sqrt' in label or '√' in label:
        return 'root'
    if '\\frac' in label or '\\dfrac' in label or '\\tfrac' in label or '/' in label:
        return 'fraction'
    if re.fullmatch(r'[-+]?\d+(?:\.\d+)?', label):
        return 'number'
    return None


def prepare(out):
    from PIL import Image
    out = out.resolve()
    if not out.is_relative_to(LAB.resolve()) or out.exists():
        raise ValueError('fresh output below ignored lab required')
    dataset = RUNTIME / 'datasets/aihub_education/formula_profiles/validation/m3_h1_h2_h3'
    training = RUNTIME / 'datasets/aihub_education/formula_profiles/training/m3_h1_h2_h3/provenance.jsonl'
    labels = (dataset / 'equations.txt').read_text(encoding='utf-8-sig').splitlines()
    provenance = jsonl(dataset / 'provenance.jsonl')
    if len(labels) != len(provenance) or len(labels) != read(dataset / 'manifest.json')['count']:
        raise ValueError('dataset coverage mismatch')
    training_rows = jsonl(training)
    training_sources = {r['sourceHash'] for r in training_rows}
    training_writers = {(r['grade'], r['writerHash']) for r in training_rows}
    candidates = []
    for p, label in zip(provenance, labels):
        category = kind(label.strip())
        if category and p['sourceHash'] not in training_sources:
            candidates.append({**p, 'label': label.strip(), 'kind': category})
    writer_counts = Counter()
    selected, used_sources, used_images = [], set(), set()
    def select_one(eligible):
        eligible = [p for p in eligible if p['sourceHash'] not in used_sources]
        eligible.sort(key=lambda p: (writer_counts[(p['grade'], p['writerHash'])],
                      hashlib.sha256(f'{SEED}:{p["sourceHash"]}'.encode()).hexdigest()))
        for p in eligible:
            image = dataset / 'images' / f'{p["index"]:07d}.png'
            image_sha = sha(image)
            if image_sha in used_images:
                continue
            with Image.open(image) as opened:
                if opened.format != 'PNG' or opened.info.get('exif') or getattr(opened, 'text', {}):
                    raise ValueError('unexpected image metadata; do not transmit')
                size = list(opened.size)
            chosen = {**p, 'imagePath': str(image), 'imageSha256': image_sha, 'size': size}
            selected.append(chosen)
            used_sources.add(chosen['sourceHash'])
            used_images.add(chosen['imageSha256'])
            writer_counts[(p['grade'], p['writerHash'])] += 1
            return
        raise ValueError('insufficient fixed diagnostic stratum')
    # Inspect label availability before inference. H_G3 has no supported numeric labels.
    # Retain all 14 supported H_G2 rows, rather than inventing grade-balanced data.
    high2 = [p for p in candidates if p['grade'] == 'H_G2']
    if Counter(p['kind'] for p in high2) != Counter({'choice_digit': 3, 'fraction': 6, 'root': 5}):
        raise ValueError('expected high2 diagnostic cohort changed')
    for p in sorted(high2, key=lambda p: p['sourceHash']):
        select_one([p])
    target_counts = {'choice_digit': 16, 'number': 8, 'fraction': 8, 'root': 8}
    for category in ('root', 'fraction', 'number'):
        remaining = target_counts[category] - sum(p['kind'] == category for p in selected)
        for _ in range(remaining):
            select_one([p for p in candidates if p['grade'] in ('M_G3', 'H_G1') and p['kind'] == category])
    digit_targets = {'1': 4, '2': 3, '3': 3, '4': 3, '5': 3}
    for digit, target_count in digit_targets.items():
        remaining = target_count - sum(p['kind'] == 'choice_digit' and p['label'] == digit for p in selected)
        for _ in range(remaining):
            select_one([p for p in candidates if p['grade'] in ('M_G3', 'H_G1') and p['label'] == digit])
    random.Random(SEED).shuffle(selected)
    inputs, truth = [], []
    for index, p in enumerate(selected, 1):
        sample_id = f'S{index:03d}'
        profile = 'm3_h1' if p['grade'] in ('M_G3', 'H_G1') else 'm3_h1_h2_h3'
        inputs.append({'sampleId': sample_id, 'imagePath': p['imagePath'], 'imageSha256': p['imageSha256'],
                       'route': 'choice_digit' if p['kind'] == 'choice_digit' else profile})
        truth.append({k: p[k] for k in ('index', 'grade', 'writerHash', 'sourceHash', 'kind', 'label', 'size')})
        truth[-1]['sampleId'] = sample_id
    assert len(inputs) == 40 and len(used_images) == 40
    out.mkdir(parents=True, exist_ok=False)
    write_new(out / 'MODEL_INPUTS.json', inputs)
    write_new(out / 'TRUTH_EVALUATOR_ONLY.json', truth)
    source_files = [dataset / n for n in ('manifest.json', 'equations.txt', 'provenance.jsonl')]
    source_files += [training, ROOT / 'core/student_test_ocr_rules.py', Path(__file__),
                     ROOT / 'scripts/student_test_choice_worker.py',
                     ROOT / 'scripts/student_test_unimernet_worker.py',
                     ROOT / 'scripts/student_test_formula_inference.py']
    write_new(out / 'RUN_MANIFEST.json', {
        'schema': 'bounded_ocr_comparison_v1', 'createdAt': now(), 'seed': SEED,
        'models': list(MODELS), 'maximumCallsPerModel': 40, 'automaticRetries': 0,
        'reasoningEffort': 'none', 'serviceTier': 'default', 'apiStore': False,
        'sampleCount': 40, 'fixedDenominator': 40, 'dataset': str(dataset),
        'datasetRows': len(labels), 'selectedByGrade': dict(Counter(p['grade'] for p in selected)),
        'selectedByKind': dict(Counter(p['kind'] for p in selected)),
        'writerHashCountGradeScoped': len(writer_counts),
        'selectedTrainingSourceHashOverlap': 0,
        'selectedWriterHashOverlapWithTraining': sum((p['grade'], p['writerHash']) in training_writers for p in selected),
        'sourceHashes': {str(p): sha(p) for p in source_files},
        'inputManifestSha256': sha(out / 'MODEL_INPUTS.json'),
        'truthSha256': sha(out / 'TRUTH_EVALUATOR_ONLY.json'),
        'promptSha256': hashlib.sha256(PROMPT.encode()).hexdigest(),
        'prompt': PROMPT, 'responseFormat': FORMAT, 'ratesPerMillionTokens': RATES,
        'pricingSources': ['https://developers.openai.com/api/docs/models/' + m for m in MODELS],
        'answerKeyFieldsUsed': 0, 'deploymentReady': False,
        'scope': '40 isolated public-development crops; diagnostic routes, not actual exam metadata; not camera or sheet latency',
        'limits': ['stratified pilot, not population accuracy; all 14 supported high2 rows deliberately included',
                   'high3 supported numeric sample count is zero; no high3 accuracy claim',
                   'public validation previously used for model development',
                   'no independent real-camera/student holdout', 'writer hashes are grade-scoped, not verified identities',
                   'local confidence policy and full grading pipeline are not evaluated'],
    })
    print(json.dumps({'prepared': str(out), 'sampleCount': 40, 'kinds': dict(Counter(p['kind'] for p in selected)),
                      'writers': len(writer_counts)}, ensure_ascii=False), flush=True)


def validated_inputs(out):
    manifest = read(out / 'RUN_MANIFEST.json')
    if sha(out / 'MODEL_INPUTS.json') != manifest['inputManifestSha256']:
        raise ValueError('frozen model input manifest changed')
    inputs = read(out / 'MODEL_INPUTS.json')
    if len(inputs) != 40 or len({p['sampleId'] for p in inputs}) != 40:
        raise ValueError('fixed sample coverage mismatch')
    for p in inputs:
        if set(p) != {'sampleId', 'imagePath', 'imageSha256', 'route'} or sha(p['imagePath']) != p['imageSha256']:
            raise ValueError('frozen model input changed')
    return inputs


def secret_from_file(path):
    # No raw value, length, prefix, error excerpt, or fingerprint is logged.
    for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
        match = re.fullmatch(r'\s*OPENAI_API_KEY\s*=\s*(.*?)\s*', line)
        if match:
            value = match[1].strip().strip('\"\'')
            if value.startswith('sk-') and len(value) >= 30:
                return value
    raise ValueError('usable key is missing in the approved input file')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('API redirect refused')


def api(out, key_file):
    inputs = validated_inputs(out)
    key = secret_from_file(key_file)
    ledger_path = out / 'API_CALL_LEDGER.jsonl'
    predictions = out / 'api_predictions.jsonl'
    if ledger_path.exists() or predictions.exists():
        raise ValueError('refuse to rerun provider calls in an existing run')
    ledger_path.touch(exist_ok=False)
    predictions.touch(exist_ok=False)
    opener = urllib.request.build_opener(NoRedirect())
    counts = Counter()
    stopped = set()
    for sample in inputs:
        image = Path(sample['imagePath']).read_bytes()
        if hashlib.sha256(image).hexdigest() != sample['imageSha256']:
            raise ValueError('frozen image changed')
        content = [{'type': 'input_text', 'text': PROMPT},
                   {'type': 'input_image', 'image_url': 'data:image/png;base64,' + base64.b64encode(image).decode(), 'detail': 'high'}]
        for model in MODELS:
            if model in stopped:
                continue
            if counts[model] >= 40:
                raise ValueError('positive user call budget exhausted')
            request_body = {'model': model, 'input': [{'role': 'user', 'content': content}],
                            'reasoning': {'effort': 'none'}, 'text': {'format': FORMAT},
                            'max_output_tokens': 256, 'store': False, 'service_tier': 'default'}
            body = json.dumps(request_body).encode()
            # Only the whitelisted literal prompt/schema and PNG bytes leave this process.
            if any(marker in body for marker in (b'imagePath', b'writerHash', b'answerKeys', b'C:\\\\server', b'human_answer')):
                raise ValueError('provider payload leak audit failed')
            counts[model] += 1
            append(ledger_path, {'model': model, 'ordinal': counts[model], 'sampleId': sample['sampleId'],
                                'attemptedAt': now(), 'requestSha256': hashlib.sha256(body).hexdigest(),
                                'imageSha256': sample['imageSha256'], 'state': 'attempt_recorded_before_http'})
            row = {'model': model, 'sampleId': sample['sampleId'], 'ordinal': counts[model],
                   'state': 'failed', 'text': '', 'terminated': False, 'usage': None}
            started = time.perf_counter()
            try:
                request = urllib.request.Request('https://api.openai.com/v1/responses', data=body,
                          headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, method='POST')
                with opener.open(request, timeout=60) as response:
                    raw = json.loads(response.read())
                    row['requestId'] = response.headers.get('x-request-id')
                output_text = ''.join(part.get('text', '') for item in raw.get('output', [])
                                      if item.get('type') == 'message' for part in item.get('content', [])
                                      if part.get('type') == 'output_text')
                row.update({'responseId': raw.get('id'), 'responseModel': raw.get('model'),
                            'serviceTier': raw.get('service_tier'), 'usage': raw.get('usage'),
                            'responseStatus': raw.get('status'), 'outputText': output_text})
                parsed = json.loads(output_text)
                if set(parsed) != {'recognized', 'uncertain', 'unreadable'} or not isinstance(parsed['recognized'], str):
                    raise ValueError('response structure invalid')
                if type(parsed['uncertain']) is not bool or type(parsed['unreadable']) is not bool:
                    raise ValueError('response flags invalid')
                row.update({'state': 'succeeded', 'text': parsed['recognized'], 'uncertain': parsed['uncertain'],
                            'unreadable': parsed['unreadable'], 'terminated': raw.get('status') == 'completed'})
                # Preserve evidence without request headers or keys.
                write_new(out / f'{model}_{sample["sampleId"]}_response.json', raw)
            except urllib.error.HTTPError as error:
                row['httpStatus'] = error.code
                try:
                    error_data = json.loads(error.read()).get('error', {})
                    row['errorType'] = str(error_data.get('type') or '')[:80]
                    row['errorCode'] = str(error_data.get('code') or '')[:80]
                except Exception:
                    row['errorCode'] = 'unparsed_http_error'
                # Do not repeat invalid credentials, unavailable models, quota or configuration errors.
                if error.code in (400, 401, 403, 404, 429):
                    stopped.add(model)
            except Exception as error:
                row['errorType'] = type(error).__name__
            row['seconds'] = round(time.perf_counter() - started, 6)
            if key in json.dumps(row):
                raise RuntimeError('secret output refused')
            append(predictions, row)
            print(json.dumps({k: row.get(k) for k in ('model', 'sampleId', 'ordinal', 'state', 'seconds', 'httpStatus', 'errorCode')}), flush=True)
    write_new(out / 'API_EXECUTION.json', {'createdAt': now(), 'counts': dict(counts),
               'stoppedModels': sorted(stopped), 'maximumCallsPerModel': 40, 'automaticRetries': 0,
               'keySource': str(Path(key_file)), 'plaintextKeyLogged': False})


def deny_network(*args, **kwargs):
    raise RuntimeError('offline local inference network denied')


def worker(out, engine):
    inputs = validated_inputs(out)
    items = [p for p in inputs if p['route'] == engine]
    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network
    socket.socket.sendto = deny_network
    socket.create_connection = deny_network
    socket.getaddrinfo = deny_network
    urllib.request.urlopen = deny_network
    model_started = time.perf_counter()
    import torch
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch_load = torch.load
    def strict_load(*args, **kwargs):
        kwargs['weights_only'] = True
        kwargs['map_location'] = 'cpu'
        return torch_load(*args, **kwargs)
    torch.load = strict_load
    if engine == 'choice_digit':
        from scripts import student_test_choice_worker as choice
        model_path = RUNTIME / 'choice_digit_classifier_v3/choice_digit_v3.pt'
        runtime = choice.cached_runtime()
    else:
        from scripts import student_test_unimernet_worker as formula
        model_dir = RUNTIME / 'models' / ('unimernet_' + engine)
        model_path = model_dir / ('unimernet_' + engine + '.pth')
        runtime = formula.load_runtime(out / (engine + '_runtime.yaml'), model_dir, model_path.name)
    load_seconds = time.perf_counter() - model_started
    metadata = {'engine': engine, 'modelPath': str(model_path), 'modelSha256': sha(model_path),
                'modelLoadSeconds': load_seconds, 'device': 'cpu', 'threads': 2, 'torchVersion': torch.__version__,
                'weightsOnly': True, 'externalNetworkAllowed': False, 'providerCallCount': 0}
    if engine != 'choice_digit':
        metadata['modelAssetsSha256'] = {n: sha(model_dir / n) for n in ('config.json', 'preprocessor_config.json', 'tokenizer_config.json', 'tokenizer.json')}
    write_new(out / f'local_{engine}_metadata.json', metadata)
    for p in items:
        started = time.perf_counter()
        row = {'sampleId': p['sampleId'], 'model': 'local', 'engine': engine, 'state': 'failed', 'text': '', 'terminated': False}
        try:
            if sha(p['imagePath']) != p['imageSha256']:
                raise ValueError('frozen crop changed')
            if engine == 'choice_digit':
                result = choice.run([(1, Path(p['imagePath']))])[0]
                row.update({'text': result['text'], 'terminated': True, 'nativeResult': result})
            else:
                from PIL import Image
                with Image.open(p['imagePath']) as opened:
                    image = opened.convert('RGB')
                result = formula.infer_prediction(*runtime, image)
                row.update({'text': result['text'], 'terminated': result['terminated'], 'nativeResult': result})
            row['state'] = 'succeeded'
        except Exception as error:
            row['errorType'] = type(error).__name__
        row['seconds'] = round(time.perf_counter() - started, 6)
        append(out / ('local_' + engine + '_predictions.jsonl'), row)
        print(json.dumps({k: row.get(k) for k in ('model', 'sampleId', 'engine', 'state', 'seconds')}), flush=True)


def local(out):
    validated_inputs(out)
    if (out / 'LOCAL_EXECUTION.json').exists():
        raise ValueError('refuse local rerun in existing output')
    results = []
    for engine in ('choice_digit', 'm3_h1', 'm3_h1_h2_h3'):
        env = {n: os.environ[n] for n in ('SYSTEMROOT', 'WINDIR', 'PATH') if n in os.environ}
        env.update({'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'NO_ALBUMENTATIONS_UPDATE': '1',
                    'PYTHONDONTWRITEBYTECODE': '1', 'STUDENT_TEST_OCR_DEVICE': 'cpu', 'OMP_NUM_THREADS': '2',
                    'MKL_NUM_THREADS': '2', 'HF_HOME': str(out / 'offline_hf_cache'), 'TORCH_HOME': str(out / 'offline_torch_cache')})
        started = time.perf_counter()
        try:
            completed = subprocess.run([str(RUNTIME / '.venv-unimernet/Scripts/python.exe'), '-B',
                                       str(Path(__file__)), 'worker', '--output', str(out), '--engine', engine],
                                      cwd=out, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace',
                                      timeout=600, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            (out / f'local_{engine}_stdout.txt').write_text(completed.stdout, encoding='utf-8')
            (out / f'local_{engine}_stderr.txt').write_text(completed.stderr, encoding='utf-8')
            state = 'succeeded' if completed.returncode == 0 else 'failed'
            print(completed.stdout, end='', flush=True)
        except subprocess.TimeoutExpired:
            state = 'timeout'
        results.append({'engine': engine, 'state': state, 'wallSecondsIncludingStartupAndHashes': time.perf_counter() - started})
        print(json.dumps(results[-1]), flush=True)
    write_new(out / 'LOCAL_EXECUTION.json', {'createdAt': now(), 'results': results, 'providerCallCount': 0})


def percentile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    index = (len(values) - 1) * fraction
    lo, hi = int(index), min(len(values) - 1, int(index) + 1)
    return values[lo] + (values[hi] - values[lo]) * (index - lo)


def result_metrics(truth, rows):
    by_id = {p['sampleId']: p for p in rows}
    if len(by_id) != len(rows):
        raise ValueError('duplicate prediction ids')
    measured = []
    for target in truth:
        prediction = by_id.get(target['sampleId'], {})
        text = prediction.get('text', '')
        valid = prediction.get('state') == 'succeeded' and prediction.get('terminated') is True
        numeric = False
        if valid:
            try:
                numeric = answer_values_equivalent(text, target['label'])
            except Exception:
                pass
        exact = bool(valid and canonicalize_answer_text(text) and
                     canonicalize_answer_text(text) == canonicalize_answer_text(target['label']))
        measured.append({'sampleId': target['sampleId'], 'grade': target['grade'], 'kind': target['kind'],
                         'writerHash': target['writerHash'], 'target': target['label'], 'predicted': text,
                         'numericCorrect': bool(numeric), 'textExact': exact, 'generationFailed': not valid,
                         'state': prediction.get('state', 'not_run'), 'seconds': prediction.get('seconds')})
    times = [p['seconds'] for p in measured if p['seconds'] is not None]
    summary = {'denominator': len(truth), 'numericCorrect': sum(p['numericCorrect'] for p in measured),
               'textExact': sum(p['textExact'] for p in measured), 'generationFailures': sum(p['generationFailed'] for p in measured),
               'meanSeconds': statistics.mean(times) if times else None, 'p50Seconds': percentile(times, .5),
               'p90Seconds': percentile(times, .9), 'timedRows': len(times),
               'succeeded': sum(p['state'] == 'succeeded' for p in measured),
               'validOutputs': sum(not p['generationFailed'] for p in measured),
               'notRun': sum(p['state'] == 'not_run' for p in measured)}
    summary['numericFailures'] = len(truth) - summary['numericCorrect']
    for field in ('grade', 'kind', 'writerHash'):
        summary['by_' + field] = {}
        for value in sorted({p[field] for p in measured}):
            subset = [p for p in measured if p[field] == value]
            summary['by_' + field][value] = {'denominator': len(subset), 'numericCorrect': sum(p['numericCorrect'] for p in subset),
                                            'textExact': sum(p['textExact'] for p in subset)}
    return summary, measured


def report(out):
    validated_inputs(out)
    manifest = read(out / 'RUN_MANIFEST.json')
    if sha(out / 'TRUTH_EVALUATOR_ONLY.json') != manifest['truthSha256']:
        raise ValueError('frozen truth changed')
    truth = read(out / 'TRUTH_EVALUATOR_ONLY.json')
    apis = jsonl(out / 'api_predictions.jsonl') if (out / 'api_predictions.jsonl').exists() else []
    ledger = jsonl(out / 'API_CALL_LEDGER.jsonl') if (out / 'API_CALL_LEDGER.jsonl').exists() else []
    local_rows = [row for p in sorted(out.glob('local_*_predictions.jsonl')) for row in jsonl(p)]
    summaries, details = {}, {}
    for model in ('local', *MODELS):
        rows = local_rows if model == 'local' else [p for p in apis if p['model'] == model]
        summaries[model], details[model] = result_metrics(truth, rows)
        if model == 'local':
            summaries[model]['externalApiCostUsd'] = 0.0
            summaries[model]['electricityAndHardwareCostMeasured'] = False
            continue
        rate_in, rate_cached, rate_out = RATES[model]
        reported_usage = [p['usage'] for p in rows if isinstance(p.get('usage'), dict)]
        total_in = sum(p.get('input_tokens', 0) for p in reported_usage)
        total_out = sum(p.get('output_tokens', 0) for p in reported_usage)
        cached = sum((p.get('input_tokens_details') or {}).get('cached_tokens', 0) for p in reported_usage)
        summaries[model].update({'attemptedCalls': sum(p['model'] == model for p in ledger),
                                'inputTokens': total_in, 'cachedInputTokens': cached, 'outputTokens': total_out,
                                'usageRows': len(reported_usage), 'rowsWithoutUsage': len(rows) - len(reported_usage),
                                'usageBasedStandardEstimatedUsd': ((total_in - cached) * rate_in + cached * rate_cached + total_out * rate_out) / 1e6,
                                'billingVerified': False})
    if any(summaries[m]['attemptedCalls'] > 40 for m in MODELS):
        raise ValueError('provider budget violation')
    artifacts = {p.name: sha(p) for p in out.iterdir() if p.is_file() and p.name not in ('REPORT.json', 'REPORT.txt', 'VERIFY.json')}
    result = {'schema': 'bounded_ocr_comparison_report_v1', 'createdAt': now(), 'summaries': summaries, 'rows': details,
              'providerCallCount': len(ledger), 'deploymentReady': False, 'operatingChanges': False,
              'frozenInputVerified': True, 'fixedDenominator': 40, 'artifactHashes': artifacts, 'limits': manifest['limits'],
              'timingScope': 'crop-to-text; local model loading separate; API includes network, excludes crop generation and grading/storage',
              'costScope': 'reported tokens times official standard rates; not a billing invoice; failed calls without usage unknown; local hardware/electricity not measured',
              'safeAutoGradeEnabled': False, 'unsafeSafeAutoGradeEmitted': 0, 'answerKeysSentToProvider': 0,
              'filePathsSentToProvider': 0}
    write_new(out / 'REPORT.json', result)
    lines = ['OCR 비교 결과 · 2026-10-30', '', '고정 표본: 기존 AI Hub validation 40 crop. 실제 카메라/운영 GO 검증 아님.', '']
    for model, s in summaries.items():
        lines.append(f'{model}: 숫자값 동치 {s["numericCorrect"]}/40, 문자열 일치 {s["textExact"]}/40, 생성실패 {s["generationFailures"]}/40')
        lines.append(f'  처리시간 평균/중앙값/p90: {s["meanSeconds"]}, {s["p50Seconds"]}, {s["p90Seconds"]} 초')
        if model != 'local':
            lines.append(f'  호출 {s["attemptedCalls"]}/40, 보고된 토큰 기준 표준요금 추정 ${s["usageBasedStandardEstimatedUsd"]:.8f}, usage 없는 응답 {s["rowsWithoutUsage"]}개')
        else:
            lines.append('  외부 API 비용 $0. 전력/하드웨어 비용은 측정하지 않음.')
    lines.extend(['', '한계:', *['- ' + limit for limit in manifest['limits']], '', result['timingScope'], result['costScope']])
    with (out / 'REPORT.txt').open('x', encoding='utf-8') as stream:
        stream.write('\n'.join(lines) + '\n')
    print(json.dumps({'report': str(out / 'REPORT.json'), 'summaries': summaries, 'providerCallCount': len(ledger)}, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('prepare', 'api', 'local', 'worker', 'report'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--key-file', type=Path, default=LAB / 'OPENAI_API_KEY_INPUT.txt')
    parser.add_argument('--engine', choices=('choice_digit', 'm3_h1', 'm3_h1_h2_h3'))
    args = parser.parse_args()
    if args.mode == 'prepare':
        prepare(args.output)
    elif args.mode == 'api':
        api(args.output, args.key_file)
    elif args.mode == 'local':
        local(args.output)
    elif args.mode == 'worker':
        worker(args.output, args.engine)
    else:
        report(args.output)


if __name__ == '__main__':
    main()
