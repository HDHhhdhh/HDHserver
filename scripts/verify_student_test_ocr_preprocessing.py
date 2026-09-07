from __future__ import annotations

def run():
    import cv2
    import numpy as np
    from scripts.student_test_ocr_preprocessing import prepare_crop
    from scripts.benchmark_student_test_free_ocr import summary
    from scripts.benchmark_student_test_free_ocr import rescore
    from scripts.student_test_formula_inference import generation_completed

    image = np.full((160, 480, 3), 255, np.uint8)
    cv2.rectangle(image, (3, 3), (476, 156), (0, 0, 0), 2)
    # Literal central fraction/root geometry, independent of candidate helpers.
    cv2.line(image, (175, 78), (290, 78), (0, 0, 0), 3)
    cv2.line(image, (215, 38), (210, 65), (0, 0, 0), 3)
    cv2.putText(image, "2", (210, 125), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
    before = image.tobytes()
    result, meta = prepare_crop(cv2, np, image, None, "border_ink")
    assert image.tobytes() == before
    assert result.shape[1] < 200 and result.shape[0] < 150
    assert meta["contentBox"][0] > 150 and meta["removedInkPixels"] > 0
    assert int((result < 128).sum(axis=1).max()) >= 110  # fraction bar survived
    raw, _ = prepare_crop(cv2, np, image, None, "raw")
    assert np.array_equal(raw, image) and raw is not image
    root = np.full((160, 480, 3), 255, np.uint8)
    cv2.line(root, (190, 65), (205, 82), (0, 0, 0), 3)
    cv2.line(root, (205, 82), (225, 32), (0, 0, 0), 3)
    cv2.line(root, (225, 32), (270, 32), (0, 0, 0), 3)
    rooted, _ = prepare_crop(cv2, np, root, None, "border_ink")
    assert int((rooted < 128).sum()) > 350
    blank, blank_meta = prepare_crop(cv2, np, np.full_like(root, 255), None, "border_ink")
    assert blank_meta["blank"] and bool((blank == 255).all())
    try:
        prepare_crop(cv2, np, image, None, "unknown")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown candidate accepted")
    counted = summary([{"numericCorrect": False, "exactCorrect": False, "terminated": False, "kind": "number"},
                       {"numericCorrect": True, "exactCorrect": True, "terminated": True, "kind": "number"}])
    assert counted["evaluated"] == 2 and counted["numericAccuracy"] == .5 and counted["truncated"] == 1
    assert generation_completed(3, 64, True) and not generation_completed(64, 64, True)
    assert not generation_completed(3, 64, False)
    plan = {"models": [{"name": "test"}], "variants": ["raw"], "generation": {"maxNewTokens": 64}}
    rows = [{"model": "test", "variant": "raw", "case": "a", "questionNo": 1, "text": "4",
             "tokenCount": 3, "terminated": True, "numericCorrect": True, "exactCorrect": True}]
    assert rescore(rows, plan, {"a": {1: "3"}})[0]["numericCorrect"] is False
    try:
        rescore(rows + rows, plan, {"a": {1: "3"}})
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate persisted predictions accepted")
    return {"passed": True, "assertions": 13}


if __name__ == "__main__":
    print(run())
