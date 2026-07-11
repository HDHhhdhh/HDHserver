# /// script
# requires-python = ">=3.11"
# dependencies = ["flask"]
# ///
#
# --- How to run ---
# python scripts\verify_submit_test_assignment_round_matching.py

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Final

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT: Final[Path] = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from routes.api_tests import _matching_submitted_assignment_labels  # noqa: E402


class AssignmentRoundMatchingVerificationError(Exception):
    pass


def assert_round_specific_assignment_matching() -> dict[str, object]:
    shared_source = "training_pack_shared_source"
    round_1_label = "트레이닝팩 / 미적분1 / 트팩 / 1회차 / 미적분1"
    round_2_label = "트레이닝팩 / 미적분1 / 트팩 / 2회차 / 미적분1"
    tests = {
        round_1_label: {"status": "assigned", "testId": "tp_mijeok1_r1", "sourceId": shared_source},
        round_2_label: {"status": "assigned", "testId": "tp_mijeok1_r2", "sourceId": shared_source},
    }
    meta_snapshot = {
        "type": "TRAINING_PACK",
        "curriculum": "미적분1",
        "difficulty": "트팩",
        "round": "1",
        "test_name": "미적분1",
        "source_id": shared_source,
    }
    record = {
        "testId": "tp_mijeok1_r1",
        "sourceId": shared_source,
        "name": "미적분1",
    }
    matched = _matching_submitted_assignment_labels(tests, record, meta_snapshot)
    if matched != [round_1_label]:
        raise AssignmentRoundMatchingVerificationError(f"round 1 matched wrong labels: {matched}")

    source_only_tests = {
        "트레이닝팩 / 공수2 / 트팩 / 1회차 / 공수2": {
            "status": "assigned",
            "sourceId": "gongsu2_shared_source",
        },
    }
    source_only_record = {
        "sourceId": "gongsu2_shared_source",
        "name": "공수2",
    }
    source_only_meta = {
        "type": "TRAINING_PACK",
        "curriculum": "공수2",
        "difficulty": "트팩",
        "round": "1",
        "test_name": "공수2",
        "source_id": "gongsu2_shared_source",
    }
    source_only_matched = _matching_submitted_assignment_labels(
        source_only_tests,
        source_only_record,
        source_only_meta,
    )
    if source_only_matched != ["트레이닝팩 / 공수2 / 트팩 / 1회차 / 공수2"]:
        raise AssignmentRoundMatchingVerificationError(
            f"source-only fallback matched wrong labels: {source_only_matched}"
        )

    return {
        "roundSpecificMatch": matched,
        "sourceOnlyFallback": source_only_matched,
        "wrongRoundMatched": False,
    }


def main() -> int:
    result = assert_round_specific_assignment_matching()
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
