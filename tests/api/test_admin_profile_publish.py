"""
Admin profile publish route tests for M36-03 validation evidence.

Exercises api/admin_profile_publish.py's publish_profile service function
and api/main.py's PUT /admin/datasets/{dataset_slug}/publish access-control
and behavior boundary. Tests use direct function/Request-object calls (no
httpx/TestClient dependency, matching tests/api/test_admin_profile_drafts.py)
and configure ATLAS_ADMIN_ENABLED and the persistence modules' repo_root
exclusively through monkeypatched module attributes or temporary
os.environ entries -- never through a .env file or the real repository's
registry/profile-drafts/ or registry/profile-snapshots/ directories.

Draft and snapshot persistence are isolated onto a fake repository root
(pytest tmp_path) with the real contracts/dataset-public-profile.schema.json,
contracts/dataset-public-profile-snapshot.schema.json, and
registry/evidence/dataset-public-profile-snapshot-evidence.schema.json
copied in, the same isolation convention
tests/registry/test_dataset_public_profile_snapshot_store.py uses for the
M36-03/M36-04 persistence modules directly -- the evidence schema is
required because publish_snapshot's M36-04 write_snapshot_evidence side
effect loads it unconditionally on every successful publish.

Run from the repository root:
    python -m pytest tests/api/test_admin_profile_publish.py -v
or directly:
    python tests/api/test_admin_profile_publish.py
"""

import functools
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
API_ROOT = REPO_ROOT / "api"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(API_ROOT))

import admin_profile_publish  # noqa: E402
import main as api_main  # noqa: E402
from fastapi import Request  # noqa: E402
from registry.dataset_public_profile_store import create_draft as _real_create_draft  # noqa: E402
from registry.dataset_public_profile_snapshot_store import (  # noqa: E402
    publish_snapshot as _real_publish_snapshot,
    publish_snapshot_from_payload as _real_publish_snapshot_from_payload,
)


def _make_request(
    headers: dict[str, str],
    method: str = "PUT",
    path: str = "/admin/datasets/example-dataset/publish",
) -> Request:
    encoded_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in headers.items()
    ]
    scope = {"type": "http", "method": method, "path": path, "headers": encoded_headers}
    return Request(scope)


def _build_fake_repo(tmp_root: Path) -> Path:
    contracts_dir = tmp_root / "contracts"
    contracts_dir.mkdir(parents=True)
    shutil.copy2(
        REPO_ROOT / "contracts" / "dataset-public-profile.schema.json",
        contracts_dir / "dataset-public-profile.schema.json",
    )
    shutil.copy2(
        REPO_ROOT / "contracts" / "dataset-public-profile-snapshot.schema.json",
        contracts_dir / "dataset-public-profile-snapshot.schema.json",
    )

    registry_dir = tmp_root / "registry"
    registry_dir.mkdir(parents=True)

    evidence_schema_dir = registry_dir / "evidence"
    evidence_schema_dir.mkdir()
    shutil.copy2(
        REPO_ROOT / "registry" / "evidence" / "dataset-public-profile-snapshot-evidence.schema.json",
        evidence_schema_dir / "dataset-public-profile-snapshot-evidence.schema.json",
    )
    (registry_dir / "datasets.json").write_text(
        json.dumps({
            "schema_version": "atlas.dataflow.registry.v1",
            "datasets": [
                {
                    "dataset_slug": "example-dataset",
                    "active_release": "release-20260101-001",
                    "public_metadata": {
                        "title": "Example Dataset",
                        "summary": "Test dataset for publish route tests.",
                        "domain": "generic",
                        "visibility": "public",
                        "tags": [],
                    },
                },
            ],
        }),
        encoding="utf-8",
    )

    metrics_dir = tmp_root / "releases" / "release-20260101-001" / "metrics"
    metrics_dir.mkdir(parents=True)
    metrics_dir.joinpath("metrics.json").write_text(
        json.dumps({
            "schema_version": "metrics.v1",
            "dataset_slug": "example-dataset",
            "release_id": "release-20260101-001",
            "evaluation": {"split": "test", "sample_size": 1, "metrics": {"accuracy": 1.0}},
        }),
        encoding="utf-8",
    )
    return tmp_root


def _install_isolated_publish(fake_repo: Path) -> object:
    original_publish_snapshot = admin_profile_publish.publish_snapshot
    original_publish_snapshot_from_payload = admin_profile_publish.publish_snapshot_from_payload
    admin_profile_publish.publish_snapshot = functools.partial(
        _real_publish_snapshot, repo_root=fake_repo
    )
    admin_profile_publish.publish_snapshot_from_payload = functools.partial(
        _real_publish_snapshot_from_payload, repo_root=fake_repo
    )
    return (original_publish_snapshot, original_publish_snapshot_from_payload)


def _restore_publish(original: object) -> None:
    original_publish_snapshot, original_publish_snapshot_from_payload = original
    admin_profile_publish.publish_snapshot = original_publish_snapshot
    admin_profile_publish.publish_snapshot_from_payload = original_publish_snapshot_from_payload


_VALID_PROFILE = {
    "schema_version": "0.1.0",
    "dataset_slug": "example-dataset",
}


def test_profile_draft_load_exposes_latest_published_snapshot_for_reload_hydration(monkeypatch):
    stale_draft = {**_VALID_PROFILE, "home_card": {"icon": "telecom"}}
    published_profile = {
        **_VALID_PROFILE,
        "home_card": {
            "icon": "weather-cloud",
            "background_image_ref": "/media/home-cards/0123456789abcdef0123456789abcdef.png",
            "short_description": "Latest published card copy",
        },
        "performance_focus": {
            "focus_id": "balanced_classification",
            "highlighted_score_id": "balanced_accuracy",
            "visible_scores": [{
                "score_id": "balanced_accuracy",
                "display_label": "Balanced Accuracy",
                "value": "0.91",
                "value_source": "manual",
                "order": 0,
            }],
        },
    }
    published_snapshot = {
        "published_at": "2026-07-11T14:00:00Z",
        "active_release_at_publish_time": "release-20260101-001",
        "source_draft_schema_version": "0.1.0",
        "profile": published_profile,
    }
    monkeypatch.setattr(api_main, "read_profile_draft", lambda _slug: {
        "draft_exists": True,
        "profile": stale_draft,
    })
    monkeypatch.setattr(api_main, "read_published_profile_snapshot", lambda _slug: published_snapshot)
    monkeypatch.setattr(api_main, "resolve_dataset", lambda _slug: type(
        "Resolved", (), {"active_release": "release-20260101-001"}
    )())
    monkeypatch.setenv("ATLAS_ADMIN_ENABLED", "true")
    monkeypatch.delenv("ADMIN_API_TOKEN", raising=False)

    response = api_main.get_admin_profile_draft(
        "example-dataset",
        _make_request({}, method="GET", path="/admin/datasets/example-dataset/profile-draft"),
    )

    assert response["profile"] == stale_draft
    assert response["published_snapshot"] == published_snapshot
    assert response["profile_hydration"] == {
        "source": "current_release_snapshot",
        "active_release": "release-20260101-001",
    }


def test_profile_draft_load_ignores_stale_or_unbound_snapshot(monkeypatch):
    stale_profile = {
        **_VALID_PROFILE,
        "home_card": {
            "icon": "weather-cloud",
            "background_image_ref": "/media/home-cards/0123456789abcdef0123456789abcdef.png",
            "short_description": "Old lifecycle copy",
        },
        "performance_focus": {"focus_id": "old-focus"},
    }
    monkeypatch.setattr(api_main, "read_profile_draft", lambda _slug: {
        "draft_exists": True,
        "profile": stale_profile,
    })
    monkeypatch.setattr(api_main, "resolve_dataset", lambda _slug: type(
        "Resolved", (), {"active_release": "release-20260101-002"}
    )())
    monkeypatch.setenv("ATLAS_ADMIN_ENABLED", "true")
    monkeypatch.delenv("ADMIN_API_TOKEN", raising=False)

    for snapshot in (
        {"active_release_at_publish_time": "release-20260101-001", "profile": stale_profile},
        {"profile": stale_profile},
    ):
        monkeypatch.setattr(api_main, "read_published_profile_snapshot", lambda _slug, value=snapshot: value)
        response = api_main.get_admin_profile_draft(
            "example-dataset",
            _make_request({}, method="GET", path="/admin/datasets/example-dataset/profile-draft"),
        )

        assert "published_snapshot" not in response
        assert response["profile_hydration"] == {
            "source": "fresh_promotion_baseline",
            "active_release": "release-20260101-002",
        }
        # Compatibility data may remain present, but the explicit hydration
        # contract prevents current clients from using it as their baseline.
        assert response["profile"] == stale_profile


# ---------------------------------------------------------------------------
# admin_profile_publish.publish_profile: direct calls
# ---------------------------------------------------------------------------


def test_publish_profile_rejects_when_no_draft_exists():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(Path(tmp))
        original = _install_isolated_publish(fake_repo)
        try:
            result = admin_profile_publish.publish_profile("example-dataset")
        finally:
            _restore_publish(original)

        assert result["published"] is False
        assert result["snapshot"] is None
        assert any(error["code"] == "NO_DRAFT_TO_PUBLISH" for error in result["errors"])


def test_publish_profile_succeeds_after_draft_saved():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(Path(tmp))
        _real_create_draft("example-dataset", dict(_VALID_PROFILE), repo_root=fake_repo)
        original = _install_isolated_publish(fake_repo)
        try:
            result = admin_profile_publish.publish_profile("example-dataset")
        finally:
            _restore_publish(original)

        assert result["published"] is True
        assert result["errors"] == []
        assert result["snapshot"]["dataset_slug"] == "example-dataset"
        assert result["snapshot"]["active_release_at_publish_time"] == "release-20260101-001"


# ---------------------------------------------------------------------------
# PUT /admin/datasets/{dataset_slug}/publish: access-control boundary
# ---------------------------------------------------------------------------


def test_publish_route_returns_generic_not_found_when_admin_runtime_unset():
    os.environ.pop("ATLAS_ADMIN_ENABLED", None)
    os.environ.pop("ADMIN_API_TOKEN", None)
    request = _make_request({})
    response = api_main.put_admin_profile_publish("example-dataset", request)
    assert response.status_code == 404
    assert json.loads(response.body.decode("utf-8")) == {"detail": "Not Found"}


def test_publish_route_returns_generic_not_found_when_admin_runtime_false_even_with_token_header():
    os.environ["ATLAS_ADMIN_ENABLED"] = "false"
    os.environ["ADMIN_API_TOKEN"] = "correct-token"
    try:
        request = _make_request({"X-Admin-Token": "wrong-token"})
        response = api_main.put_admin_profile_publish("example-dataset", request)
        assert response.status_code == 404
        assert json.loads(response.body.decode("utf-8")) == {"detail": "Not Found"}
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)
        os.environ.pop("ADMIN_API_TOKEN", None)


def test_publish_route_returns_422_when_no_draft_exists_in_private_runtime_without_token_header():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(Path(tmp))
        original = _install_isolated_publish(fake_repo)
        try:
            request = _make_request({})
            response = api_main.put_admin_profile_publish("example-dataset", request)
        finally:
            _restore_publish(original)
            os.environ.pop("ATLAS_ADMIN_ENABLED", None)
            os.environ.pop("ADMIN_API_TOKEN", None)

    assert response.status_code == 422
    body = json.loads(response.body.decode("utf-8"))
    assert body["error_code"] == "PROFILE_PUBLISH_FAILED"
    assert body["errors"], "expected passthrough validation errors"


def test_publish_route_succeeds_after_draft_saved_in_private_runtime_without_token_header():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(Path(tmp))
        _real_create_draft("example-dataset", dict(_VALID_PROFILE), repo_root=fake_repo)
        original = _install_isolated_publish(fake_repo)
        try:
            request = _make_request({})
            response = api_main.put_admin_profile_publish("example-dataset", request)
        finally:
            _restore_publish(original)
            os.environ.pop("ATLAS_ADMIN_ENABLED", None)
            os.environ.pop("ADMIN_API_TOKEN", None)

    assert response["published"] is True
    assert response["dataset_slug"] == "example-dataset"
    assert response["snapshot"]["dataset_slug"] == "example-dataset"


def test_publish_route_with_body_publishes_payload_directly_without_a_draft():
    # Project Spec S0061: Dataset Admin's Publish changes flow no longer
    # requires a persisted profile-draft as part of the normal publish path.
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(Path(tmp))
        original = _install_isolated_publish(fake_repo)
        try:
            request = _make_request({})
            payload = {
                "schema_version": "0.1.0",
                "dataset_slug": "example-dataset",
                "display": {"title": "Directly published title"},
            }
            response = api_main.put_admin_profile_publish("example-dataset", request, payload)

            assert response["published"] is True
            assert response["display_title"] == "Directly published title"
            assert response["snapshot"]["dataset_slug"] == "example-dataset"
            assert response["snapshot"]["profile"]["display"]["title"] == "Directly published title"
            # No draft was ever created for example-dataset in this fake
            # repo, so a successful direct publish proves the persisted
            # draft store was never read along this path.
            assert not (fake_repo / "registry" / "profile-drafts" / "example-dataset.json").exists()
        finally:
            _restore_publish(original)
            os.environ.pop("ATLAS_ADMIN_ENABLED", None)
            os.environ.pop("ADMIN_API_TOKEN", None)


def test_publish_route_accepts_and_persists_each_new_bounded_icon():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(Path(tmp))
        original = _install_isolated_publish(fake_repo)
        try:
            for icon in ("money-dollar", "globe", "flask", "cpu-chip"):
                payload = {**_VALID_PROFILE, "home_card": {"icon": icon}}
                response = api_main.put_admin_profile_publish(
                    "example-dataset", _make_request({}), payload
                )

                assert response["published"] is True
                assert response["snapshot"]["profile"]["home_card"]["icon"] == icon
        finally:
            _restore_publish(original)
            os.environ.pop("ATLAS_ADMIN_ENABLED", None)
            os.environ.pop("ADMIN_API_TOKEN", None)


def test_publish_route_with_invalid_body_returns_422_and_preserves_previous_snapshot():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(Path(tmp))
        original = _install_isolated_publish(fake_repo)
        try:
            first_request = _make_request({})
            first_response = api_main.put_admin_profile_publish(
                "example-dataset", first_request, dict(_VALID_PROFILE)
            )
            assert first_response["published"] is True
            previous_snapshot = first_response["snapshot"]

            second_request = _make_request({})
            invalid_payload = {**_VALID_PROFILE, "unexpected_field": "not allowed by the schema"}
            second_response = api_main.put_admin_profile_publish(
                "example-dataset", second_request, invalid_payload
            )

            assert second_response.status_code == 422
            body = json.loads(second_response.body.decode("utf-8"))
            assert body["error_code"] == "PROFILE_PUBLISH_FAILED"
            assert body["errors"], "expected passthrough validation errors"

            snapshot_path = fake_repo / "registry" / "profile-snapshots" / "example-dataset.json"
            on_disk_snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            assert on_disk_snapshot == previous_snapshot
        finally:
            _restore_publish(original)
            os.environ.pop("ATLAS_ADMIN_ENABLED", None)
            os.environ.pop("ADMIN_API_TOKEN", None)


def test_publish_route_with_body_rejects_dataset_slug_mismatch():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(Path(tmp))
        original = _install_isolated_publish(fake_repo)
        try:
            request = _make_request({})
            mismatched_payload = {"schema_version": "0.1.0", "dataset_slug": "other-dataset"}
            response = api_main.put_admin_profile_publish("example-dataset", request, mismatched_payload)

            assert response.status_code == 422
            body = json.loads(response.body.decode("utf-8"))
            assert any(error["code"] == "DATASET_SLUG_MISMATCH" for error in body["errors"])
            assert not (fake_repo / "registry" / "profile-snapshots" / "example-dataset.json").exists()
        finally:
            _restore_publish(original)
            os.environ.pop("ATLAS_ADMIN_ENABLED", None)
            os.environ.pop("ADMIN_API_TOKEN", None)


def test_publish_route_with_body_succeeds_while_visibility_is_off():
    # Preserves visibility as a separate concern from snapshot publication:
    # a direct publish must not require Public visibility to be on.
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(Path(tmp))
        registry_path = fake_repo / "registry" / "datasets.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registry["datasets"][0]["public_metadata"]["visibility"] = "private"
        registry_path.write_text(json.dumps(registry), encoding="utf-8")

        original = _install_isolated_publish(fake_repo)
        try:
            request = _make_request({})
            response = api_main.put_admin_profile_publish("example-dataset", request, dict(_VALID_PROFILE))
        finally:
            _restore_publish(original)
            os.environ.pop("ATLAS_ADMIN_ENABLED", None)
            os.environ.pop("ADMIN_API_TOKEN", None)

    assert response["published"] is True
    assert response["snapshot"]["dataset_slug"] == "example-dataset"


def test_publish_route_returns_422_for_invalid_dataset_slug():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    try:
        request = _make_request(
            {},
            path="/admin/datasets/Invalid Slug/publish",
        )
        response = api_main.put_admin_profile_publish("Invalid Slug", request)
        assert response.status_code == 422
        assert json.loads(response.body.decode("utf-8"))["error_code"] == (
            "PROFILE_PUBLISH_DATASET_SLUG_INVALID"
        )
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)
        os.environ.pop("ADMIN_API_TOKEN", None)


# ---------------------------------------------------------------------------
# Public surface non-exposure
# ---------------------------------------------------------------------------


def test_publish_route_registered_only_under_admin_and_public_datasets_unchanged():
    paths = {route.path for route in api_main.app.routes}
    assert "/admin/datasets/{dataset_slug}/publish" in paths

    public_paths = {path for path in paths if not path.startswith("/admin")}
    assert not any("publish" in path for path in public_paths)


def test_home_card_image_store_accepts_ordinary_names_and_generates_safe_references(tmp_path):
    cases = [
        ("Home card final.png", "image/png", b"\x89PNG\r\n\x1a\n" + b"png", ".png"),
        ("Customer churn (final).jpeg", "image/jpeg", b"\xff\xd8\xff" + b"jpeg", ".jpg"),
        ("home_card-v2.webp", "image/webp", b"RIFF\x04\x00\x00\x00WEBPdata", ".webp"),
        ("visão geral.avif", "image/avif", b"\x00\x00\x00\x18ftypavifdata", ".avif"),
    ]
    for filename, content_type, content, expected_extension in cases:
        result = admin_profile_publish.store_home_card_image(filename, content_type, content, tmp_path)

        assert result["uploaded"] is True
        assert result["media_ref"].startswith("/media/home-cards/")
        assert filename not in result["media_ref"]
        stored_name = result["media_ref"].rsplit("/", 1)[-1]
        assert stored_name.endswith(expected_extension)
        assert admin_profile_publish.resolve_home_card_media_path(stored_name, tmp_path).read_bytes() == content


def test_home_card_image_store_uses_signature_with_generic_or_missing_mime(tmp_path):
    png = b"\x89PNG\r\n\x1a\n" + b"safe image payload"
    for content_type in (None, "", "application/octet-stream"):
        result = admin_profile_publish.store_home_card_image("imagem verão.jpg", content_type, png, tmp_path)
        assert result["uploaded"] is True
        assert result["media_ref"].endswith(".png")


def test_home_card_image_store_rejects_traversal_svg_oversize_and_invalid_content(tmp_path):
    valid_png = b"\x89PNG\r\n\x1a\n" + b"payload"
    cases = [
        ("../card.png", "image/png", valid_png),
        ("..%2Fcard.png", "application/octet-stream", valid_png),
        ("folder\\card.png", "image/png", valid_png),
        ("card.svg", "image/svg+xml", b"<svg><script/></svg>"),
        ("card.png", "image/png", b"not a png"),
        ("card.jpg", "image/jpeg", valid_png),
        ("card.png", "image/png", valid_png + b"x" * admin_profile_publish.HOME_CARD_IMAGE_MAX_BYTES),
    ]
    for filename, content_type, content in cases:
        result = admin_profile_publish.store_home_card_image(filename, content_type, content, tmp_path)
        assert result["uploaded"] is False
        assert result["media_ref"] is None

    assert not (tmp_path / "media").exists()


def test_home_card_media_resolver_serves_only_generated_safe_filenames(tmp_path, monkeypatch):
    png = b"\x89PNG\r\n\x1a\n" + b"safe image payload"
    stored = admin_profile_publish.store_home_card_image(
        "Home card.png", "image/png", png, tmp_path
    )
    stored_name = stored["media_ref"].rsplit("/", 1)[-1]
    monkeypatch.setenv("ATLAS_MEDIA_ROOT", str(tmp_path / "media"))

    response = api_main.get_home_card_image(stored_name)
    assert response.path == tmp_path / "media" / "home-cards" / stored_name
    assert response.media_type == "image/png"

    for unsafe_name in (
        "does-not-exist.png",
        "published.png",
        "../" + stored_name,
        "%2e%2e%2f" + stored_name,
        stored_name.upper(),
    ):
        assert admin_profile_publish.resolve_home_card_media_path(unsafe_name, tmp_path) is None


def test_home_card_media_route_returns_safe_json_404_for_missing_file():
    response = api_main.get_home_card_image("0" * 32 + ".png")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert json.loads(response.body.decode("utf-8")) == {"detail": "Not Found"}


def test_published_profile_keeps_only_bounded_home_card_media_reference():
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(Path(tmp))
        original = _install_isolated_publish(fake_repo)
        try:
            media_ref = "/media/home-cards/" + "a" * 32 + ".webp"
            payload = {**_VALID_PROFILE, "home_card": {"background_image_ref": media_ref}}
            response = api_main.put_admin_profile_publish(
                "example-dataset", _make_request({}), payload
            )

            assert response["published"] is True
            assert response["snapshot"]["profile"]["home_card"]["background_image_ref"] == media_ref
        finally:
            _restore_publish(original)
            os.environ.pop("ATLAS_ADMIN_ENABLED", None)
            os.environ.pop("ADMIN_API_TOKEN", None)


def test_remove_profile_artifacts_cleans_lifecycle_and_only_unshared_media(tmp_path):
    deleted_slug = "deleted-dataset"
    live_slug = "live-dataset"
    deleted_media = "a" * 32 + ".png"
    shared_media = "b" * 32 + ".webp"
    media_root = tmp_path / "media" / "home-cards"
    media_root.mkdir(parents=True)
    (media_root / deleted_media).write_bytes(b"deleted")
    (media_root / shared_media).write_bytes(b"shared")

    registry_root = tmp_path / "registry"
    registry_root.mkdir()
    (registry_root / "datasets.json").write_text(json.dumps({
        "datasets": [{"dataset_slug": live_slug}],
    }), encoding="utf-8")

    artifact_paths = [
        registry_root / "profile-drafts" / f"{deleted_slug}.json",
        registry_root / "profile-drafts" / f"{deleted_slug}.json.previous",
        registry_root / "profile-snapshots" / f"{deleted_slug}.json",
        registry_root / "profile-snapshots" / f"{deleted_slug}.json.previous",
        registry_root / "profile-snapshots" / f"{deleted_slug}.evidence.json",
        registry_root / "profile-publications" / f"{deleted_slug}.json",
    ]
    for path in artifact_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "home_card": {
                "deleted": f"/media/home-cards/{deleted_media}",
                "shared": f"/media/home-cards/{shared_media}",
                "unsafe": "/media/home-cards/../../outside.png",
            },
        }), encoding="utf-8")

    live_snapshot = registry_root / "profile-snapshots" / f"{live_slug}.json"
    live_snapshot.write_text(json.dumps({
        "profile": {"home_card": {"background_image_ref": f"/media/home-cards/{shared_media}"}},
    }), encoding="utf-8")

    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")
    result = admin_profile_publish.remove_profile_artifacts(deleted_slug, tmp_path)

    assert result == {
        "completed": True,
        "artifacts_removed": 6,
        "media_removed": 1,
        "errors": [],
    }
    assert all(not path.exists() for path in artifact_paths)
    assert not (media_root / deleted_media).exists()
    assert (media_root / shared_media).is_file()
    assert outside.is_file()
    assert live_snapshot.is_file()

    assert admin_profile_publish.remove_profile_artifacts(deleted_slug, tmp_path) == {
        "completed": True,
        "artifacts_removed": 0,
        "media_removed": 0,
        "errors": [],
    }


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
