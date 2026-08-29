from __future__ import annotations

import tempfile
from pathlib import Path

import fitz

from core.student_test_solution_crop import (
    TABLE_BOTTOM,
    TABLE_LEFT,
    TABLE_RIGHT,
    TABLE_TOP,
    UnitSolutionCropProvider,
)


def _fixture_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True)
    with fitz.open() as document:
        page = document.new_page(width=595, height=842)
        cell_width = (TABLE_RIGHT - TABLE_LEFT) * page.rect.width / 4
        cell_height = (TABLE_BOTTOM - TABLE_TOP) * page.rect.height / 5
        for number in range(1, 21):
            column = (number - 1) % 4
            row = (number - 1) // 4
            point = fitz.Point(
                page.rect.width * TABLE_LEFT + column * cell_width + 4,
                page.rect.height * TABLE_TOP + row * cell_height + cell_height * 0.68,
            )
            page.insert_text(point, f"{number:02d} A{number}", fontsize=7)
        document.save(path)


def run() -> dict:
    assertions = 0
    with tempfile.TemporaryDirectory(prefix="student-test-solution-crop-") as temp_dir:
        root = Path(temp_dir)
        pdf_path = root / "unit-source-1" / "1.pdf"
        _fixture_pdf(pdf_path)
        provider = UnitSolutionCropProvider(root)
        test = {"sourceId": "unit-source-1"}

        assert provider.available(test, "1") is True
        first = provider.render(test, "1", 1)
        last = provider.render(test, 1, 20)
        assert first is not None and first.startswith(b"\x89PNG\r\n\x1a\n")
        assert last is not None and last.startswith(b"\x89PNG\r\n\x1a\n")
        assert first != last
        assertions += 4

        assert provider.available({"sourceId": "../escape"}, 1) is False
        assert provider.render(test, 1, 0) is None
        assert provider.render({"sourceId": "missing"}, 1, 1) is None
        assertions += 3

    return {"name": "student-test-solution-crop", "assertions": assertions, "passed": True}


if __name__ == "__main__":
    result = run()
    print(f"{result['name']} passed: {result['assertions']} assertions")
