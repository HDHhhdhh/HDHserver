from __future__ import annotations

import json
import hashlib
import os
import sys
import tempfile
from pathlib import Path

from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from routes import api_basic, api_videos


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    previous_path = api_videos.VID_PATH
    previous_mirror = os.environ.get("DATA_MIRROR_DIR")
    try:
        with tempfile.TemporaryDirectory(prefix="verify-video-mid-guard-") as tmp:
            root = Path(tmp)
            video_path = root / "videos.json"
            os.environ["DATA_MIRROR_DIR"] = str(root / "mirror")
            api_videos.VID_PATH = video_path
            _write_json(video_path, _catalog())

            app = Flask(__name__)
            app.register_blueprint(api_basic.bp_api_basic)
            app.register_blueprint(api_videos.bp_api_videos)
            client = app.test_client()

            video_rules = [rule for rule in app.url_map.iter_rules() if rule.rule == "/api/videos"]
            assert len(video_rules) == 1, video_rules
            assert video_rules[0].endpoint == "api_videos.api_videos"
            assert video_rules[0].methods == {"GET", "HEAD", "OPTIONS", "POST"}

            response = client.get("/api/videos")
            assert response.status_code == 200
            assert response.get_json() == _catalog()

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
            before_block_bytes = video_path.read_bytes()
            before_block_hash = _sha256(video_path)
            changed_mid = json.loads(json.dumps(before_block, ensure_ascii=False))
            changed_mid[0]["url"] = "https://v.kr.kollus.com/player?mid=mid-replacement"
            response = client.post("/api/videos", json=changed_mid)
            assert response.status_code == 409
            payload = response.get_json()
            assert payload["error"] == api_videos.VIDEO_CATALOG_IDENTITY_CHANGE_ERROR
            assert payload["removedIds"] == []
            assert payload["midChanges"] == [{"id": "1", "oldMid": "mid-a", "newMid": "mid-replacement"}]
            assert _read_json(video_path) == before_block, "blocked MID change wrote videos.json"
            assert video_path.read_bytes() == before_block_bytes
            assert _sha256(video_path) == before_block_hash

            response = client.post("/api/videos", json=before_block[1:])
            assert response.status_code == 409
            payload = response.get_json()
            assert payload["removedIds"] == ["1"]
            assert payload["midChanges"] == []
            assert _read_json(video_path) == before_block, "blocked deletion wrote videos.json"
            assert video_path.read_bytes() == before_block_bytes
            assert _sha256(video_path) == before_block_hash

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
            before_invalid_bytes = video_path.read_bytes()
            before_invalid_hash = _sha256(video_path)
            response = client.post("/api/videos", json=duplicate_id)
            assert response.status_code == 400
            assert response.get_json()["error"] == "invalid_video_catalog"
            assert _read_json(video_path) == before_invalid, "invalid catalog wrote videos.json"
            assert video_path.read_bytes() == before_invalid_bytes
            assert _sha256(video_path) == before_invalid_hash

            response = client.post("/api/videos", json={"not": "an array"})
            assert response.status_code == 400
            assert response.get_json()["error"] == "invalid_video_catalog"
            assert video_path.read_bytes() == before_invalid_bytes
            assert _sha256(video_path) == before_invalid_hash

            basic_source = (ROOT / "routes" / "api_basic.py").read_text(encoding="utf-8")
            videos_source = (ROOT / "routes" / "api_videos.py").read_text(encoding="utf-8")
            assert '"/api/videos"' not in basic_source
            assert '@bp_api_videos.route("/api/videos", methods=["GET", "POST"])' in videos_source
    finally:
        api_videos.VID_PATH = previous_path
        if previous_mirror is None:
            os.environ.pop("DATA_MIRROR_DIR", None)
        else:
            os.environ["DATA_MIRROR_DIR"] = previous_mirror

    print(
        "video catalog route checks passed: dedicated blueprint, GET/POST contract, "
        "same-MID edit/new row allowed, blocked writes byte-identical"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
