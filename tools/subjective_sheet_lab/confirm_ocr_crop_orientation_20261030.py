"""Diagnostic EXIF normalization only; never replaces data or runs an OCR model."""
import hashlib
import json
from pathlib import Path
import sys
from PIL import Image, ImageOps

ROOT = Path('C:/server')
OUT = ROOT / 'tools/subjective_sheet_lab/comparison_20261030_01'
sys.path.insert(0, str(ROOT))
from scripts.import_aihub_education_choice_dataset import crop_box


def sha(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def main():
    trace = json.loads((OUT / 'SOURCE_TRACE.json').read_text(encoding='utf-8'))['high2OriginalAnnotations']
    quality = json.loads((OUT / 'DATA_QUALITY_REVIEW.json').read_text(encoding='utf-8'))
    suspects = set(quality['high2CropsUnableToConfirmAnnotatedFormula'])
    affected = [r for r in trace if r['sampleId'] in suspects]
    assert len(affected) == 11
    destination = OUT / 'orientation_diagnostics'
    destination.mkdir(exist_ok=False)
    records = []
    for r in affected:
        path = Path(r['sourceImagePath'])
        before_sha = sha(path)
        assert before_sha == r['sourceImageSha256']
        with Image.open(path) as opened:
            original_size = list(opened.size)
            orientation = opened.getexif().get(274)
            assert orientation == 6
            upright = ImageOps.exif_transpose(opened)
            assert list(upright.size) == r['annotationDimensions']
            bounds = crop_box(r['bbox'], width=upright.width, height=upright.height, padding_ratio=.08)
            diagnostic = ImageOps.autocontrast(ImageOps.grayscale(upright.crop(bounds))).convert('RGB')
            target = destination / (r['sampleId'] + '_orientation_normalized.png')
            diagnostic.save(target, format='PNG', optimize=True)
        assert sha(path) == before_sha
        records.append({'sampleId': r['sampleId'], 'label': r['originalEquation'], 'sourceImageSha256': before_sha,
                        'sourceExifOrientation': orientation, 'rawSize': original_size,
                        'uprightSize': r['annotationDimensions'], 'diagnosticCropPath': str(target),
                        'diagnosticCropSha256': sha(target), 'correctedBounds': list(bounds)})
    result = {'schema': 'ocr_crop_orientation_diagnostic_v1', 'affectedFrozenSamples': 11,
              'observedCause': 'conversion crops raw EXIF-orientation-6 pixels using upright annotation coordinates',
              'proof': 'all 11 have swapped raw dimensions; ImageOps.exif_transpose restores exact annotated dimensions',
              'importerPath': str(ROOT / 'scripts/import_aihub_education_formula_dataset.py'),
              'importerSha256': sha(ROOT / 'scripts/import_aihub_education_formula_dataset.py'),
              'importerObservation': 'Image.open(source) is cropped directly; no ImageOps.exif_transpose before crop',
              'originalDatasetModified': False, 'originalLabelsModified': False,
              'diagnosticCropsUsedForTraining': False, 'newOcrInferenceExecuted': False, 'providerCallCount': 0,
              'records': records}
    with (OUT / 'ORIENTATION_FINDING.json').open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'affectedSamples': 11, 'providerCallCount': 0, 'finding': str(OUT / 'ORIENTATION_FINDING.json')}))


if __name__ == '__main__':
    main()
