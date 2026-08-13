"""Temp-only regression checks for file-manager path reference updates."""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile

from flask import Flask


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_file_reference_route_checks() -> None:
    import routes.api_fs as api_fs

    original = {
        "FILES_DIR": api_fs.FILES_DIR,
        "FILES_ROOT": api_fs.FILES_ROOT,
        "MAT_PATH": api_fs.MAT_PATH,
        "ASN_PATH": api_fs.ASN_PATH,
        "PAGE_FOLDERS_PATH": api_fs.PAGE_FOLDERS_PATH,
    }

    def write_json(path: pathlib.Path, value: object) -> None:
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def read_json(path: pathlib.Path):
        return json.loads(path.read_text(encoding="utf-8"))

    try:
        with tempfile.TemporaryDirectory(prefix="file-reference-route-") as tmpdir:
            root = pathlib.Path(tmpdir)
            files_dir = root / "files"
            files_dir.mkdir()
            mat_path = root / "materials.json"
            assign_path = root / "mat_assign.json"
            page_path = root / "page_folders.json"
            api_fs.FILES_DIR = files_dir
            api_fs.FILES_ROOT = files_dir.resolve()
            api_fs.MAT_PATH = mat_path
            api_fs.ASN_PATH = assign_path
            api_fs.PAGE_FOLDERS_PATH = page_path

            source_file = files_dir / "\uad50\uc7ac" / "\ub2e8\uc6d0" / "\ubb38\uc81c.pdf"
            source_file.parent.mkdir(parents=True)
            source_file.write_text("fixture", encoding="utf-8")
            write_json(mat_path, {"m1": {"url": "/files/\uad50\uc7ac/\ub2e8\uc6d0/\ubb38\uc81c.pdf", "title": "\ubb38\uc81c"}})
            write_json(
                assign_path,
                {
                    "s1": [
                        "m1",
                        "/files/\uad50\uc7ac/\ub2e8\uc6d0/\ubb38\uc81c.pdf",
                        "\uad50\uc7ac/\ub2e8\uc6d0/\ubb38\uc81c.pdf",
                        "DIR:\uad50\uc7ac",
                    ],
                },
            )
            write_json(page_path, {"materials": "\uad50\uc7ac/\ub2e8\uc6d0"})

            app = Flask("verify-file-reference-routes")
            app.register_blueprint(api_fs.bp_api_fs)
            client = app.test_client()

            response = client.post(
                "/api/fs/rename",
                json={"src": "\uad50\uc7ac", "new_name": "\uc218\ud559 \uad50\uc7ac"},
            )
            check(response.status_code == 200, "folder rename must accept a safe Korean name")
            check(
                (files_dir / "\uc218\ud559 \uad50\uc7ac" / "\ub2e8\uc6d0" / "\ubb38\uc81c.pdf").exists(),
                "folder rename must preserve nested files",
            )
            check(
                read_json(mat_path)["m1"]["url"] == "/files/\uc218\ud559 \uad50\uc7ac/\ub2e8\uc6d0/\ubb38\uc81c.pdf",
                "folder rename must rewrite descendant material URLs",
            )
            check(
                read_json(assign_path)["s1"]
                == [
                    "m1",
                    "/files/\uc218\ud559 \uad50\uc7ac/\ub2e8\uc6d0/\ubb38\uc81c.pdf",
                    "\uc218\ud559 \uad50\uc7ac/\ub2e8\uc6d0/\ubb38\uc81c.pdf",
                    "DIR:\uc218\ud559 \uad50\uc7ac",
                ],
                "folder rename must rewrite URL, relative, and directory assignment tokens",
            )
            check(
                read_json(page_path) == {"materials": "\uc218\ud559 \uad50\uc7ac/\ub2e8\uc6d0"},
                "folder rename must rewrite page-folder descendants",
            )

            response = client.post(
                "/api/fs/delete",
                json={"paths": ["\uc218\ud559 \uad50\uc7ac/\ub2e8\uc6d0"]},
            )
            check(response.status_code == 200, "nested folder delete must succeed")
            check(read_json(mat_path) == {}, "folder delete must remove descendant material metadata")
            check(
                read_json(assign_path)["s1"] == ["DIR:\uc218\ud559 \uad50\uc7ac"],
                "folder delete must remove descendant IDs and paths but preserve the parent directory token",
            )
            check(
                read_json(page_path) == {"materials": ""},
                "folder delete must clear a page-folder reference to the deleted subtree",
            )

            move_file = files_dir / "\uc790\ub8cc" / "\ud558\uc704" / "\uc774\ub3d9.pdf"
            move_file.parent.mkdir(parents=True)
            move_file.write_text("fixture", encoding="utf-8")
            write_json(mat_path, {"m2": {"url": "/files/\uc790\ub8cc/\ud558\uc704/\uc774\ub3d9.pdf"}})
            write_json(assign_path, {"s2": ["DIR:\uc790\ub8cc", "/files/\uc790\ub8cc/\ud558\uc704/\uc774\ub3d9.pdf"]})
            write_json(page_path, {"materials": "\uc790\ub8cc/\ud558\uc704"})

            response = client.post(
                "/api/fs/move",
                json={"paths": ["\uc790\ub8cc"], "dst": "\ubcf4\uad00"},
            )
            check(response.status_code == 200, "folder move must succeed")
            check(
                (files_dir / "\ubcf4\uad00" / "\uc790\ub8cc" / "\ud558\uc704" / "\uc774\ub3d9.pdf").exists()
                and read_json(mat_path)["m2"]["url"] == "/files/\ubcf4\uad00/\uc790\ub8cc/\ud558\uc704/\uc774\ub3d9.pdf"
                and read_json(assign_path)["s2"]
                == ["DIR:\ubcf4\uad00/\uc790\ub8cc", "/files/\ubcf4\uad00/\uc790\ub8cc/\ud558\uc704/\uc774\ub3d9.pdf"]
                and read_json(page_path) == {"materials": "\ubcf4\uad00/\uc790\ub8cc/\ud558\uc704"},
                "folder move must rewrite every descendant reference",
            )

            scalar_paths = client.post(
                "/api/fs/move",
                json={"paths": "\ubcf4\uad00/\uc790\ub8cc", "dst": "\ub2e4\ub978\uacf3"},
            )
            check(scalar_paths.status_code == 400, "folder move must reject a scalar paths payload")
    finally:
        for name, value in original.items():
            setattr(api_fs, name, value)


def main() -> int:
    run_file_reference_route_checks()
    print("file reference route checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
