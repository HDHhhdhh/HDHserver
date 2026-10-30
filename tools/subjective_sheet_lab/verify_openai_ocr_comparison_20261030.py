"""Offline contract checks only; fixture model outputs are not OCR accuracy evidence."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import sys
from unittest.mock import patch
import urllib.error

LAB = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('ocr_comparison', LAB / 'compare_openai_ocr_20261030.py')
comparison = importlib.util.module_from_spec(spec)
spec.loader.exec_module(comparison)


class FakeResponse:
    headers = {'x-request-id': 'offline-fixture'}
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return json.dumps({'id': 'offline-fixture', 'model': 'fixture', 'status': 'completed', 'service_tier': 'default',
                           'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(
                               {'recognized': '1', 'uncertain': False, 'unreadable': False})}]}],
                           'usage': {'input_tokens': 100, 'output_tokens': 10,
                                     'input_tokens_details': {'cached_tokens': 0}}}).encode()


class FakeOpener:
    def __init__(self, fail=False):
        self.requests = []
        self.fail = fail
    def open(self, request, timeout):
        self.requests.append(request)
        if self.fail:
            raise urllib.error.HTTPError(request.full_url, 401, 'fixture', {},
                                         io.BytesIO(b'{"error":{"type":"invalid_request_error","code":"invalid_api_key"}}'))
        return FakeResponse()


class Checks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='comparison_contract_', dir=LAB)
        self.root = Path(self.temp.name).resolve()
        assert self.root.is_relative_to(LAB.resolve())
        self.key_path = self.root / 'fixture.env'
        self.key_path.write_text('OPENAI_API_KEY=sk-offline-fixture-not-a-real-secret-000000000000\n', encoding='utf-8')
        image = self.root / 'fixture.png'
        image.write_bytes(b'offline-fixture-not-an-image-or-an-api-call')
        inputs = [{'sampleId': f'S{i:03d}', 'imagePath': str(image), 'imageSha256': comparison.sha(image),
                   'route': 'choice_digit'} for i in range(1, 41)]
        comparison.write_new(self.root / 'MODEL_INPUTS.json', inputs)
        self.truth = [{'sampleId': f'S{i:03d}', 'grade': 'M_G3', 'kind': 'choice_digit', 'writerHash': 'fixture', 'label': '1'}
                      for i in range(1, 41)]
        comparison.write_new(self.root / 'TRUTH_EVALUATOR_ONLY.json', self.truth)
        comparison.write_new(self.root / 'RUN_MANIFEST.json', {
            'inputManifestSha256': comparison.sha(self.root / 'MODEL_INPUTS.json'),
            'truthSha256': comparison.sha(self.root / 'TRUTH_EVALUATOR_ONLY.json'), 'limits': ['offline contract fixture only']})
    def tearDown(self):
        self.temp.cleanup()

    def test_40_calls_per_model_no_retries_key_not_in_artifacts(self):
        opener = FakeOpener()
        with patch.object(comparison.urllib.request, 'build_opener', return_value=opener), contextlib.redirect_stdout(io.StringIO()):
            comparison.api(self.root, self.key_path)
        ledger = comparison.jsonl(self.root / 'API_CALL_LEDGER.jsonl')
        self.assertEqual(len(opener.requests), 80)
        self.assertEqual(len(ledger), 80)
        self.assertTrue(all(sum(r['model'] == m for r in ledger) == 40 for m in comparison.MODELS))
        for request in opener.requests:
            body = json.loads(request.data)
            self.assertEqual(request.full_url, 'https://api.openai.com/v1/responses')
            self.assertEqual(body['reasoning'], {'effort': 'none'})
            self.assertIs(body['store'], False)
            self.assertEqual(body['service_tier'], 'default')
            self.assertEqual(len(body['input'][0]['content']), 2)
            self.assertEqual(body['input'][0]['content'][0]['text'], comparison.PROMPT)
            self.assertNotIn('label', body)
        for name in ('API_CALL_LEDGER.jsonl', 'api_predictions.jsonl', 'API_EXECUTION.json'):
            self.assertNotIn('sk-offline-fixture', (self.root / name).read_text(encoding='utf-8'))
        with self.assertRaises(ValueError):
            comparison.api(self.root, self.key_path)

    def test_auth_error_stops_each_model_after_one_attempt(self):
        opener = FakeOpener(fail=True)
        with patch.object(comparison.urllib.request, 'build_opener', return_value=opener), contextlib.redirect_stdout(io.StringIO()):
            comparison.api(self.root, self.key_path)
        self.assertEqual(len(opener.requests), 2)
        self.assertEqual(len(comparison.jsonl(self.root / 'API_CALL_LEDGER.jsonl')), 2)

    def test_generation_failure_and_missing_rows_stay_in_fixed_denominator(self):
        rows = [{'sampleId': 'S001', 'state': 'succeeded', 'terminated': True, 'text': '1', 'seconds': 1.0},
                {'sampleId': 'S002', 'state': 'succeeded', 'terminated': False, 'text': '1', 'seconds': 2.0}]
        summary, measured = comparison.result_metrics(self.truth, rows)
        self.assertEqual(summary['denominator'], 40)
        self.assertEqual(summary['numericCorrect'], 1)
        self.assertEqual(summary['generationFailures'], 39)
        self.assertEqual(summary['notRun'], 38)
        self.assertFalse(measured[1]['numericCorrect'])

    def test_spaced_digits_are_not_merged(self):
        truth = [{'sampleId': 'S001', 'grade': 'H_G1', 'kind': 'number', 'writerHash': 'fixture', 'label': '23'}]
        summary, _ = comparison.result_metrics(truth, [{'sampleId': 'S001', 'state': 'succeeded',
                             'terminated': True, 'text': '2 3', 'seconds': 0.1}])
        self.assertEqual(summary['numericCorrect'], 0)
        self.assertEqual(summary['textExact'], 0)

    def test_fraction_numeric_equivalence_is_not_raw_text_equality(self):
        self.assertTrue(comparison.answer_values_equivalent('1/2', r'\frac{1}{2}'))
        self.assertEqual(comparison.kind('x+1'), None)
        self.assertEqual(comparison.kind(r'\frac{1}{2}'), 'fraction')
        self.assertEqual(comparison.kind(r'2\sqrt{3}'), 'root')

    def test_changed_input_rejected_before_http(self):
        inputs = comparison.read(self.root / 'MODEL_INPUTS.json')
        Path(inputs[0]['imagePath']).write_bytes(b'changed')
        with self.assertRaises(ValueError):
            comparison.validated_inputs(self.root)

    def test_redirect_refused(self):
        with self.assertRaises(RuntimeError):
            comparison.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.com')


def verify_actual_run():
    root = LAB / 'comparison_20261030_01'
    initial = comparison.read(root / 'VERIFY.json')
    assert initial['allPassed'] is True
    for name, expected in initial['artifactSha256'].items():
        assert comparison.sha(root / name) == expected, 'original result artifact changed'
    finding = comparison.read(root / 'ORIENTATION_FINDING.json')
    assert finding['affectedFrozenSamples'] == len(finding['records']) == 11
    assert finding['providerCallCount'] == 0 and finding['newOcrInferenceExecuted'] is False
    for row in finding['records']:
        assert row['sourceExifOrientation'] == 6
        assert row['rawSize'] == list(reversed(row['uprightSize']))
        assert comparison.sha(row['diagnosticCropPath']) == row['diagnosticCropSha256']
    comparison.validated_inputs(root)
    ledger = comparison.jsonl(root / 'API_CALL_LEDGER.jsonl')
    assert len(ledger) == 80
    assert all(sum(r['model'] == model for r in ledger) == 40 for model in comparison.MODELS)
    inventory = {}
    for path in root.rglob('*'):
        if path.is_file():
            assert not path.is_symlink() and path.resolve().is_relative_to(root.resolve())
            inventory[path.relative_to(root).as_posix()] = {'bytes': path.stat().st_size, 'sha256': comparison.sha(path)}
    result = {'allPassed': True, 'initialArtifactHashesStillMatch': True,
              'currentFrozenImagesStillMatch': True, 'orientationDiagnosticCount': 11,
              'actualCalls': {model: 40 for model in comparison.MODELS}, 'callsMadeByThisVerifier': 0,
              'diagnosticCropsNotUsedForOcr': True, 'existingDatasetNotReplaced': True,
              'humanSummary': 'RESULTS_KO.txt', 'rawMetrics': 'REPORT.json',
              'sourceQuality': 'ORIENTATION_FINDING.json', 'filesBeforeThisReceipt': inventory}
    comparison.write_new(root / 'VERIFY_FINAL.json', result)
    print(json.dumps({'allPassed': True, 'filesVerified': len(inventory), 'providerCallsInVerifier': 0}))


if __name__ == '__main__':
    if sys.argv[1:] == ['--actual-run']:
        verify_actual_run()
    else:
        unittest.main()
