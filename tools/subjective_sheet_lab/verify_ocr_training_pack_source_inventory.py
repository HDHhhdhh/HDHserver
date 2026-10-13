# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_source_inventory.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from ocr_training_pack_source_inventory_model import markdown, training_pack_inventory


ROUTE_UPLOADS: Final[Path] = Path("C:/server-ocr/phase2c_route_uploads")
REPORT_JSON: Final[Path] = Path(__file__).with_name("ocr_training_pack_source_inventory.json")
REPORT_MD: Final[Path] = Path(__file__).with_name("ocr_training_pack_source_inventory.md")


def main() -> int:
    output = training_pack_inventory(ROUTE_UPLOADS)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
