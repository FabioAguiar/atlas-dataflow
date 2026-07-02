"""
Dataset public profile store tests for M34-03.

Verifies create_draft, get_draft, update_draft, and validate_profile_draft
against an isolated fake repository root (pytest tmp_path), so no test writes
into the real registry/profile-drafts/ location or any other real repository
path. The real contracts/dataset-public-profile.schema.json is copied into
the fake repo root so schema validation exercises the real schema, not a
hand-authored replica.

Run from the repository root:
    python -m pytest tests/registry/test_dataset_public_profile_store.py -v
"""

import json
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from registry.dataset_public_profile_store import (  # noqa: E402
    ProfileDraftNotFoundError,
    create_draft,
    get_draft,
    update_draft,
)


_MOCK_PREDICT_VIEWS_REGISTRY = {
    "schema_version": "atlas.dataflow.predict-views.v1",
    "predict_views": [
        {"view_id": "churn-risk-overview", "dataset_slug": "telco-customer-churn"},
    ],
}

_MOCK_DATASETS_REGISTRY = {
    "schema_version": "atlas.dataflow.registry.v1",
    "datasets": [
        {
            "dataset_slug": "telco-customer-churn",
            "active_release": "release-20260101-001",
            "public_metadata": {
                "title": "Telco Customer Churn",
                "summary": "Test dataset for store persistence tests.",
                "domain": "telco",
                "visibility": "public",
                "tags": ["telco"],
            },
        },
    ],
}

_MOCK_RELEASE_METRICS = {
    "schema_version": "metrics.v1",
    "dataset_slug": "telco-customer-churn",
    "release_id": "release-20260101-001",
    "evaluation": {
        "split": "test",
        "sample_size": 1000,
        "metrics": {"accuracy": 0.9, "auc_roc": 0.85},
    },
}


def _profile(**overrides) -> dict:
    base = {"schema_version": "1.0.0", "dataset_slug": "telco-customer-churn"}
    base.update(overrides)
    return base


def _codes(result: dict) -> set:
    return {e["code"] for e in result["errors"]}


@pytest.fixture
def fake_repo(tmp_path):
    schema_src = REPO_ROOT / "contracts" / "dataset-public-profile.schema.json"
    contracts_dir = tmp_path / "contracts"
    contracts_dir.mkdir()
    shutil.copy2(schema_src, contracts_dir / "dataset-public-profile.schema.json")

    registry_dir = tmp_path / "registry"
    registry_dir.mkdir()
    (registry_dir / "predict-views.json").write_text(
        json.dumps(_MOCK_PREDICT_VIEWS_REGISTRY), encoding="utf-8"
    )
    (registry_dir / "datasets.json").write_text(
        json.dumps(_MOCK_DATASETS_REGISTRY), encoding="utf-8"
    )

    metrics_dir = tmp_path / "releases" / "release-20260101-001" / "metrics"
    metrics_dir.mkdir(parents=True)
    (metrics_dir / "metrics.json").write_text(
        json.dumps(_MOCK_RELEASE_METRICS), encoding="utf-8"
    )

    return tmp_path


def test_create_draft_success(fake_repo):
    result = create_draft("telco-customer-churn", _profile(), repo_root=fake_repo)

    assert result["created"] is True
    assert result["errors"] == []
    draft_path = fake_repo / "registry" / "profile-drafts" / "telco-customer-churn.json"
    assert draft_path.is_file()


def test_create_draft_dataset_slug_mismatch(fake_repo):
    profile = _profile()
    profile["dataset_slug"] = "bank-marketing"

    result = create_draft("telco-customer-churn", profile, repo_root=fake_repo)

    assert result["created"] is False
    assert "DATASET_SLUG_MISMATCH" in _codes(result)


def test_create_draft_already_exists(fake_repo):
    create_draft("telco-customer-churn", _profile(), repo_root=fake_repo)

    result = create_draft("telco-customer-churn", _profile(), repo_root=fake_repo)

    assert result["created"] is False
    assert "PROFILE_DRAFT_ALREADY_EXISTS" in _codes(result)


def test_create_draft_rejects_schema_invalid_profile(fake_repo):
    invalid_profile = {
        "schema_version": "1.0.0",
        "dataset_slug": "telco-customer-churn",
        "unexpected_field_not_in_schema": True,
    }

    result = create_draft("telco-customer-churn", invalid_profile, repo_root=fake_repo)

    assert result["created"] is False
    assert "SCHEMA_VALIDATION_ERROR" in _codes(result)
    draft_path = fake_repo / "registry" / "profile-drafts" / "telco-customer-churn.json"
    assert not draft_path.exists()


def test_create_draft_rejects_unresolvable_reference(fake_repo):
    profile = _profile(inference_presentation={"bound_predict_view_id": "does-not-exist"})

    result = create_draft("telco-customer-churn", profile, repo_root=fake_repo)

    assert result["created"] is False
    assert "BOUND_PREDICT_VIEW_NOT_FOUND" in _codes(result)


def test_get_draft_returns_created_content(fake_repo):
    create_draft("telco-customer-churn", _profile(), repo_root=fake_repo)

    draft = get_draft("telco-customer-churn", repo_root=fake_repo)

    assert draft["dataset_slug"] == "telco-customer-churn"


def test_get_draft_missing_raises_not_found(fake_repo):
    with pytest.raises(ProfileDraftNotFoundError):
        get_draft("telco-customer-churn", repo_root=fake_repo)


def test_get_draft_invalid_json_raises_not_found(fake_repo):
    drafts_dir = fake_repo / "registry" / "profile-drafts"
    drafts_dir.mkdir(parents=True)
    (drafts_dir / "telco-customer-churn.json").write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ProfileDraftNotFoundError):
        get_draft("telco-customer-churn", repo_root=fake_repo)


def test_get_draft_schema_invalid_content_raises_not_found(fake_repo):
    drafts_dir = fake_repo / "registry" / "profile-drafts"
    drafts_dir.mkdir(parents=True)
    invalid_profile = {
        "schema_version": "1.0.0",
        "dataset_slug": "telco-customer-churn",
        "unexpected_field_not_in_schema": True,
    }
    (drafts_dir / "telco-customer-churn.json").write_text(
        json.dumps(invalid_profile), encoding="utf-8"
    )

    with pytest.raises(ProfileDraftNotFoundError):
        get_draft("telco-customer-churn", repo_root=fake_repo)


def test_update_draft_success_creates_backup_and_replaces_content(fake_repo):
    create_draft("telco-customer-churn", _profile(), repo_root=fake_repo)
    updated_profile = _profile(display={"title": "Updated Title"})

    result = update_draft("telco-customer-churn", updated_profile, repo_root=fake_repo)

    assert result["updated"] is True
    backup_path = fake_repo / "registry" / "profile-drafts" / "telco-customer-churn.json.previous"
    assert backup_path.is_file()
    draft = get_draft("telco-customer-churn", repo_root=fake_repo)
    assert draft["display"]["title"] == "Updated Title"


def test_update_draft_nonexistent_rejected(fake_repo):
    result = update_draft("telco-customer-churn", _profile(), repo_root=fake_repo)

    assert result["updated"] is False
    assert "PROFILE_DRAFT_NOT_FOUND_FOR_UPDATE" in _codes(result)
    backup_path = fake_repo / "registry" / "profile-drafts" / "telco-customer-churn.json.previous"
    assert not backup_path.exists()


@pytest.mark.parametrize(
    "bad_slug",
    ["../etc/passwd", "foo/bar", "FOO", "foo_bar", "", "foo bar"],
)
def test_invalid_dataset_slug_rejected_before_filesystem_access(fake_repo, bad_slug):
    with pytest.raises(ValueError):
        create_draft(bad_slug, _profile(dataset_slug=bad_slug), repo_root=fake_repo)

    with pytest.raises(ValueError):
        get_draft(bad_slug, repo_root=fake_repo)

    with pytest.raises(ValueError):
        update_draft(bad_slug, _profile(dataset_slug=bad_slug), repo_root=fake_repo)


def test_release_artifacts_not_modified_by_draft_persistence(fake_repo):
    metrics_path = fake_repo / "releases" / "release-20260101-001" / "metrics" / "metrics.json"
    before = metrics_path.read_text(encoding="utf-8")

    create_draft("telco-customer-churn", _profile(), repo_root=fake_repo)
    update_draft(
        "telco-customer-churn",
        _profile(display={"title": "Updated Title"}),
        repo_root=fake_repo,
    )

    after = metrics_path.read_text(encoding="utf-8")
    assert before == after
