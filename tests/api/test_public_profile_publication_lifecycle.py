"""
Final M36 lifecycle integration coverage.

This test stitches the M36 draft, publish, evidence, visibility, and public
route boundaries together without writing to the repository's runtime
registry/profile-drafts, registry/profile-snapshots, or
registry/profile-publications directories.
"""

import functools
import json
import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
API_ROOT = REPO_ROOT / "api"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(API_ROOT))

import admin_profile_drafts  # noqa: E402
import admin_profile_publish  # noqa: E402
import main as api_main  # noqa: E402
from fastapi import Request  # noqa: E402
from public_profile_visibility import resolve_dataset_visibility as _real_resolve_visibility  # noqa: E402
from registry.dataset_public_profile_publication_store import set_visibility as _real_set_visibility  # noqa: E402
from registry.dataset_public_profile_snapshot_store import publish_snapshot as _real_publish_snapshot  # noqa: E402
from registry.dataset_public_profile_store import (  # noqa: E402
    create_draft as _real_create_draft,
    get_draft as _real_get_draft,
    update_draft as _real_update_draft,
)

_TARGET_SLUG = "telco-customer-churn"
_RELEASE_ID = "release-20260101-001"
_ADMIN_TOKEN = "correct-token"
_PRIVATE_MARKER = "M36-07-private-draft-marker-6dd9c1"


def _make_request(
    method: str = "PUT",
    path: str = f"/admin/datasets/{_TARGET_SLUG}/profile-draft",
) -> Request:
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [(b"x-admin-token", _ADMIN_TOKEN.encode("latin-1"))],
    }
    return Request(scope)


def _write_metrics(fake_repo: Path, metrics: dict[str, float]) -> None:
    metrics_path = fake_repo / "releases" / _RELEASE_ID / "metrics" / "metrics.json"
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(
        json.dumps(
            {
                "schema_version": "metrics.v1",
                "dataset_slug": _TARGET_SLUG,
                "release_id": _RELEASE_ID,
                "evaluation": {"split": "test", "sample_size": 1, "metrics": metrics},
            }
        ),
        encoding="utf-8",
    )


def _build_fake_repo(tmp_path: Path) -> Path:
    fake_repo = tmp_path / "isolated-repo"

    contracts_dir = fake_repo / "contracts"
    contracts_dir.mkdir(parents=True)
    for schema_name in (
        "dataset-public-profile.schema.json",
        "dataset-public-profile-snapshot.schema.json",
    ):
        shutil.copy2(REPO_ROOT / "contracts" / schema_name, contracts_dir / schema_name)

    registry_dir = fake_repo / "registry"
    registry_dir.mkdir()
    (registry_dir / "datasets.json").write_text(
        json.dumps(
            {
                "schema_version": "atlas.dataflow.registry.v1",
                "datasets": [
                    {
                        "dataset_slug": _TARGET_SLUG,
                        "active_release": _RELEASE_ID,
                        "public_metadata": {
                            "title": "Telco Customer Churn",
                            "summary": "Customer churn prediction dataset",
                            "domain": "telecom",
                            "visibility": "public",
                            "tags": ["telecom"],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    evidence_schema_dir = registry_dir / "evidence"
    evidence_schema_dir.mkdir()
    shutil.copy2(
        REPO_ROOT
        / "registry"
        / "evidence"
        / "dataset-public-profile-snapshot-evidence.schema.json",
        evidence_schema_dir / "dataset-public-profile-snapshot-evidence.schema.json",
    )

    _write_metrics(fake_repo, {"accuracy": 0.86, "auc_roc": 0.93})
    return fake_repo


def _profile(title: str, primary_metric_key: str | None = None) -> dict:
    profile = {
        "schema_version": "0.1.0",
        "dataset_slug": _TARGET_SLUG,
        "display": {
            "title": title,
            "subtitle": "Operator-authored private draft subtitle",
        },
    }
    if primary_metric_key is not None:
        profile["home_card"] = {
            "short_description": "Private draft home card copy",
            "primary_metric_key": primary_metric_key,
        }
    return profile


def _install_isolated_lifecycle(monkeypatch, fake_repo: Path) -> None:
    monkeypatch.setenv("ADMIN_API_TOKEN", _ADMIN_TOKEN)
    monkeypatch.setattr(
        admin_profile_drafts,
        "create_draft",
        functools.partial(_real_create_draft, repo_root=fake_repo),
    )
    monkeypatch.setattr(
        admin_profile_drafts,
        "get_draft",
        functools.partial(_real_get_draft, repo_root=fake_repo),
    )
    monkeypatch.setattr(
        admin_profile_drafts,
        "update_draft",
        functools.partial(_real_update_draft, repo_root=fake_repo),
    )
    monkeypatch.setattr(
        admin_profile_publish,
        "publish_snapshot",
        functools.partial(_real_publish_snapshot, repo_root=fake_repo),
    )
    monkeypatch.setattr(
        api_main,
        "resolve_dataset_visibility",
        functools.partial(_real_resolve_visibility, repo_root=fake_repo),
    )
    monkeypatch.setattr(
        api_main,
        "set_dataset_visibility",
        lambda dataset_slug, visible: {
            **_real_set_visibility(dataset_slug, visible, repo_root=fake_repo)
        },
    )


def _public_payload_contains_marker() -> bool:
    public_payloads = [
        api_main.list_datasets_endpoint(),
        api_main.get_dataset(_TARGET_SLUG),
    ]
    return _PRIVATE_MARKER in json.dumps(public_payloads, sort_keys=True, default=str)


def test_public_profile_publication_lifecycle_keeps_private_drafts_out_of_public_routes(
    tmp_path,
    monkeypatch,
):
    fake_repo = _build_fake_repo(tmp_path)
    _install_isolated_lifecycle(monkeypatch, fake_repo)

    draft_response = api_main.put_admin_profile_draft(
        _TARGET_SLUG,
        _make_request(path=f"/admin/datasets/{_TARGET_SLUG}/profile-draft"),
        _profile(_PRIVATE_MARKER),
    )
    assert draft_response["saved"] is True
    assert _public_payload_contains_marker() is False

    publish_response = api_main.put_admin_profile_publish(
        _TARGET_SLUG,
        _make_request(path=f"/admin/datasets/{_TARGET_SLUG}/publish"),
    )
    assert publish_response["published"] is True
    assert publish_response["snapshot"]["profile"]["display"]["title"] == _PRIVATE_MARKER

    snapshot_path = fake_repo / "registry" / "profile-snapshots" / f"{_TARGET_SLUG}.json"
    evidence_path = fake_repo / "registry" / "profile-snapshots" / f"{_TARGET_SLUG}.evidence.json"
    assert snapshot_path.is_file()
    assert evidence_path.is_file()
    snapshot_before_failure = snapshot_path.read_text(encoding="utf-8")
    evidence_before_failure = evidence_path.read_text(encoding="utf-8")

    metric_bound_profile = _profile("Metric-bound draft that must fail later", "auc_roc")
    update_response = api_main.put_admin_profile_draft(
        _TARGET_SLUG,
        _make_request(path=f"/admin/datasets/{_TARGET_SLUG}/profile-draft"),
        metric_bound_profile,
    )
    assert update_response["saved"] is True
    _write_metrics(fake_repo, {"accuracy": 0.86})

    failed_publish = api_main.put_admin_profile_publish(
        _TARGET_SLUG,
        _make_request(path=f"/admin/datasets/{_TARGET_SLUG}/publish"),
    )
    assert failed_publish.status_code == 422
    failed_body = json.loads(failed_publish.body.decode("utf-8"))
    assert failed_body["error_code"] == "PROFILE_PUBLISH_FAILED"
    assert failed_body["errors"], "expected a sanitized publish failure"
    assert snapshot_path.read_text(encoding="utf-8") == snapshot_before_failure
    assert evidence_path.read_text(encoding="utf-8") == evidence_before_failure
    assert not (snapshot_path.parent / f"{_TARGET_SLUG}.json.previous").exists()

    hidden_response = api_main.put_admin_profile_visibility(
        _TARGET_SLUG,
        _make_request(path=f"/admin/datasets/{_TARGET_SLUG}/visibility"),
        {"visible": False},
    )
    assert hidden_response["visible"] is False
    hidden_list = api_main.list_datasets_endpoint()
    assert _TARGET_SLUG not in {entry["dataset_slug"] for entry in hidden_list["datasets"]}
    hidden_detail = api_main.get_dataset(_TARGET_SLUG)
    nonexistent_detail = api_main.get_dataset("dataset-that-does-not-exist")
    assert hidden_detail.status_code == nonexistent_detail.status_code
    assert json.loads(hidden_detail.body.decode("utf-8")) == json.loads(
        nonexistent_detail.body.decode("utf-8")
    )

    visible_response = api_main.put_admin_profile_visibility(
        _TARGET_SLUG,
        _make_request(path=f"/admin/datasets/{_TARGET_SLUG}/visibility"),
        {"visible": True},
    )
    assert visible_response["visible"] is True
    visible_list = api_main.list_datasets_endpoint()
    assert _TARGET_SLUG in {entry["dataset_slug"] for entry in visible_list["datasets"]}
    assert api_main.get_dataset(_TARGET_SLUG)["dataset_slug"] == _TARGET_SLUG

    assert (fake_repo / "registry" / "profile-drafts" / f"{_TARGET_SLUG}.json").is_file()
    assert (fake_repo / "registry" / "profile-publications" / f"{_TARGET_SLUG}.json").is_file()
    assert os.environ["ADMIN_API_TOKEN"] == _ADMIN_TOKEN
