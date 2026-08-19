"""
Dataset published profile snapshot store tests for M36-03/M36-04.

Verifies publish_snapshot and get_snapshot against an isolated fake
repository root (pytest tmp_path), so no test writes into the real
registry/profile-snapshots/ location or any other real repository path.
The real contracts/dataset-public-profile.schema.json,
contracts/dataset-public-profile-snapshot.schema.json, and
registry/evidence/dataset-public-profile-snapshot-evidence.schema.json are
copied into the fake repo root so schema validation exercises the real
schemas, not a hand-authored replica.

Also verifies (M36-04) that a successful publish writes a reduced
traceability evidence file alongside the snapshot, and that a rejected
publish creates or replaces neither the snapshot nor the evidence file.

Run from the repository root:
    python -m pytest tests/registry/test_dataset_public_profile_snapshot_store.py -v
"""

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from registry.dataset_public_profile_store import create_draft, update_draft  # noqa: E402
from registry.dataset_public_profile_snapshot_store import (  # noqa: E402
    SnapshotNotFoundError,
    get_snapshot,
    publish_snapshot,
    publish_snapshot_from_payload,
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


def _set_active_release(fake_repo: Path, release_id: str) -> None:
    registry = json.loads(json.dumps(_MOCK_DATASETS_REGISTRY))
    registry["datasets"][0]["active_release"] = release_id
    _write_datasets_registry(fake_repo, registry)


def _write_predict_views_registry(fake_repo: Path, registry: dict) -> None:
    (fake_repo / "registry" / "predict-views.json").write_text(
        json.dumps(registry), encoding="utf-8"
    )


def _evidence_path(fake_repo: Path, dataset_slug: str) -> Path:
    return fake_repo / "registry" / "profile-snapshots" / f"{dataset_slug}.evidence.json"


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
    evidence_schema_dir = registry_dir / "evidence"
    evidence_schema_dir.mkdir()
    shutil.copy2(
        REPO_ROOT / "registry" / "evidence" / "dataset-public-profile-snapshot-evidence.schema.json",
        evidence_schema_dir / "dataset-public-profile-snapshot-evidence.schema.json",
    )
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
    assert not _evidence_path(fake_repo, "telco-customer-churn").exists()


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


def test_publish_canonicalizes_legacy_result_card_and_omits_legacy_keys(fake_repo):
    legacy = _profile(result_card={
        "probability_label": "Event probability",
        "model_label": "Model details",
        "badge_preset": "risk",
        "badge_labels": {"high": "High risk", "medium": "Medium risk", "low": "Low risk"},
    })
    result = publish_snapshot_from_payload(
        "telco-customer-churn", legacy, repo_root=fake_repo
    )
    assert result["published"] is True
    card = result["snapshot"]["profile"]["result_card"]
    assert card["schema_version"] == "binary-result-presentation.v1"
    assert card["positive_class_probability_label"] == "Event probability"
    assert card["model_section_label"] == "Model details"
    assert not ({"probability_label", "model_label", "badge_preset", "badge_labels", "submit_button_label"} & card.keys())


def test_publish_preserves_multiclass_result_presentation(fake_repo):
    profile = _profile(result_card={
        "schema_version": "multiclass-result-presentation.v1",
        "predicted_class_label": "Predicted class",
        "class_probability_distribution_label": "Class probability distribution",
        "model_section_label": "Model",
    })
    result = publish_snapshot_from_payload("telco-customer-churn", profile, repo_root=fake_repo)
    assert result["published"] is True
    assert result["snapshot"]["profile"]["result_card"] == profile["result_card"]


def test_publish_preserves_continuous_regression_result_presentation(fake_repo):
    profile = _profile(result_card={
        "schema_version": "continuous-regression-result-presentation.v1",
        "predicted_value_label": "Predicted compressive strength",
        "model_section_label": "Model",
        "decimal_places": 2,
        "value_unit_label": "MPa",
    })
    result = publish_snapshot_from_payload("telco-customer-churn", profile, repo_root=fake_repo)
    assert result["published"] is True
    assert result["snapshot"]["profile"]["result_card"] == profile["result_card"]


def test_publish_bounds_continuous_regression_decimal_places(fake_repo):
    profile = _profile(result_card={
        "schema_version": "continuous-regression-result-presentation.v1",
        "predicted_value_label": "Predicted value",
        "model_section_label": "Model",
        "decimal_places": 7,
    })
    result = publish_snapshot_from_payload("telco-customer-churn", profile, repo_root=fake_repo)
    assert result["published"] is False
    assert "SCHEMA_VALIDATION_ERROR" in _codes(result)


def test_publish_blocks_dropping_unmigrated_legacy_submit_copy(fake_repo):
    profile = _profile(
        inference_presentation={"bound_predict_view_id": "churn-risk-overview"},
        result_card={"submit_button_label": "Run prediction"},
    )
    blocked = publish_snapshot_from_payload(
        "telco-customer-churn", profile, repo_root=fake_repo
    )
    assert blocked["published"] is False
    assert "LEGACY_SUBMIT_COPY_MIGRATION_REQUIRED" in _codes(blocked)

    (fake_repo / "registry" / "predict-view-customizations.json").write_text(
        json.dumps({
            "predict_view_customizations": [{
                "dataset_slug": "telco-customer-churn",
                "view_id": "churn-risk-overview",
                "view_copy": {"submit_button_label": "Run prediction"},
            }]
        }),
        encoding="utf-8",
    )
    published = publish_snapshot_from_payload(
        "telco-customer-churn", profile, repo_root=fake_repo
    )
    assert published["published"] is True
    assert "submit_button_label" not in published["snapshot"]["profile"]["result_card"]


@pytest.mark.parametrize(
    "release_id",
    ["release-20260101-001", "release-20260712t190939z"],
)
def test_publish_accepts_and_preserves_supported_release_id_formats(fake_repo, release_id):
    _set_active_release(fake_repo, release_id)

    result = publish_snapshot_from_payload(
        "telco-customer-churn", _profile(), repo_root=fake_repo
    )

    assert result["published"] is True
    assert result["snapshot"]["active_release_at_publish_time"] == release_id
    evidence = json.loads(
        _evidence_path(fake_repo, "telco-customer-churn").read_text(encoding="utf-8")
    )
    assert evidence["active_release_at_publish_time"] == release_id


@pytest.mark.parametrize(
    "release_id",
    [
        "",
        "release-latest",
        "release-20260712T190939Z",
        "release-20260712t190939z-extra",
        "prefix-release-20260101-001",
        "../release-20260101-001",
        "https://example.com/release-20260101-001",
    ],
)
def test_publish_rejects_malformed_release_ids(fake_repo, release_id):
    _set_active_release(fake_repo, release_id)

    result = publish_snapshot_from_payload(
        "telco-customer-churn", _profile(), repo_root=fake_repo
    )

    assert result["published"] is False
    expected_code = "ACTIVE_RELEASE_NOT_FOUND" if release_id == "" else "SCHEMA_VALIDATION_ERROR"
    assert expected_code in _codes(result)
    assert not _evidence_path(fake_repo, "telco-customer-churn").exists()


@pytest.mark.parametrize("icon", ["money-dollar", "globe", "flask", "cpu-chip"])
def test_direct_publish_persists_new_home_card_icons(fake_repo, icon):
    home_card = {
        "icon": icon,
        "background_image_ref": "/media/home-cards/churn.webp",
        "short_description": "Published card copy",
    }
    result = publish_snapshot_from_payload(
        "telco-customer-churn", _profile(home_card=home_card), repo_root=fake_repo
    )

    assert result["published"] is True
    assert result["snapshot"]["profile"]["home_card"] == home_card


def test_direct_publish_persists_existing_home_card_presentation_fields(fake_repo):
    home_card = {"icon": "weather-cloud", "short_description": "Published card copy"}
    result = publish_snapshot_from_payload(
        "telco-customer-churn", _profile(home_card=home_card), repo_root=fake_repo
    )

    assert result["published"] is True
    assert result["snapshot"]["profile"]["home_card"] == home_card


def test_direct_publish_persists_valid_performance_focus(fake_repo):
    performance_focus = {
        "focus_id": "positive_class_detection",
        "highlighted_score_id": "recall",
        "visible_scores": [
            {"score_id": "precision", "display_label": "Precision", "value": "0.679", "value_source": "canonical", "order": 1},
            {"score_id": "recall", "display_label": "Recall", "value": "57.4%", "value_source": "manual", "order": 0},
        ],
    }
    result = publish_snapshot_from_payload(
        "telco-customer-churn", _profile(performance_focus=performance_focus), repo_root=fake_repo
    )
    assert result["published"] is True
    assert result["snapshot"]["profile"]["performance_focus"] == performance_focus


def test_invalid_performance_focus_does_not_replace_previous_snapshot(fake_repo):
    valid = publish_snapshot_from_payload(
        "telco-customer-churn", _profile(display={"title": "Previous"}), repo_root=fake_repo
    )
    snapshot_path = fake_repo / "registry" / "profile-snapshots" / "telco-customer-churn.json"
    original = snapshot_path.read_text(encoding="utf-8")
    invalid_focus = {
        "focus_id": "positive_class_detection",
        "highlighted_score_id": "precision",
        "visible_scores": [
            {"score_id": "recall", "display_label": "Recall", "value": "0.5", "value_source": "manual", "order": 0},
        ],
    }
    rejected = publish_snapshot_from_payload(
        "telco-customer-churn", _profile(performance_focus=invalid_focus), repo_root=fake_repo
    )
    assert valid["published"] is True
    assert rejected["published"] is False
    assert "PERFORMANCE_HIGHLIGHT_NOT_VISIBLE" in _codes(rejected)
    assert snapshot_path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("unsafe_value", ["", "not measured", "<script>", "0.5\nprivate"])
def test_direct_publish_rejects_unsafe_performance_values(fake_repo, unsafe_value):
    result = publish_snapshot_from_payload(
        "telco-customer-churn",
        _profile(performance_focus={
            "focus_id": "positive_class_detection",
            "highlighted_score_id": "recall",
            "visible_scores": [{
                "score_id": "recall", "display_label": "Recall", "value": unsafe_value,
                "value_source": "manual", "order": 0,
            }],
        }),
        repo_root=fake_repo,
    )
    assert result["published"] is False
    assert "SCHEMA_VALIDATION_ERROR" in _codes(result)


@pytest.mark.parametrize(
    "unsafe_reference",
    ["/etc/passwd", "../private.png", "file:///tmp/card.png", "https://private.example/card.png", "/media/../private.png"],
)
def test_direct_publish_rejects_unsafe_home_card_media_references(fake_repo, unsafe_reference):
    result = publish_snapshot_from_payload(
        "telco-customer-churn",
        _profile(home_card={"background_image_ref": unsafe_reference}),
        repo_root=fake_repo,
    )

    assert result["published"] is False
    assert "SCHEMA_VALIDATION_ERROR" in _codes(result)


def test_direct_publish_replaces_canonical_local_date_and_drops_legacy_mode(fake_repo, monkeypatch):
    registry = json.loads((fake_repo / "registry" / "datasets.json").read_text(encoding="utf-8"))
    registry["datasets"][0]["dataset_detail_updated_at"] = "2026-07-13T10:39:32Z"
    _write_datasets_registry(fake_repo, registry)
    monkeypatch.setenv("TZ", "America/Recife")

    result = publish_snapshot_from_payload(
        "telco-customer-churn",
        _profile(display={"release_date_label": "2026-07-10", "release_date_mode": "manual"}),
        repo_root=fake_repo,
    )

    assert result["published"] is True
    assert result["snapshot"]["profile"]["display"] == {"release_date_label": "2026-07-10"}
    registry = json.loads((fake_repo / "registry" / "datasets.json").read_text(encoding="utf-8"))
    assert registry["datasets"][0]["dataset_detail_updated_at"] == "2026-07-10T10:39:32Z"


def test_direct_publish_without_canonical_timestamp_uses_backend_time_of_day(fake_repo, monkeypatch):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 7, 13, 0, 41, 21, tzinfo=timezone.utc)

    monkeypatch.setenv("TZ", "America/Recife")
    monkeypatch.setattr("registry.dataset_public_profile_snapshot_store.datetime", FixedDateTime)
    result = publish_snapshot_from_payload(
        "telco-customer-churn",
        _profile(display={"release_date_label": "2026-07-10"}),
        repo_root=fake_repo,
    )

    assert result["published"] is True
    registry = json.loads((fake_repo / "registry" / "datasets.json").read_text(encoding="utf-8"))
    assert registry["datasets"][0]["dataset_detail_updated_at"] == "2026-07-11T00:41:21Z"


def test_invalid_release_date_cannot_replace_snapshot(fake_repo):
    valid = publish_snapshot_from_payload(
        "telco-customer-churn",
        _profile(display={"release_date_label": "2026-05-12", "release_date_mode": "auto"}),
        repo_root=fake_repo,
    )
    snapshot_path = fake_repo / "registry" / "profile-snapshots" / "telco-customer-churn.json"
    original = snapshot_path.read_text(encoding="utf-8")

    rejected = publish_snapshot_from_payload(
        "telco-customer-churn",
        _profile(display={"release_date_label": "2026-02-30", "release_date_mode": "manual"}),
        repo_root=fake_repo,
    )

    assert valid["published"] is True
    assert rejected["published"] is False
    assert "RELEASE_DATE_INVALID" in _codes(rejected)
    assert snapshot_path.read_text(encoding="utf-8") == original


def test_invalid_timezone_cannot_mutate_canonical_timestamp_or_replace_snapshot(fake_repo):
    first = publish_snapshot_from_payload(
        "telco-customer-churn",
        _profile(display={"release_date_label": "2026-05-12"}),
        repo_root=fake_repo,
        time_zone="America/Recife",
    )
    snapshot_path = fake_repo / "registry" / "profile-snapshots" / "telco-customer-churn.json"
    original_snapshot = snapshot_path.read_text(encoding="utf-8")
    original_registry = (fake_repo / "registry" / "datasets.json").read_text(encoding="utf-8")

    rejected = publish_snapshot_from_payload(
        "telco-customer-churn",
        _profile(display={"release_date_label": "2026-06-20"}),
        repo_root=fake_repo,
        time_zone="Not/A-Timezone",
    )

    assert first["published"] is True
    assert rejected["published"] is False
    assert "DATASET_DETAIL_TIMEZONE_INVALID" in _codes(rejected)
    assert snapshot_path.read_text(encoding="utf-8") == original_snapshot
    assert (fake_repo / "registry" / "datasets.json").read_text(encoding="utf-8") == original_registry


def test_failed_operational_timestamp_update_does_not_replace_snapshot(fake_repo, monkeypatch):
    first = publish_snapshot_from_payload(
        "telco-customer-churn",
        _profile(display={"release_date_label": "2026-05-12", "release_date_mode": "manual"}),
        repo_root=fake_repo,
    )
    snapshot_path = fake_repo / "registry" / "profile-snapshots" / "telco-customer-churn.json"
    original = snapshot_path.read_text(encoding="utf-8")

    monkeypatch.setattr(
        "registry.dataset_public_profile_snapshot_store.update_dataset_detail_timestamp",
        lambda *args, **kwargs: {"updated": False, "errors": [{"code": "write_failed"}]},
    )
    rejected = publish_snapshot_from_payload(
        "telco-customer-churn",
        _profile(display={"release_date_label": "2026-06-20", "release_date_mode": "manual"}),
        repo_root=fake_repo,
    )

    assert first["published"] is True
    assert rejected["published"] is False
    assert "DATASET_DETAIL_TIMESTAMP_UPDATE_FAILED" in _codes(rejected)
    assert snapshot_path.read_text(encoding="utf-8") == original


def test_publish_writes_traceability_evidence_alongside_snapshot(fake_repo):
    create_draft(
        "telco-customer-churn",
        _profile(display={"title": "Churn Risk"}),
        repo_root=fake_repo,
    )

    result = publish_snapshot("telco-customer-churn", repo_root=fake_repo)
    assert result["published"] is True

    evidence_path = _evidence_path(fake_repo, "telco-customer-churn")
    assert evidence_path.is_file()

    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["dataset_slug"] == "telco-customer-churn"
    assert evidence["published_at"] == result["snapshot"]["published_at"]
    assert evidence["active_release_at_publish_time"] == "release-20260101-001"
    assert evidence["snapshot_identifier"] == (
        f"telco-customer-churn@{result['snapshot']['published_at']}"
    )
    assert evidence["draft_source_reference"]["path"] == (
        "registry/profile-drafts/telco-customer-churn.json"
    )
    assert evidence["candidate_validation"]["validation_outcome"] == "accepted"
    assert evidence["candidate_validation"]["errors"] == []
    assert evidence["visibility_at_publish_time"]["value"] == "public"
    assert evidence["visibility_at_publish_time"]["read_only_snapshot"] is True
    assert evidence["evidence_safety"]["raw_logs_persisted"] is False
    assert evidence["evidence_safety"]["secrets_persisted"] is False


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

    evidence_path = _evidence_path(fake_repo, "telco-customer-churn")
    assert evidence_path.is_file()
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["published_at"] == second["snapshot"]["published_at"]
    assert evidence["snapshot_identifier"] == (
        f"telco-customer-churn@{second['snapshot']['published_at']}"
    )


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
    assert not _evidence_path(fake_repo, "telco-customer-churn").exists()


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
    assert not _evidence_path(fake_repo, "telco-customer-churn").exists()


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
    assert not _evidence_path(fake_repo, "telco-customer-churn").exists()


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


def test_direct_publish_preserves_exact_documentation_markdown_source(fake_repo):
    documentation = {"format": "markdown", "content": "# Heading\n\nBody text with **bold**."}
    result = publish_snapshot_from_payload(
        "telco-customer-churn", _profile(documentation=documentation), repo_root=fake_repo
    )

    assert result["published"] is True
    assert result["snapshot"]["profile"]["documentation"] == documentation

    snapshot_path = fake_repo / "registry" / "profile-snapshots" / "telco-customer-churn.json"
    persisted = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert persisted["profile"]["documentation"] == documentation


def test_legacy_publish_snapshot_preserves_documentation(fake_repo):
    documentation = {"format": "markdown", "content": "## Draft-sourced heading"}
    create_draft(
        "telco-customer-churn", _profile(documentation=documentation), repo_root=fake_repo
    )

    result = publish_snapshot("telco-customer-churn", repo_root=fake_repo)

    assert result["published"] is True
    assert result["snapshot"]["profile"]["documentation"] == documentation


def test_profile_without_documentation_remains_valid_and_omits_field(fake_repo):
    result = publish_snapshot_from_payload(
        "telco-customer-churn", _profile(display={"title": "No docs"}), repo_root=fake_repo
    )

    assert result["published"] is True
    assert "documentation" not in result["snapshot"]["profile"]


def test_invalid_documentation_rejected_by_existing_schema_validation(fake_repo):
    result = publish_snapshot_from_payload(
        "telco-customer-churn",
        _profile(documentation={"format": "markdown", "content": "ok", "unexpected": "field"}),
        repo_root=fake_repo,
    )

    assert result["published"] is False
    assert "SCHEMA_VALIDATION_ERROR" in _codes(result)


def test_documentation_backup_previous_snapshot_retains_prior_documentation(fake_repo):
    first_documentation = {"format": "markdown", "content": "First published documentation."}
    first = publish_snapshot_from_payload(
        "telco-customer-churn", _profile(documentation=first_documentation), repo_root=fake_repo
    )
    assert first["published"] is True

    second_documentation = {"format": "markdown", "content": "Second published documentation."}
    second = publish_snapshot_from_payload(
        "telco-customer-churn", _profile(documentation=second_documentation), repo_root=fake_repo
    )
    assert second["published"] is True

    backup_path = fake_repo / "registry" / "profile-snapshots" / "telco-customer-churn.json.previous"
    backup = json.loads(backup_path.read_text(encoding="utf-8"))
    assert backup["profile"]["documentation"] == first_documentation

    snapshot_path = fake_repo / "registry" / "profile-snapshots" / "telco-customer-churn.json"
    current = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert current["profile"]["documentation"] == second_documentation


def test_no_unrelated_request_only_field_is_promoted_into_snapshot_profile(fake_repo):
    result = publish_snapshot_from_payload(
        "telco-customer-churn",
        _profile(
            documentation={"format": "markdown", "content": "Bounded profile check."},
            _example_note="should-not-appear",
        ),
        repo_root=fake_repo,
    )

    assert result["published"] is True
    assert "_example_note" not in result["snapshot"]["profile"]
