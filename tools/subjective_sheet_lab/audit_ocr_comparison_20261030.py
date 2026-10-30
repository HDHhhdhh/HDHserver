"""Read-only validation of source data/results; emits new review artifacts only."""
import base64
from collections import Counter
import hashlib
import json
from pathlib import Path
import random
import re
import sys

ROOT = Path('C:/server')
LAB = ROOT / 'tools/subjective_sheet_lab'
OUT = LAB / 'comparison_20261030_01'
DATA = Path('C:/server-ocr/datasets/aihub_education')
sys.path.insert(0, str(ROOT))
from scripts.import_aihub_education_formula_dataset import normalized_formula_boxes
from scripts.import_aihub_education_choice_dataset import crop_box, image_filename
from PIL import Image


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def lines(path):
    return [json.loads(x) for x in Path(path).read_text(encoding='utf-8-sig').splitlines() if x.strip()]


def write(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def trace_original_high2(targets):
    labels_root = DATA / 'extracted/H_G2/validation_labels'
    images_root = DATA / 'extracted/H_G2/validation_images'
    wanted = {t['sourceHash']: t for t in targets if t['grade'] == 'H_G2'}
    results = []
    for label_path in sorted(labels_root.rglob('*.json')):
        payload = read(label_path)
        relative = label_path.relative_to(labels_root).as_posix()
        boxes = normalized_formula_boxes(payload)
        random.Random(f'20260829:{relative}').shuffle(boxes)
        for position, box in enumerate(boxes):
            source_hash = hashlib.sha256(f'{relative}\n{box["id"]}\n{position}'.encode()).hexdigest()
            if source_hash not in wanted:
                continue
            target = wanted[source_hash]
            image_path = images_root / image_filename(payload)
            record = {'sampleId': target['sampleId'], 'labelPath': str(label_path), 'labelSha256': digest(label_path),
                      'sourceImagePath': str(image_path), 'originalEquation': box['equation'],
                      'annotationDimensions': [payload.get('Images', {}).get('width'), payload.get('Images', {}).get('height')],
                      'bbox': {k: box[k] for k in ('left', 'top', 'right', 'bottom')},
                      'labelEqualsFrozen': box['equation'] == target['label']}
            if image_path.is_file():
                with Image.open(image_path) as opened:
                    record.update({'actualDimensions': list(opened.size), 'exifOrientation': opened.getexif().get(274),
                                   'originalCropBounds': crop_box(box, width=opened.width, height=opened.height, padding_ratio=.08)})
                record['sourceImageSha256'] = digest(image_path)
            results.append(record)
    return results


def main():
    report = read(OUT / 'REPORT.json')
    manifest = read(OUT / 'RUN_MANIFEST.json')
    inputs = read(OUT / 'MODEL_INPUTS.json')
    targets = read(OUT / 'TRUTH_EVALUATOR_ONLY.json')
    by_id = {i['sampleId']: i for i in inputs}
    checks = {}
    for path, expected in manifest['sourceHashes'].items():
        assert digest(path) == expected, 'frozen source changed'
    checks['frozenSourceHashes'] = True
    assert digest(OUT / 'MODEL_INPUTS.json') == manifest['inputManifestSha256']
    assert digest(OUT / 'TRUTH_EVALUATOR_ONLY.json') == manifest['truthSha256']
    dataset = Path(manifest['dataset'])
    equations = (dataset / 'equations.txt').read_text(encoding='utf-8-sig').splitlines()
    provenance = lines(dataset / 'provenance.jsonl')
    converted = {grade: {r['sourceHash']: r for r in lines(DATA / 'formula_converted/validation' / grade / 'samples.jsonl')}
                 for grade in ('M_G3', 'H_G1', 'H_G2')}
    source_links = []
    for target in targets:
        index = target['index']
        record = provenance[index]
        assert record['index'] == index
        assert all(record[k] == target[k] for k in ('grade', 'writerHash', 'sourceHash'))
        assert equations[index].strip() == target['label']
        sample = by_id[target['sampleId']]
        assert digest(sample['imagePath']) == sample['imageSha256']
        source_record = converted[target['grade']][target['sourceHash']]
        assert source_record['equation'] == target['label']
        source_path = DATA / 'formula_converted/validation' / target['grade'] / source_record['image']
        assert digest(source_path) == sample['imageSha256']
        source_links.append({'sampleId': target['sampleId'], 'convertedSource': str(source_path),
                             'imageSha256': sample['imageSha256'], 'sourceHash': target['sourceHash']})
    checks['all40ProfileToConvertedImageAndLabelLinks'] = True
    assert len({i['imageSha256'] for i in inputs}) == 40
    ledger = lines(OUT / 'API_CALL_LEDGER.jsonl')
    predictions = lines(OUT / 'api_predictions.jsonl')
    costs = {}
    for model, rates in {'gpt-6-luna': (.10, .01, .125, .50), 'gpt-6.1-terra': (1., .05, 1.25, 5.)}.items():
        calls = [r for r in ledger if r['model'] == model]
        rows = [r for r in predictions if r['model'] == model]
        assert len(calls) == len(rows) == 40
        assert [r['ordinal'] for r in calls] == list(range(1, 41))
        assert {r['sampleId'] for r in rows} == set(by_id)
        assert len({r['requestId'] for r in rows}) == 40
        tokens = Counter()
        flags = Counter()
        for call, row in zip(calls, rows):
            sample = by_id[call['sampleId']]
            assert row['sampleId'] == call['sampleId']
            assert call['imageSha256'] == sample['imageSha256']
            body = {'model': model, 'input': [{'role': 'user', 'content': [
                        {'type': 'input_text', 'text': manifest['prompt']},
                        {'type': 'input_image', 'image_url': 'data:image/png;base64,' + base64.b64encode(Path(sample['imagePath']).read_bytes()).decode(), 'detail': 'high'}]}],
                    'reasoning': {'effort': 'none'}, 'text': {'format': manifest['responseFormat']},
                    'max_output_tokens': 256, 'store': False, 'service_tier': 'default'}
            assert hashlib.sha256(json.dumps(body).encode()).hexdigest() == call['requestSha256']
            response = read(OUT / f'{model}_{row["sampleId"]}_response.json')
            assert response['id'] == row['responseId'] and response['model'].startswith(model)
            assert response['status'] == 'completed' and response['service_tier'] == 'default'
            assert response['usage'] == row['usage']
            parsed = json.loads(row['outputText'])
            assert row['text'] == parsed['recognized']
            assert row['state'] == 'succeeded' and row['terminated'] is True
            usage = row['usage']
            tokens['input'] += usage['input_tokens']
            tokens['output'] += usage['output_tokens']
            tokens['cacheRead'] += usage['input_tokens_details']['cached_tokens']
            tokens['cacheWrite'] += usage['input_tokens_details']['cache_write_tokens']
            tokens['reasoning'] += usage['output_tokens_details']['reasoning_tokens']
            flags['uncertain'] += bool(row['uncertain'])
            flags['unreadable'] += bool(row['unreadable'])
        assert tokens['reasoning'] == 0
        ordinary = tokens['input'] - tokens['cacheRead'] - tokens['cacheWrite']
        assert ordinary >= 0
        price = (ordinary * rates[0] + tokens['cacheRead'] * rates[1] + tokens['cacheWrite'] * rates[2] + tokens['output'] * rates[3]) / 1e6
        assert abs(price - report['summaries'][model]['usageBasedStandardEstimatedUsd']) < 1e-12
        costs[model] = {'attempts': 40, 'successes': 40, 'tokens': dict(tokens), 'flags': dict(flags),
                        'standardEstimatedUsd': price, 'meanCropEstimatedUsd': price / 40,
                        'arithmetic20CropEstimatedUsd': price / 2, 'billingVerified': False}
    checks['bothModels40Calls80ResponsesNoRetries'] = True
    checks['reconstructedRequestsExcludeLabelsPathsAndSecrets'] = True
    checks['same40ImagesForBothApisAndLocal'] = True
    checks['noneReasoningObservedAndCacheAwareCostRecomputed'] = True
    local_rows = [r for p in OUT.glob('local_*_predictions.jsonl') for r in lines(p)]
    assert len(local_rows) == 40 and {r['sampleId'] for r in local_rows} == set(by_id)
    assert len({r['sampleId'] for r in local_rows}) == 40
    for r in local_rows:
        if r['engine'] != 'choice_digit':
            native = r['nativeResult']
            assert native['terminated'] is True and 0 < native['tokenCount'] < 64
    local_models = [read(p) for p in OUT.glob('local_*_metadata.json')]
    assert len(local_models) == 3
    for model in local_models:
        assert model['weightsOnly'] is True and model['externalNetworkAllowed'] is False
        assert digest(model['modelPath']) == model['modelSha256']
    checks['local40RowsCapsAnd3CurrentCheckpointHashes'] = True
    secret_pattern = re.compile(rb'sk-[A-Za-z0-9_-]{20,}')
    for p in OUT.rglob('*'):
        if p.is_file() and p.suffix in ('.json', '.jsonl', '.txt', '.yaml'):
            assert not secret_pattern.search(p.read_bytes()), 'secret-like artifact content refused'
    checks['noPlaintextKeysInGeneratedResults'] = True
    original_trace = trace_original_high2(targets)
    assert len(original_trace) == 14 and all(r['labelEqualsFrozen'] for r in original_trace)
    checks['all14High2OriginalAnnotationHashesRecovered'] = True
    write(OUT / 'SOURCE_TRACE.json', {'profileAndConvertedLinks': source_links, 'high2OriginalAnnotations': original_trace})
    suspected = ['S013', 'S015', 'S019', 'S022', 'S024', 'S027', 'S028', 'S029', 'S030', 'S031', 'S035']
    findings = {
        'qualityStatus': 'LABEL_AGREEMENT_ONLY_NOT_VALIDATED_OCR_ACCURACY',
        'scope': 'current 40-crop comparison; not all AI Hub data or all original annotations',
        'visuallyInspectedHigh2': 14, 'high2CropsUnableToConfirmAnnotatedFormula': suspected,
        'suspectCount': 11, 'reviewMethod': 'same-session visual inspection; not an independent human relabel',
        'examples': [{'sampleId': 'S031', 'label': r'\sqrt{16}', 'observation': 'crop shows vertical ruled lines and no readable square-root expression'},
                     {'sampleId': 'S019', 'label': r'-\sqrt{10}', 'observation': 'crop shows ruled lines; annotated negative square-root expression not visible'},
                     {'sampleId': 'S013', 'label': r'\frac{3}{16}', 'observation': 'crop shows partial strokes; annotated numerator and denominator not present as a complete fraction'}],
        'rootCause': 'upstream image/annotation/crop alignment remains under investigation; benchmark index and file-byte association verified',
        'original40DenominatorPreserved': True, 'labelsRewritten': False, 'badCasesExcludedFromHeadline': False,
        'correctedAccuracyClaimed': False, 'providerRankingClaimed': False,
        'mandela': {'fired': [{'pattern': 'Shared-pool bias', 'evidence': '4/40 samples have grade-scoped writer hashes present in training provenance',
                             'fix': 'new writer-disjoint, independently visually verified holdout after crop repair'}]},
    }
    write(OUT / 'DATA_QUALITY_REVIEW.json', findings)
    final = {'createdAt': __import__('datetime').datetime.now(__import__('datetime').timezone(__import__('datetime').timedelta(hours=9))).isoformat(),
             'qualityStatus': findings['qualityStatus'], 'rawMetricsReference': 'REPORT.json', 'costs': costs,
             'totalProviderCalls': 80, 'maximumCallsPerModel': 40, 'additionalCallsAfterBudget': 0,
             'totalStandardEstimatedUsd': sum(c['standardEstimatedUsd'] for c in costs.values()),
             'localModelLoadSeconds': {m['engine']: m['modelLoadSeconds'] for m in local_models},
             'sourceTraceReference': 'SOURCE_TRACE.json', 'dataQualityReference': 'DATA_QUALITY_REVIEW.json',
             'verificationChecks': checks, 'deploymentReady': False, 'productionChanges': False,
             'independentSubagentReview': False, 'newTrainingOrPackageInstallation': False,
             'localStartupNote': 'initial restricted Windows environment failed before formula inference; retry only corrected process-local user/cache variables; original failure logs retained',
             'ssotizeAuditOnly': {'actualCalls': 'API_CALL_LEDGER.jsonl', 'frozenSources': 'RUN_MANIFEST.json',
                                 'rawLabelAgreementAndTime': 'REPORT.json', 'finalInterpretation': 'FINAL_REVIEW.json',
                                 'existingProjectDocumentsConsolidated': False},
             'nextStep': 'audit and repair upstream source/crop alignment into a new dataset; independently verify labels; obtain a new API budget before retesting; do not change operating OCR model from these scores'}
    write(OUT / 'FINAL_REVIEW.json', final)
    output = ['OCR 비교 검토 결과 · 2026-10-30', '',
              '결론: 실제 3개 모델 실행은 완료. 기존 crop-라벨 정합성 문제가 있어 정확도 순위를 확정할 수 없음.',
              '아래 수치는 고정 40개에 대한 기존 라벨 일치율이다. 원본/라벨/분모는 바꾸지 않았다.', '']
    for model, s in report['summaries'].items():
        output.append(f'{model}: 숫자값 동치 {s["numericCorrect"]}/40 ({s["numericCorrect"]*2.5:.1f}%), 정규화 문자열 {s["textExact"]}/40; 평균 {s["meanSeconds"]:.3f}초/crop, p90 {s["p90Seconds"]:.3f}초/crop.')
        if model in costs:
            output.append(f'  API {costs[model]["attempts"]}/40회, 표준 단가×실제 usage 추정 ${costs[model]["standardEstimatedUsd"]:.7f}. reasoning 토큰 0. 청구서 확인 아님.')
    output += ['', '데이터 품질:', '고2 14개를 육안 점검한 결과, 분수/루트 11개 crop에서 해당 라벨 수식을 확인하기 어렵다.',
               '예: S031 라벨 sqrt(16), 실제 crop은 세로줄 중심. S019 라벨 -sqrt(10), 실제 crop도 세로줄 중심.',
               '프로필 index→원본 converted 이미지/라벨 연결과 고2 원본 annotation 14개는 별도로 추적했다.',
               '상위 원본 image/annotation/crop 불일치 원인은 아직 확정하지 않았다. 모델의 오인식으로 단정하지 않는다.',
               '11개를 사후 제외해 개선된 정확도라고 발표하지 않았다. 기존 결과/예측/원본을 보존했다.', '',
               '속도 범위: crop→문자열. 로컬은 CPU 2 threads, 모델 초기 로딩 제외. API는 네트워크 왕복 포함.',
               '로컬 초기 모델 로딩(초): '+json.dumps(final['localModelLoadSeconds']),
               '전체 사진 촬영→채점 저장 또는 20개 동시 batch 처리 시간은 측정하지 않았다.',
               f'총 80회, 표준요금 usage 기반 합계 추정 ${final["totalStandardEstimatedUsd"]:.7f}. 실제 청구/크레딧 적용은 미확인.',
               '공식 단가: https://developers.openai.com/api/docs/models/gpt-6-luna ; https://developers.openai.com/api/docs/models/gpt-6.1-terra', '',
               '제약: 공개 개발 validation, 작성자 hash 7개, 4개 표본의 작성자 hash가 학습과 겹침. 고3 지원 숫자 표본 0개.',
               '정답키와 로컬 경로는 provider 입력에 포함하지 않았다. 키를 로그에 남기지 않았다.',
               '초기 로컬 수식 실행 실패는 별도 보존했고 실행 환경 변수만 보완해 재시도에 성공했다.',
               '운영 모델/설정/DB/UI/서버를 변경하지 않았고 설치/학습/추가 API 호출도 하지 않았다.',
               'sip/factchk: 단가·응답 usage·캐시·추론 토큰·체크포인트 SHA·고정 분모·호출 수를 재검증했다.',
               'mandela: 공유 작성자 pool 편향을 명시했다. ssotize는 근거 소유자만 읽기 전용으로 점검했으며 기존 문서를 통합하지 않았다.',
               '독립 하위 에이전트 검토는 수행하지 않았다.', '', '다음 단계: '+final['nextStep']]
    with (OUT / 'FINAL_REVIEW.txt').open('x', encoding='utf-8') as stream:
        stream.write('\n'.join(output) + '\n')
    write(OUT / 'VERIFY.json', {'checks': checks, 'allPassed': all(checks.values()), 'providerCallsInVerifier': 0,
                              'artifactSha256': {p.name: digest(p) for p in OUT.iterdir() if p.is_file() and p.name != 'VERIFY.json'}})
    print(json.dumps({'allPassed': all(checks.values()), 'checks': checks, 'qualityStatus': findings['qualityStatus'],
                      'totalStandardEstimatedUsd': final['totalStandardEstimatedUsd'], 'costs': costs,
                      'traceSampleCount': len(original_trace)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
