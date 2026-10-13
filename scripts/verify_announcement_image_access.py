from __future__ import annotations

import copy
import datetime as dt
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.announcement_image_access import (  # noqa: E402
    announcement_image_paths,
    normalize_announcement_image_path,
    student_can_access_announcement_image,
    student_can_access_announcement_image_from_store,
)
from core.storage import save_atomic  # noqa: E402


NOW = dt.datetime(2026, 8, 24, 12, 0, tzinfo=dt.timezone.utc)


def _announcement(
    announcement_id: str,
    image_name: str,
    *,
    targets: list[str] | None = None,
    created_at: str = "2026-08-24T00:00:00Z",
    expires_at: str = "2026-08-25T00:00:00Z",
    **extra,
) -> dict:
    return {
        "id": announcement_id,
        "kind": "announcement",
        "targetSids": targets if targets is not None else ["sid-a"],
        "createdAt": created_at,
        "expiresAt": expires_at,
        "images": [
            {
                "path": f"announcements/{image_name}",
                "url": f"/files/announcements/{image_name}",
            }
        ],
        **extra,
    }


def _verify_path_normalization() -> None:
    assert normalize_announcement_image_path(
        {"path": "announcements/valid.png"}
    ) == "announcements/valid.png"
    assert normalize_announcement_image_path(
        {
            "path": "announcements/wrong.png",
            "url": "/files/announcements/from-url.webp",
        }
    ) == "announcements/from-url.webp"
    assert normalize_announcement_image_path(
        {"path": "announcements\\windows.jpg"}
    ) == "announcements/windows.jpg"
    assert normalize_announcement_image_path("announcements/direct.gif") == (
        "announcements/direct.gif"
    )

    for invalid in (
        "",
        "answers/secret.png",
        "announcements/../answers/secret.png",
        "announcements/not-an-image.pdf",
        {"path": "announcements/../../secret.png"},
        {"url": "/files/answers/secret.png"},
        None,
    ):
        assert normalize_announcement_image_path(invalid) == ""


def _verify_image_membership_projection() -> None:
    fallback = {
        "images": [{"path": "answers/no.png"}],
        "image": {"path": "announcements/fallback.png"},
    }
    assert announcement_image_paths(fallback) == ("announcements/fallback.png",)

    assert announcement_image_paths(
        {
            "images": ["announcements/string-entry.png"],
            "image": {"path": "announcements/dict-fallback.png"},
        }
    ) == ("announcements/dict-fallback.png",)
    try:
        announcement_image_paths(
            {"images": [{"path": "announcements/bad-size.png", "size": "bad"}]}
        )
    except ValueError:
        pass
    else:
        raise AssertionError("malformed stored image size no longer fails closed")
    rows = [
        {"path": "announcements/one.png"},
        {"url": "/files/announcements/one.png"},
        {"path": "announcements/two.jpg"},
    ]
    assert announcement_image_paths({"images": rows}) == (
        "announcements/one.png",
        "announcements/two.jpg",
    )

    first_ten = [
        {"path": f"announcements/{index}.png"}
        for index in range(1, 12)
    ]
    assert announcement_image_paths({"images": first_ten}) == tuple(
        f"announcements/{index}.png" for index in range(1, 11)
    )


def _verify_visibility_matrix() -> None:
    visible = _announcement("visible", "visible.png")
    public_survey = _announcement(
        "survey",
        "survey.png",
        kind="survey",
        survey={
            "status": "public",
            "questions": [{"id": "q1", "type": "short", "text": "Question"}],
        },
    )
    entries = [
        visible,
        public_survey,
        _announcement("foreign", "foreign.png", targets=["sid-b"]),
        _announcement(
            "future",
            "future.png",
            created_at="2026-08-25T00:00:00Z",
            expires_at="2026-08-26T00:00:00Z",
        ),
        _announcement(
            "expired",
            "expired.png",
            created_at="2026-08-22T00:00:00Z",
            expires_at="2026-08-23T00:00:00Z",
        ),
        _announcement("draft", "draft.png", draft=True),
        _announcement("unpublished", "unpublished.png", published=False),
        _announcement("deleted", "deleted.png", deleted=True),
        _announcement(
            "deleted-at",
            "deleted-at.png",
            deletedAt="2026-08-24T01:00:00Z",
        ),
        _announcement("inactive", "inactive.png", status="inactive"),
        _announcement(
            "closed-survey",
            "closed-survey.png",
            kind="survey",
            survey={
                "status": "closed",
                "questions": [{"id": "q1", "type": "short", "text": "Question"}],
            },
        ),
    ]
    before = copy.deepcopy(entries)

    assert student_can_access_announcement_image(
        entries, "sid-a", "announcements/visible.png", NOW
    )
    assert student_can_access_announcement_image(
        entries, "sid-a", "announcements/survey.png", NOW
    )

    for image_name in (
        "foreign.png",
        "future.png",
        "expired.png",
        "draft.png",
        "unpublished.png",
        "deleted.png",
        "deleted-at.png",
        "inactive.png",
        "closed-survey.png",
        "orphan.png",
    ):
        assert not student_can_access_announcement_image(
            entries,
            "sid-a",
            f"announcements/{image_name}",
            NOW,
        )
    assert not student_can_access_announcement_image(
        entries, "sid-b", "announcements/visible.png", NOW
    )
    assert not student_can_access_announcement_image(
        {"not": "a list"}, "sid-a", "announcements/visible.png", NOW
    )
    assert entries == before


def _verify_locked_store_boundary() -> None:
    with tempfile.TemporaryDirectory(prefix="announcement-image-access-") as temp_dir:
        path = Path(temp_dir) / "announcements.json"
        save_atomic(path, [_announcement("visible", "visible.png")], mirror=False)
        assert student_can_access_announcement_image_from_store(
            path,
            "sid-a",
            "announcements/visible.png",
            now=NOW,
        )
        assert not student_can_access_announcement_image_from_store(
            path,
            "sid-b",
            "announcements/visible.png",
            now=NOW,
        )
        assert not Path(str(path) + ".lock").exists()


def _verify_source_boundary() -> None:
    fs_source = (ROOT / "routes" / "api_fs.py").read_text(encoding="utf-8")
    announcements_source = (
        ROOT / "routes" / "api_announcements.py"
    ).read_text(encoding="utf-8")
    assert "from routes.api_announcements import" not in fs_source
    assert "student_can_access_announcement_image_from_store" in fs_source
    assert "_student_can_access_announcement_image" not in announcements_source
    assert "ANNOUNCEMENT_IMAGE_EXTENSIONS" in announcements_source


def main() -> int:
    _verify_path_normalization()
    _verify_image_membership_projection()
    _verify_visibility_matrix()
    _verify_locked_store_boundary()
    _verify_source_boundary()
    print(
        "announcement image access checks passed: "
        "normalization, membership, visibility, locked store, private-import boundary"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
