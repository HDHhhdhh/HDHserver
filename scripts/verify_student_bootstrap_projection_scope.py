"""Pure requested-SID projection oracle; never imports app or runtime paths."""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from core.student_video_projection import (
    history_for_sid, build_latest_status_by_sid,
    build_auto_assignment_blocked_by_sid, blocked_mids_for_sid,
)

def verify():
    progress={
        "2026-05-01":{
            "007":{"m1":"done","m2":"skip","__unknown":{"keep":True}},
            "7":{"m3":"done"},
            "0007":{"m4":"done"},
            "other":{"unrelated":"done"},
        },
        "2026-05-02":{
            "007":{"m1":"none","__manualProgressMids":{"m1":"manual"}},
            "other":{"unrelated":"skip"},
        },
        "invalid-shape":["ignored"],
    }
    watch={"2026-05-02":{
        "7":{"m1":{"last":100,"dur":100,"completed":True}},
        "other":{"unrelated":{"last":100,"dur":100,"completed":True}},
    }}
    before=deepcopy((progress,watch))
    expected={
        "2026-05-01":{
            "007":{"m1":"done","m2":"skip","__unknown":{"keep":True}},
            "7":{"m3":"done"},
            "0007":{"m4":"done"},
        },
        "2026-05-02":{"007":{"m1":"none","__manualProgressMids":{"m1":"manual"}}},
    }
    scoped=history_for_sid(progress,"007")
    assert scoped==expected
    assert build_latest_status_by_sid(scoped)=={
        "007":{"m1":"none","m2":"skip"},"7":{"m3":"done"},"0007":{"m4":"done"}
    }
    blocked=build_auto_assignment_blocked_by_sid(scoped,history_for_sid(watch,"007"))
    assert blocked_mids_for_sid(blocked,"007")=={"m2","m3","m4"}
    assert blocked_mids_for_sid(build_auto_assignment_blocked_by_sid(progress,watch),"007")=={"m2","m3","m4"}
    assert history_for_sid({},"one")=={}
    assert history_for_sid(None,"one")=={}
    assert history_for_sid(progress,"absent")=={}
    assert (progress,watch)==before
    print("requested-SID projection checks passed: numeric/leading-zero aliases, manual reopen, unknown fields, unrelated-SID exclusion and input invariance")
if __name__=="__main__":
    verify()
