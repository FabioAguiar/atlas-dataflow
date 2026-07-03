"""
Dataset published profile snapshot store tests for M36-03.

Verifies publish_snapshot and get_snapshot against an isolated fake
repository root (pytest tmp_path), so no test writes into the real
registry/profile-snapshots/ location or any other real repository path.
The real contracts/dataset-public-profile.schema.json and
contracts/dataset-public-profile-snapshot.schema.json are copied into the
fake repo root so schema validation exercises the real schemas, not a
hand-authored replica.

Run from the repository root:
    python -m pytest tests/registry/test_dataset_public_profile_snapshot_store.py -v
"""

import json
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from registry.dataset_public_profile_store import create_draft, update_draft  # noqa: E402
from registry.dataset_public_profile_snapshot_store import (  # noqa: E402
    SnapshotNotFoundError,
    get_snapshot,
    publish_snapshot,
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
                "summary": "Test dataset for snapshot store tests.",
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


def _metrics_path(fake_repo: Path) -> Path:
    return fake_repo / "releases" / "release-20260101-001" / "metrics" / "metrics.json"


def _write_datasets_registry(fake_repo: Path, registry: dict) -> None:
    (fake_repo / "registry" / "datasets.json").write_text(
        json.dumps(registry), encoding="utf-8"
    )


def _write_predict_views_registry(fake_repo: Path, registry: dict) -> None:
    (fake_repo / "registry" / "predict-views.json").write_text(
        json.dumps(registry), encoding="utf-8"
    )


@pytest.fixture
def fake_repo(tmp_path):
    contracts_dir = tmp_path / "contracts"
    contracts_dir.mkdir()
    shutil.copy2(
        REPO_ROOT / "contracts" / "dataset-public-profile.schema.json",
        contracts_dir / "dataset-public-profile.schema.json",
    )
    shutil.copy2(
        REPO_ROOT / "contracts" / "dataset-public-profile-snapshot.schema.json",
        contracts_dir / "dataset-public-profile-snapshot.schema.json",
    )

    registry_dir = tmp_path / "registry"
    registry_dir.mkdir()
    _write_predict_views_registry(tmp_path, _MOCK_PREDICT_VIEWS_REGISTRY)
    _write_datasets_registry(tmp_path, _MOCK_DATASETS_REGISTRY)

    metrics_dir = tmp_path / "releases" / "release-20260101-001" / "metrics"
    metrics_dir.mkdir(parents=True)
    metrics_dir.joinpath("metrics.json").write_text(
        json.dumps(_MOCK_RELEASE_METRICS), encoding="utf-8"
    )

    return tmp_path


def test_publish_rejects_when_no_draft_exists(fake_repo):
    result = publish_snapshot("telco-customer-churn", repo_root=fake_repo)

    assert result["published"] is False
    assert result["snapshot"] is None
    assert "NO_DRAFT_TO_PUBLISH" in _codes(result)
    snapshot_path = fake_repo / "registry" / "profile-snapshots" / "telco-customer-churn.json"
    assert not snapshot_path.exists()


def test_publish_creates_deterministic_snapshot_file(fake_repo):
    create_draft(
        "telco-customer-churn",
        _profile(display={"title": "Churn Risk"}, home_card={"primary_metric_key": "auc_roc"}),
        repo_root=fake_repo,
    )

    result = publish_snapshot("telco-customer-churn", repo_root=fake_repo)

    assert result["published"] is True
    assert result["errors"] == []
    snapshot_path = fake_repo / "registry" / "profile-snapshots" / "telco-customer-churn.json"
    assert snapshot_path.is_file()

    persisted = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert persisted["dataset_slug"] == "telco-customer-churn"
    assert persisted["active_release_at_publish_time"] == "release-20260101-001"
    assert persisted["profile"]["display"]["title"] == "Churn Risk"
    assert persisted["profile"]["home_card"]["primary_metric_key"] == "auc_roc"
    assert "contract" not in persisted
    assert "metrics" not in persisted


def test_publish_replace_creates_previous_backup_and_replaces_content(fake_repo):
    create_draft(
        "telco-customer-churn", _profile(display={"title": "First Title"}), repo_root=fake_repo
    )
    first = publish_snapshot("telco-customer-churn", repo_root=fake_repo)
    assert first["published"] is True

    update_draft(
        "telco-customer-churn", _profile(display={"title": "Second Title"}), repo_root=fake_repo
    )
    second = publish_snapshot("telco-customer-churn", repo_root=fake_repo)
    assert second["published"] is True

    snapshot_path = fake_repo / "registry" / "profile-snapshots" / "telco-customer-churn.json"
    backup_path = fake_repo / "registry" / "profile-snapshots" / "telco-customer-churn.json.previous"
    assert backup_path.is_file()

    backup = json.loads(backup_path.read_text(encoding="utf-8"))
    current = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert backup["profile"]["display"]["title"] == "First Title"
    assert current["profile"]["display"]["title"] == "Second Title"


def test_publish_rejects_when_no_active_release_registered(fake_repo):
    registry_without_active_release = {
        "schema_version": "atlas.dataflow.registry.v1",
        "datasets": [
            {
                "dataset_slug": "telco-customer-churn",
                "public_metadata": {
                    "title": "Telco Customer Churn",
                    "summary": "No active release.",
                    "domain": "telco",
                    "visibility": "public",
                    "tags": ["telco"],
                },
            },
        ],
    }
    _write_datasets_registry(fake_repo, registry_without_active_release)
    create_draft("telco-customer-churn", _profile(), repo_root=fake_repo)

    result = publish_snapshot("telco-customer-churn", repo_root=fake_repo)

    assert result["published"] is False
    assert "ACTIVE_RELEASE_NOT_FOUND" in _codes(result)
    snapshot_path = fake_repo / "registry" / "profile-snapshots" / "telco-customer-churn.json"
    assert not snapshot_path.exists()


def test_publish_rejects_when_bound_predict_view_removed_before_publish(fake_repo):
    """A draft that was valid at save time can be invalidated by registry
    drift before publish. get_draft (registry/dataset_public_profile_store.py,
    out of scope for this issue) re-validates on every read and treats a
    since-invalidated draft identically to a missing one -- by its own
    documented contract, "a missing draft file and a draft file that fails
    schema or reference validation are both treated as one deterministic
    absence condition." So publish_snapshot correctly reports
    NO_DRAFT_TO_PUBLISH here rather than the more specific
    BOUND_PREDICT_VIEW_NOT_FOUND reference error; either way, no snapshot
    is created from a draft whose references no longer resolve.
    """
    create_draft(
        "telco-customer-churn",
        _profile(inference_presentation={"bound_predict_view_id": "churn-risk-overview"}),
        repo_root=fake_repo,
    )

    _write_predict_views_registry(
        fake_repo, {"schema_version": "atlas.dataflow.predict-views.v1", "predict_views": []}
    )

    result = publish_snapshot("telco-customer-churn", repo_root=fake_repo)

    assert result["published"] is False
    assert "NO_DRAFT_TO_PUBLISH" in _codes(result)
    snapshot_path = fake_repo / "registry" / "profile-snapshots" / "telco-customer-churn.json"
    assert not snapshot_path.exists()


def test_publish_rejects_when_primary_metric_key_removed_before_publish(fake_repo):
    """See test_publish_rejects_when_bound_predict_view_removed_before_publish
    for why NO_DRAFT_TO_PUBLISH, not PRIMARY_METRIC_KEY_NOT_FOUND, is the
    observable code: get_draft's own revalidation-on-read already blocks
    a since-invalidated draft before publish_snapshot's own reference
    check would otherwise run.
    """
    create_draft(
        "telco-customer-churn",
        _profile(home_card={"primary_metric_key": "auc_roc"}),
        repo_root=fake_repo,
    )

    metrics_without_auc = {
        "schema_version": "metrics.v1",
        "dataset_slug": "telco-customer-churn",
        "release_id": "release-20260101-001",
        "evaluation": {"split": "test", "sample_size": 1000, "metrics": {"accuracy": 0.9}},
    }
    _metrics_path(fake_repo).write_text(json.dumps(metrics_without_auc), encoding="utf-8")

    result = publish_snapshot("telco-customer-churn", repo_root=fake_repo)

    assert result["published"] is False
    assert "NO_DRAFT_TO_PUBLISH" in _codes(result)
    snapshot_path = fake_repo / "registry" / "profile-snapshots" / "telco-customer-churn.json"
    assert not snapshot_path.exists()


def test_release_artifacts_not_modified_by_publish(fake_repo):
    before = _metrics_path(fake_repo).read_text(encoding="utf-8")

    create_draft("telco-customer-churn", _profile(), repo_root=fake_repo)
    publish_snapshot("telco-customer-churn", repo_root=fake_repo)

    after = _metrics_path(fake_repo).read_text(encoding="utf-8")
    assert before == after


def test_get_snapshot_returns_published_content(fake_repo):
    create_draft(
        "telco-customer-churn", _profile(display={"title": "Churn Risk"}), repo_root=fake_repo
    )
    publish_snapshot("telco-customer-churn", repo_root=fake_repo)

    snapshot = get_snapshot("telco-customer-churn", repo_root=fake_repo)

    assert snapshot["dataset_slug"] == "telco-customer-churn"
    assert snapshot["profile"]["display"]["title"] == "Churn Risk"


def test_get_snapshot_missing_raises_not_found(fake_repo):
    with pytest.raises(SnapshotNotFoundError):
        get_snapshot("telco-customer-churn", repo_root=fake_repo)


@pytest.mark.parametrize(
    "bad_slug",
    ["../etc/passwd", "foo/bar", "FOO", "foo_bar", "", "foo bar"],
)
def test_invalid_dataset_slug_rejected_before_filesystem_access(fake_repo, bad_slug):
    with pytest.raises(ValueError):
        publish_snapshot(bad_slug, repo_root=fake_repo)

    with pytest.raises(ValueError):
        get_snapshot(bad_slug, repo_root=fake_repo)
