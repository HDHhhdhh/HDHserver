"""Fetch pinned browser distributions; verify npm SHA-512 before writing assets."""
from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1] / "static" / "vendor"
PACKAGES = {
    "tom-select": ("2.6.2", "eiXIkk82XzzUTOVQDFpy+ZGejuqdTvMukyUyeZBQaKnqW42UoTiTZnrod/eX0rkqJEc4rZY9DZ3zdjV07i29wQ==", ["dist/js/tom-select.complete.min.js", "dist/css/tom-select.default.min.css", "LICENSE"]),
    "tabulator-tables": ("6.7.1", "6CMy17XdemQaIdg1BOqD5K6nzF2xoD47eRNiBYJBK+QrLWji7sgukyPjKXYrjRdWLwbGENdUsiAYJrNS3XeUfw==", ["dist/js/tabulator.min.js", "dist/css/tabulator.min.css", "LICENSE"]),
    "echarts": ("6.1.0", "q0yaFPggC9FUdsWH4blavRWFmxdrIodbkoKNAjJudAI6CA9gNPxHtV2RcZNEepZVlk4yvBYkOkbk6HIVpIyHZA==", ["dist/echarts.min.js", "LICENSE", "NOTICE"]),
}


def main():
    manifest = []
    for name, (version, integrity, members) in PACKAGES.items():
        url = f"https://registry.npmjs.org/{name}/-/{name}-{version}.tgz"
        with urllib.request.urlopen(url, timeout=60) as response:
            archive = response.read()
        actual = base64.b64encode(hashlib.sha512(archive).digest()).decode()
        if actual != integrity:
            raise ValueError(f"Integrity mismatch: {name}")
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as package:
            for member in members:
                data = package.extractfile("package/" + member).read()
                target = ROOT / name / version / Path(member).name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                manifest.append({"file": target.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(data).hexdigest(), "source": url, "integrity": "sha512-" + integrity})
        print(f"Verified {name}@{version}")
    (ROOT / "admin-toolkit-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
