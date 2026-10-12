# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_evidence_prearrival_contract_gate.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from ocr_provider_free_extended_gate_common import read_json_object
from ocr_training_pack_evidence_prearrival_contract_model import (
    PrearrivalInputs,
    prearrival_contract,
    require_prearrival_contract,
)
from ocr_training_pack_evidence_prearrival_contract_output import markdown

LAB: Final[Path] = Path(__file__).resolve().parent
CHECKLIST_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_operator_checklist.json"
DROPBOX_JSON: Final[Path] = LAB / "ocr_training_pack_evidence_dropbox_spec.json"
INTAKE_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_intake_replay.json"
NEXT_ACTION_JSON: Final[Path] = LAB / "ocr_operator_next_action_summary.json"
EVIDENCE_DIR: Final[Path] = LAB / "training_pack_recognized_evidence"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_evidence_prearrival_contract_gate.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_evidence_prearrival_contract_gate.md"


def main() -> int:
    output = prearrival_contract(
        PrearrivalInputs(
            checklist=read_json_object(CHECKLIST_JSON),
            dropbox=read_json_object(DROPBOX_JSON),
            intake=read_json_object(INTAKE_JSON),
            next_action=read_json_object(NEXT_ACTION_JSON),
            evidence_file_names=evidence_file_names(),
        ),
    )
    require_prearrival_contract(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def evidence_file_names() -> tuple[str, ...]:
    return tuple(path.name for path in sorted(EVIDENCE_DIR.glob("*.json"))) if EVIDENCE_DIR.exists() else ()


if __name__ == "__main__":
    raise SystemExit(main())
