from __future__ import annotations

import importlib.util
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


SAFE_SOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,159}$")
QUESTION_COUNT = 20

# Official UNIT solutions use the same four-column, five-row answer summary on
# page one. Fractions keep this independent of PDF point size and render DPI.
TABLE_LEFT = 0.037
TABLE_TOP = 0.120
TABLE_RIGHT = 0.462
TABLE_BOTTOM = 0.248


@dataclass(frozen=True, slots=True)
class UnitSolutionCropProvider:
    pdf_root: Path
    zoom: float = 3.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "pdf_root", self.pdf_root.resolve())
        if not 1.0 <= self.zoom <= 6.0:
            raise ValueError("solution crop zoom is invalid")

    def _pdf_path(self, test: Mapping[str, object], round_no: object) -> Path | None:
        source_id = str(test.get("sourceId") or "").strip()
        if not SAFE_SOURCE_ID.fullmatch(source_id):
            return None
        try:
            round_value = int(str(round_no).strip())
        except (TypeError, ValueError):
            return None
        if not 1 <= round_value <= 3:
            return None
        candidate = (self.pdf_root / source_id / f"{round_value}.pdf").resolve()
        try:
            candidate.relative_to(self.pdf_root)
        except ValueError:
            return None
        return candidate if candidate.is_file() else None

    def available(self, test: Mapping[str, object], round_no: object) -> bool:
        return importlib.util.find_spec("fitz") is not None and self._pdf_path(test, round_no) is not None

    def render(self, test: Mapping[str, object], round_no: object, question_no: object) -> bytes | None:
        if isinstance(question_no, bool) or not isinstance(question_no, int) or not 1 <= question_no <= QUESTION_COUNT:
            return None
        pdf_path = self._pdf_path(test, round_no)
        if pdf_path is None:
            return None
        try:
            import fitz

            with fitz.open(pdf_path) as document:
                if document.page_count < 1:
                    return None
                page = document.load_page(0)
                page_rect = page.rect
                if page_rect.width <= 0 or page_rect.height <= page_rect.width:
                    return None
                column = (question_no - 1) % 4
                row = (question_no - 1) // 4
                cell_width = (TABLE_RIGHT - TABLE_LEFT) / 4
                cell_height = (TABLE_BOTTOM - TABLE_TOP) / 5
                clip = fitz.Rect(
                    page_rect.width * (TABLE_LEFT + column * cell_width),
                    page_rect.height * (TABLE_TOP + row * cell_height),
                    page_rect.width * (TABLE_LEFT + (column + 1) * cell_width),
                    page_rect.height * (TABLE_TOP + (row + 1) * cell_height),
                )
                pixmap = page.get_pixmap(matrix=fitz.Matrix(self.zoom, self.zoom), clip=clip, alpha=False)
                content = pixmap.tobytes("png")
                return content if content.startswith(b"\x89PNG\r\n\x1a\n") else None
        except Exception:
            # The official Drive link remains the administrator fallback when a
            # local cache is missing, corrupt, or unsupported by the renderer.
            return None


__all__ = ["QUESTION_COUNT", "UnitSolutionCropProvider"]
