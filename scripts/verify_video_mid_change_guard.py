from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from routes import api_basic


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _catalog() -> list[dict]:
    return [
        {
            "id": 1,
            "mid": "mid-a",
            "title": "기존 영상 A",
            "chapter": 1,
            "url": "https://v.kr.kollus.com/player?mid=mid-a&token=old",
        },
        {
            "id": 2,
            "mid": "mid-b",
            "title": "기존 영상 B",
            "chapter": 2,
            "url": "https://v.kr.kollus.com/player?mid=mid-b&token=old",
        },
    ]


def main() -> int:
    previous_path = api_basic.VID_PATH
    previous_mirror = os.environ.get("DATA_MIRROR_DIR")
    try:
        with tempfile.TemporaryDirectory(prefix="verify-video-mid-guard-") as tmp:
            root = Path(tmp)
            video_path = root / "videos.json"
            os.environ["DATA_MIRROR_DIR"] = str(root / "mirror")
            api_basic.VID_PATH = video_path
            _write_json(video_path, _catalog())

            app = Flask(__name__)
            app.register_blueprint(api_basic.bp_api_basic)
            client = app.test_client()

            same_mid = _catalog()
            same_mid[0]["title"] = "제목 수정 허용"
            same_mid[0]["url"] = "https://v.kr.kollus.com/player?mid=mid-a&token=new-signature"
            response = client.post("/api/videos", json=same_mid)
            assert response.status_code == 204, response.get_data(as_text=True)
            saved = _read_json(video_path)
            assert saved[0]["title"] == "제목 수정 허용"
            assert saved[0]["mid"] == "mid-a"
            assert "new-signature" in saved[0]["url"]

            before_block = _read_json(video_path)
            changed_mid = json.loads(json.dumps(before_block, ensure_ascii=False))
            changed_mid[0]["url"] = "https://v.kr.kollus.com/player?mid=mid-replacement"
            response = client.post("/api/videos", json=changed_mid)
            assert response.status_code == 409
            payload = response.get_json()
            assert payload["error"] == api_basic.VIDEO_CATALOG_IDENTITY_CHANGE_ERROR
            assert payload["removedIds"] == []
            assert payload["midChanges"] == [{"id": "1", "oldMid": "mid-a", "newMid": "mid-replacement"}]
            assert _read_json(video_path) == before_block, "blocked MID change wrote videos.json"

            response = client.post("/api/videos", json=before_block[1:])
            assert response.status_code == 409
            payload = response.get_json()
            assert payload["removedIds"] == ["1"]
            assert payload["midChanges"] == []
            assert _read_json(video_path) == before_block, "blocked deletion wrote videos.json"

            with_new_row = json.loads(json.dumps(before_block, ensure_ascii=False))
            with_new_row.append({
                "id": 3,
                "mid": "mid-c",
                "title": "새 영상",
                "chapter": 3,
                "url": "https://v.kr.kollus.com/player?mid=mid-c",
            })
            response = client.post("/api/videos", json=with_new_row)
            assert response.status_code == 204, response.get_data(as_text=True)
            assert [row["mid"] for row in _read_json(video_path)] == ["mid-a", "mid-b", "mid-c"]

            duplicate_id = json.loads(json.dumps(with_new_row, ensure_ascii=False))
            duplicate_id[2]["id"] = 2
            before_invalid = _read_json(video_path)
            response = client.post("/api/videos", json=duplicate_id)
            assert response.status_code == 400
            assert response.get_json()["error"] == "invalid_video_catalog"
            assert _read_json(video_path) == before_invalid, "invalid catalog wrote videos.json"
    finally:
        api_basic.VID_PATH = previous_path
        if previous_mirror is None:
            os.environ.pop("DATA_MIRROR_DIR", None)
        else:
            os.environ["DATA_MIRROR_DIR"] = previous_mirror

    print("video MID change guard checks passed: same-MID edit/new row allowed; change/delete blocked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())