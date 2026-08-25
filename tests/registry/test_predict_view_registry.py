"""
Predict view registry validation tests for M18-02.

Verifies that the binding validator accepts valid predict view registry content
and rejects invalid dataset references, invalid release references, and
incompatible contract bindings with predictable, deterministic errors.

Run from the repository root:
    python -m pytest tests/registry/test_predict_view_registry.py -v
or directly:
    python tests/registry/test_predict_view_registry.py
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from registry.predict_view_validate import (  # noqa: E402
    validate_predict_views,
    validate_predict_views_file,
)
from registry.update import MODE_CREATE_NEW_DATASET_DETAIL, run as registry_update_run  # noqa: E402

VALID_DIR = Path(__file__).parent / "predict-views" / "valid"
INVALID_DIR = Path(__file__).parent / "predict-views" / "invalid"
DATASETS_PATH = REPO_ROOT / "registry" / "datasets.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _codes(result: dict) -> set[str]:
    return {e["code"] for e in result["errors"]}


# ---------------------------------------------------------------------------
# Valid fixture
# ---------------------------------------------------------------------------

def test_valid_predict_views_passes():
    registry = _load(VALID_DIR / "predict-views.json")
    result = validate_predict_views(
        registry,
        known_dataset_slugs={record["dataset_slug"] for record in registry["predict_views"]},
    )
    assert result["valid"] is True, f"Expected valid, got errors: {result['errors']}"
    assert result["errors"] == []


# ---------------------------------------------------------------------------
# Invalid fixtures
# ---------------------------------------------------------------------------

def test_invalid_dataset_reference_rejected():
    result = validate_predict_views_file(
        INVALID_DIR / "invalid-dataset-reference.json",
        datasets_path=DATASETS_PATH,
    )
    assert result["valid"] is False
    assert "DATASET_NOT_FOUND" in _codes(result)


def test_invalid_release_reference_rejected():
    registry = _load(INVALID_DIR / "invalid-release-reference.json")
    result = validate_predict_views(
        registry,
        known_dataset_slugs={record["dataset_slug"] for record in registry["predict_views"]},
    )
    assert result["valid"] is False
    assert "RELEASE_REFERENCE_INVALID" in _codes(result)


def test_incompatible_contract_binding_rejected():
    registry = _load(INVALID_DIR / "incompatible-contract-binding.json")
    result = validate_predict_views(
        registry,
        known_dataset_slugs={record["dataset_slug"] for record in registry["predict_views"]},
    )
    assert result["valid"] is False
    assert "CONTRACT_BINDING_INVALID" in _codes(result)


# ---------------------------------------------------------------------------
# Inline semantic checks
# ---------------------------------------------------------------------------

def test_missing_schema_version_rejected():
    result = validate_predict_views({"predict_views": []})
    assert result["valid"] is False
    assert "MISSING_SCHEMA_VERSION" in _codes(result)


def test_invalid_schema_version_rejected():
    result = validate_predict_views(
        {"schema_version": "wrong.version", "predict_views": []}
    )
    assert result["valid"] is False
    assert "INVALID_SCHEMA_VERSION" in _codes(result)


def test_compatible_mode_with_valid_release_id_passes():
    result = validate_predict_views(
        {
            "schema_version": "atlas.dataflow.predict-views.v1",
            "predict_views": [
                {
                    "schema_version": "1.0.0",
                    "view_id": "test-compatible-view",
                    "dataset_slug": "telco-customer-churn",
                    "display": {"title": "T", "summary": "S"},
                    "intent": {
                        "prediction_goal": "G",
                        "audience": "A",
                        "usage_notes": "N",
                    },
                    "binding": {
                        "dataset_slug": "telco-customer-churn",
                        "release": {
                            "mode": "compatible",
                            "release_id": "release-20260619-001",
                        },
                    },
                    "contract_precedence": {
                        "canonical_contracts_are_source_of_truth": True,
                        "view_metadata_defines_runtime_validation": False,
                        "view_metadata_duplicates_contract": False,
                    },
                }
            ],
        },
        known_dataset_slugs={"telco-customer-churn"},
    )
    assert result["valid"] is True, f"Expected valid, got errors: {result['errors']}"


def test_active_mode_with_release_id_rejected():
    result = validate_predict_views(
        {
            "schema_version": "atlas.dataflow.predict-views.v1",
            "predict_views": [
                {
                    "schema_version": "1.0.0",
                    "view_id": "test-active-with-release-id",
                    "dataset_slug": "telco-customer-churn",
                    "display": {"title": "T", "summary": "S"},
                    "intent": {
                        "prediction_goal": "G",
                        "audience": "A",
                        "usage_notes": "N",
                    },
                    "binding": {
                        "dataset_slug": "telco-customer-churn",
                        "release": {
                            "mode": "active",
                            "release_id": "release-20260619-001",
                        },
                    },
                    "contract_precedence": {
                        "canonical_contracts_are_source_of_truth": True,
                        "view_metadata_defines_runtime_validation": False,
                        "view_metadata_duplicates_contract": False,
                    },
                }
            ],
        },
        known_dataset_slugs={"telco-customer-churn"},
    )
    assert result["valid"] is False
    assert "RELEASE_REFERENCE_INVALID" in _codes(result)


def test_contract_precedence_violation_rejected():
    result = validate_predict_views(
        {
            "schema_version": "atlas.dataflow.predict-views.v1",
            "predict_views": [
                {
                    "schema_version": "1.0.0",
                    "view_id": "test-precedence-violation",
                    "dataset_slug": "telco-customer-churn",
                    "display": {"title": "T", "summary": "S"},
                    "intent": {
                        "prediction_goal": "G",
                        "audience": "A",
                        "usage_notes": "N",
                    },
                    "binding": {
                        "dataset_slug": "telco-customer-churn",
                        "release": {"mode": "active"},
                    },
                    "contract_precedence": {
                        "canonical_contracts_are_source_of_truth": False,
                        "view_metadata_defines_runtime_validation": False,
                        "view_metadata_duplicates_contract": False,
                    },
                }
            ],
        },
        known_dataset_slugs={"telco-customer-churn"},
    )
    assert result["valid"] is False
    assert "CONTRACT_PRECEDENCE_VIOLATION" in _codes(result)


def test_duplicate_view_id_rejected_within_same_dataset():
    """S0261: uniqueness is (dataset_slug, view_id) -- two records for the
    same dataset declaring the same view_id remain a deterministic rejection."""
    view = {
        "schema_version": "1.0.0",
        "view_id": "duplicate-id",
        "dataset_slug": "telco-customer-churn",
        "display": {"title": "T", "summary": "S"},
        "intent": {"prediction_goal": "G", "audience": "A", "usage_notes": "N"},
        "binding": {
            "dataset_slug": "telco-customer-churn",
            "release": {"mode": "active"},
        },
        "contract_precedence": {
            "canonical_contracts_are_source_of_truth": True,
            "view_metadata_defines_runtime_validation": False,
            "view_metadata_duplicates_contract": False,
        },
    }
    result = validate_predict_views(
        {
            "schema_version": "atlas.dataflow.predict-views.v1",
            "predict_views": [view, {**view}],
        },
        known_dataset_slugs={"telco-customer-churn"},
    )
    assert result["valid"] is False
    assert "DUPLICATE_VIEW_ID" in _codes(result)


def test_same_view_id_across_two_different_datasets_is_valid():
    """S0261: Predict View uniqueness is scoped to (dataset_slug, view_id),
    so the same view_id may legitimately appear under distinct datasets."""
    def _view(dataset_slug: str) -> dict:
        return {
            "schema_version": "1.0.0",
            "view_id": "shared-view",
            "dataset_slug": dataset_slug,
            "display": {"title": "T", "summary": "S"},
            "intent": {"prediction_goal": "G", "audience": "A", "usage_notes": "N"},
            "binding": {
                "dataset_slug": dataset_slug,
                "release": {"mode": "active"},
            },
            "contract_precedence": {
                "canonical_contracts_are_source_of_truth": True,
                "view_metadata_defines_runtime_validation": False,
                "view_metadata_duplicates_contract": False,
            },
        }

    result = validate_predict_views(
        {
            "schema_version": "atlas.dataflow.predict-views.v1",
            "predict_views": [_view("telco-customer-churn"), _view("telco-customer-churn1")],
        },
        known_dataset_slugs={"telco-customer-churn", "telco-customer-churn1"},
    )
    assert result["valid"] is True, f"Expected valid, got errors: {result['errors']}"


def test_registry_discovery_returns_only_valid_views():
    """The production registry file must pass binding validation end-to-end."""
    result = validate_predict_views_file(
        REPO_ROOT / "registry" / "predict-views.json",
        datasets_path=DATASETS_PATH,
    )
    assert result["valid"] is True, f"Production registry invalid: {result['errors']}"


def test_empty_registry_with_no_predict_views_is_valid():
    result = validate_predict_views(
        {"schema_version": "atlas.dataflow.predict-views.v1", "predict_views": []},
        known_dataset_slugs=set(),
    )
    assert result == {"valid": True, "errors": []}


def test_active_orphan_predict_view_remains_invalid():
    registry = _load(VALID_DIR / "predict-views.json")
    result = validate_predict_views(registry, known_dataset_slugs=set())
    assert result["valid"] is False
    assert "DATASET_NOT_FOUND" in _codes(result)


def test_error_messages_contain_no_filesystem_paths():
    """Validation errors must not leak internal filesystem details."""
    registry = _load(INVALID_DIR / "invalid-dataset-reference.json")
    result = validate_predict_views(registry, known_dataset_slugs=set())
    for error in result["errors"]:
        msg = error.get("message", "")
        assert "/internal/" not in msg
        assert "/workspace/" not in msg
        assert "/home/" not in msg


# ---------------------------------------------------------------------------
# registry/update.py predict-view materialization (Project Spec S0098)
# ---------------------------------------------------------------------------

_VIEW_DECLARATION_TEMPLATE = {
    "schema_version": "1.0.0",
    "view_id": "churn-risk-overview",
    "dataset_slug": "telco-customer-churn",
    "display": {"title": "Churn Risk Overview", "summary": "Estimate churn."},
    "intent": {"prediction_goal": "Estimate churn.", "audience": "Public visitors."},
    "binding": {"dataset_slug": "telco-customer-churn", "release": {"mode": "active"}},
    "contract_precedence": {
        "canonical_contracts_are_source_of_truth": True,
        "view_metadata_defines_runtime_validation": False,
        "view_metadata_duplicates_contract": False,
    },
}


def _write_materialization_repo(
    repo_root: Path,
    *,
    dataset_entries: list | None = None,
    existing_predict_views: list | None = None,
) -> None:
    registry_dir = repo_root / "registry"
    registry_dir.mkdir(parents=True, exist_ok=True)
    (registry_dir / "datasets.json").write_text(
        json.dumps({
            "schema_version": "atlas.dataflow.registry.v1",
            "datasets": dataset_entries if dataset_entries is not None else [],
        }),
        encoding="utf-8",
    )
    (registry_dir / "predict-views.json").write_text(
        json.dumps({
            "schema_version": "atlas.dataflow.predict-views.v1",
            "predict_views": existing_predict_views if existing_predict_views is not None else [],
        }),
        encoding="utf-8",
    )
    (registry_dir / "predict-view-customizations.json").write_text(
        json.dumps({
            "schema_version": "atlas.dataflow.predict-view-customizations.v1",
            "predict_view_customizations": [],
        }),
        encoding="utf-8",
    )


def _dataset_entry(slug: str, release_id: str) -> dict:
    return {
        "dataset_slug": slug,
        "active_release": release_id,
        "public_metadata": {
            "title": slug, "summary": "s", "domain": "general", "visibility": "public", "tags": [],
        },
    }


def _write_release(
    repo_root: Path, release_id: str, dataset_slug: str, predict_views,
) -> None:
    release_dir = repo_root / "releases" / release_id
    release_dir.mkdir(parents=True, exist_ok=True)
    public_context = {
        "schema_version": "1.0.0",
        "dataset_slug": dataset_slug,
        "title": "T",
        "description": "D",
        "domain": "general",
    }
    if predict_views is not None:
        public_context["predict_views"] = predict_views
    (release_dir / "public-context.json").write_text(json.dumps(public_context), encoding="utf-8")
    (release_dir / "manifest.json").write_text(json.dumps({"artifacts": []}), encoding="utf-8")


def _write_promotion_run(repo_root: Path, run_id: str, dataset_slug: str, release_id: str) -> Path:
    run_dir = repo_root / "publisher" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "promotion-result.json").write_text(
        json.dumps({
            "promotion_outcome": "promoted",
            "candidate_identity": {"dataset_slug": dataset_slug, "release_id": release_id},
        }),
        encoding="utf-8",
    )
    return run_dir


def _predict_views_of(repo_root: Path) -> dict:
    return _load(repo_root / "registry" / "predict-views.json")


def test_materialize_absent_predict_views_preserves_dataset_owned_subset(tmp_path):
    other_view = {**_VIEW_DECLARATION_TEMPLATE, "view_id": "other-view", "dataset_slug": "other-dataset"}
    other_view["binding"] = {"dataset_slug": "other-dataset", "release": {"mode": "active"}}
    _write_materialization_repo(
        tmp_path,
        dataset_entries=[_dataset_entry("other-dataset", "release-20260101-001")],
        existing_predict_views=[other_view],
    )
    _write_release(tmp_path, "release-20260102-002", "telco-customer-churn", predict_views=None)
    run_dir = _write_promotion_run(tmp_path, "run-absent", "telco-customer-churn", "release-20260102-002")

    result = registry_update_run(str(run_dir), repo_root=tmp_path)

    assert result["predict_view_materialization"] == {"declared_mode": "absent", "action": "not_declared"}
    assert _predict_views_of(tmp_path)["predict_views"] == [other_view]


def test_materialize_populated_declaration_creates_view_and_preserves_other_datasets(tmp_path):
    other_view = {**_VIEW_DECLARATION_TEMPLATE, "view_id": "other-view", "dataset_slug": "other-dataset"}
    other_view["binding"] = {"dataset_slug": "other-dataset", "release": {"mode": "active"}}
    _write_materialization_repo(
        tmp_path,
        dataset_entries=[_dataset_entry("other-dataset", "release-20260101-001")],
        existing_predict_views=[other_view],
    )
    _write_release(
        tmp_path, "release-20260102-003", "telco-customer-churn", predict_views=[_VIEW_DECLARATION_TEMPLATE]
    )
    run_dir = _write_promotion_run(tmp_path, "run-populated", "telco-customer-churn", "release-20260102-003")

    result = registry_update_run(str(run_dir), repo_root=tmp_path)

    assert result["predict_view_materialization"]["action"] == "created"
    views = _predict_views_of(tmp_path)["predict_views"]
    assert {v["view_id"] for v in views} == {"other-view", "churn-risk-overview"}
    assert other_view in views


def test_materialize_is_idempotent_on_repeated_promotion(tmp_path):
    _write_materialization_repo(tmp_path)
    _write_release(
        tmp_path, "release-20260102-004", "telco-customer-churn", predict_views=[_VIEW_DECLARATION_TEMPLATE]
    )
    run_dir = _write_promotion_run(tmp_path, "run-idempotent", "telco-customer-churn", "release-20260102-004")

    registry_update_run(str(run_dir), repo_root=tmp_path)
    predict_views_path = tmp_path / "registry" / "predict-views.json"
    before = predict_views_path.read_bytes()

    result = registry_update_run(str(run_dir), repo_root=tmp_path)

    assert result["predict_view_materialization"]["action"] == "preserved"
    assert predict_views_path.read_bytes() == before


def test_materialize_explicit_empty_removes_only_dataset_owned_subset(tmp_path):
    other_view = {**_VIEW_DECLARATION_TEMPLATE, "view_id": "other-view", "dataset_slug": "other-dataset"}
    other_view["binding"] = {"dataset_slug": "other-dataset", "release": {"mode": "active"}}
    _write_materialization_repo(
        tmp_path,
        dataset_entries=[
            _dataset_entry("other-dataset", "release-20260101-001"),
            _dataset_entry("telco-customer-churn", "release-20260101-999"),
        ],
        existing_predict_views=[other_view, _VIEW_DECLARATION_TEMPLATE],
    )
    _write_release(tmp_path, "release-20260102-005", "telco-customer-churn", predict_views=[])
    run_dir = _write_promotion_run(tmp_path, "run-empty", "telco-customer-churn", "release-20260102-005")

    result = registry_update_run(str(run_dir), repo_root=tmp_path)

    assert result["predict_view_materialization"]["action"] == "removed"
    views = _predict_views_of(tmp_path)["predict_views"]
    assert {v["view_id"] for v in views} == {"other-view"}


def test_materialize_delete_then_repromote_restores_declared_view(tmp_path):
    _write_materialization_repo(tmp_path)
    _write_release(
        tmp_path, "release-20260102-006", "telco-customer-churn", predict_views=[_VIEW_DECLARATION_TEMPLATE]
    )
    run_dir = _write_promotion_run(tmp_path, "run-restore", "telco-customer-churn", "release-20260102-006")
    registry_update_run(str(run_dir), repo_root=tmp_path)
    assert _predict_views_of(tmp_path)["predict_views"] != []

    # Simulate the S0082 Dataset Detail deletion cascade (owned by api/main.py,
    # not registry/update.py): remove this dataset's predict views and its
    # registry entry, leaving the release artifact untouched.
    (tmp_path / "registry" / "predict-views.json").write_text(
        json.dumps({"schema_version": "atlas.dataflow.predict-views.v1", "predict_views": []}),
        encoding="utf-8",
    )
    (tmp_path / "registry" / "datasets.json").write_text(
        json.dumps({"schema_version": "atlas.dataflow.registry.v1", "datasets": []}), encoding="utf-8"
    )

    result = registry_update_run(str(run_dir), repo_root=tmp_path)

    assert result["predict_view_materialization"]["action"] == "created"
    views = _predict_views_of(tmp_path)["predict_views"]
    assert {v["view_id"] for v in views} == {"churn-risk-overview"}


def test_materialize_create_new_dataset_detail_mode_rebinds_to_allocated_slug(tmp_path):
    """S0261: the base dataset already owns the declared view_id, and
    MODE_CREATE_NEW_DATASET_DETAIL still allocates base1 and materializes the
    same stable view_id under it -- both records coexist, each binding its
    own dataset_slug, and the merged registry validates."""
    _write_materialization_repo(
        tmp_path,
        dataset_entries=[_dataset_entry("telco-customer-churn", "release-20260101-999")],
        existing_predict_views=[_VIEW_DECLARATION_TEMPLATE],
    )
    _write_release(
        tmp_path, "release-20260102-007", "telco-customer-churn", predict_views=[_VIEW_DECLARATION_TEMPLATE]
    )
    run_dir = _write_promotion_run(tmp_path, "run-newdetail", "telco-customer-churn", "release-20260102-007")

    result = registry_update_run(str(run_dir), repo_root=tmp_path, mode=MODE_CREATE_NEW_DATASET_DETAIL)

    assert result["allocated_dataset_slug"] == "telco-customer-churn1"
    views = _predict_views_of(tmp_path)["predict_views"]
    matching = [v for v in views if v["view_id"] == "churn-risk-overview"]
    assert {v["dataset_slug"] for v in matching} == {"telco-customer-churn", "telco-customer-churn1"}
    for v in matching:
        assert v["binding"]["dataset_slug"] == v["dataset_slug"]

    validation = validate_predict_views(
        _predict_views_of(tmp_path),
        known_dataset_slugs={"telco-customer-churn", "telco-customer-churn1"},
    )
    assert validation["valid"] is True, f"Expected valid, got errors: {validation['errors']}"


def test_materialize_create_new_dataset_detail_base2_allocation_preserves_same_view_id(tmp_path):
    """S0261: with base and base1 already occupied, a further
    MODE_CREATE_NEW_DATASET_DETAIL promotion allocates base2 and the same
    stable view_id remains legal there too, alongside base/base1."""
    _write_materialization_repo(
        tmp_path,
        dataset_entries=[
            _dataset_entry("telco-customer-churn", "release-20260101-999"),
            _dataset_entry("telco-customer-churn1", "release-20260101-998"),
        ],
        existing_predict_views=[
            _VIEW_DECLARATION_TEMPLATE,
            {
                **_VIEW_DECLARATION_TEMPLATE,
                "dataset_slug": "telco-customer-churn1",
                "binding": {"dataset_slug": "telco-customer-churn1", "release": {"mode": "active"}},
            },
        ],
    )
    _write_release(
        tmp_path, "release-20260102-011", "telco-customer-churn", predict_views=[_VIEW_DECLARATION_TEMPLATE]
    )
    run_dir = _write_promotion_run(tmp_path, "run-newdetail2", "telco-customer-churn", "release-20260102-011")

    result = registry_update_run(str(run_dir), repo_root=tmp_path, mode=MODE_CREATE_NEW_DATASET_DETAIL)

    assert result["allocated_dataset_slug"] == "telco-customer-churn2"
    views = _predict_views_of(tmp_path)["predict_views"]
    matching = [v for v in views if v["view_id"] == "churn-risk-overview"]
    assert {v["dataset_slug"] for v in matching} == {
        "telco-customer-churn", "telco-customer-churn1", "telco-customer-churn2",
    }


def test_materialize_rejects_malformed_declaration_without_any_write(tmp_path):
    _write_materialization_repo(tmp_path)
    _write_release(tmp_path, "release-20260102-008", "telco-customer-churn", predict_views=["not-an-object"])
    run_dir = _write_promotion_run(tmp_path, "run-malformed", "telco-customer-churn", "release-20260102-008")
    datasets_before = (tmp_path / "registry" / "datasets.json").read_bytes()
    predict_views_before = (tmp_path / "registry" / "predict-views.json").read_bytes()

    try:
        registry_update_run(str(run_dir), repo_root=tmp_path)
        raise AssertionError("expected RuntimeError for malformed predict view declaration")
    except RuntimeError:
        pass

    assert (tmp_path / "registry" / "datasets.json").read_bytes() == datasets_before
    assert (tmp_path / "registry" / "predict-views.json").read_bytes() == predict_views_before
    assert not (tmp_path / "registry" / "datasets.json.previous").exists()


def test_materialize_allows_same_view_id_reused_across_different_datasets(tmp_path):
    """S0261: this case is no longer a global-duplicate rejection -- the same
    view_id declared for a different, already-registered dataset is a valid
    cross-dataset reuse, and both dataset-scoped records persist."""
    other_view = {**_VIEW_DECLARATION_TEMPLATE, "dataset_slug": "other-dataset"}
    other_view["binding"] = {"dataset_slug": "other-dataset", "release": {"mode": "active"}}
    _write_materialization_repo(
        tmp_path,
        dataset_entries=[_dataset_entry("other-dataset", "release-20260101-001")],
        existing_predict_views=[other_view],
    )
    reused = {**_VIEW_DECLARATION_TEMPLATE, "view_id": "churn-risk-overview"}
    _write_release(tmp_path, "release-20260102-009", "telco-customer-churn", predict_views=[reused])
    run_dir = _write_promotion_run(tmp_path, "run-reuse", "telco-customer-churn", "release-20260102-009")

    result = registry_update_run(str(run_dir), repo_root=tmp_path)

    assert result["predict_view_materialization"]["action"] == "created"
    views = _predict_views_of(tmp_path)["predict_views"]
    matching = [v for v in views if v["view_id"] == "churn-risk-overview"]
    assert {v["dataset_slug"] for v in matching} == {"other-dataset", "telco-customer-churn"}


def test_materialize_rejects_two_same_view_id_declarations_in_one_promotion_without_any_write(tmp_path):
    """S0261: two identical view_id declarations for the same final Dataset
    Detail must still abort before any registry write -- composite-key
    scoping never permits duplicates within a single dataset's own declared
    predict_views."""
    _write_materialization_repo(tmp_path)
    duplicated = {**_VIEW_DECLARATION_TEMPLATE, "view_id": "churn-risk-overview"}
    _write_release(
        tmp_path, "release-20260102-012", "telco-customer-churn",
        predict_views=[duplicated, {**duplicated}],
    )
    run_dir = _write_promotion_run(tmp_path, "run-samedataset-duplicate", "telco-customer-churn", "release-20260102-012")
    datasets_before = (tmp_path / "registry" / "datasets.json").read_bytes()
    predict_views_before = (tmp_path / "registry" / "predict-views.json").read_bytes()

    try:
        registry_update_run(str(run_dir), repo_root=tmp_path)
        raise AssertionError("expected RuntimeError for same-dataset duplicate view_id")
    except RuntimeError:
        pass

    assert (tmp_path / "registry" / "datasets.json").read_bytes() == datasets_before
    assert (tmp_path / "registry" / "predict-views.json").read_bytes() == predict_views_before


def test_materialize_rejects_cross_dataset_declaration_without_any_write(tmp_path):
    _write_materialization_repo(tmp_path)
    spoofed = {**_VIEW_DECLARATION_TEMPLATE, "dataset_slug": "someone-elses-dataset"}
    _write_release(tmp_path, "release-20260102-010", "telco-customer-churn", predict_views=[spoofed])
    run_dir = _write_promotion_run(tmp_path, "run-spoofed", "telco-customer-churn", "release-20260102-010")
    predict_views_before = (tmp_path / "registry" / "predict-views.json").read_bytes()

    try:
        registry_update_run(str(run_dir), repo_root=tmp_path)
        raise AssertionError("expected RuntimeError for cross-dataset declaration")
    except RuntimeError:
        pass

    assert (tmp_path / "registry" / "predict-views.json").read_bytes() == predict_views_before


def test_no_implementation_logic_hardcodes_churn_risk_overview():
    import inspect

    import registry.update as update_module

    source = inspect.getsource(update_module)
    assert "churn-risk-overview" not in source


# ---------------------------------------------------------------------------
# Project Spec S0218: first-dataset/native-style materialization fixture
# (dry-bean-classification) proving registry/update.py's generic
# materialization logic is not churn-risk-overview-specific.
# ---------------------------------------------------------------------------

_DRY_BEAN_VIEW_DECLARATION_TEMPLATE = {
    "schema_version": "1.0.0",
    "view_id": "dry-bean-classification",
    "dataset_slug": "dry-bean",
    "display": {
        "title": "Dry Bean Classification",
        "summary": "Predict the class of a dry bean sample from its morphological measurements.",
        "description": "A multiclass prediction experience using the governed Dry Bean input contract.",
        "tags": ["dry-bean", "classification", "multiclass"],
    },
    "intent": {
        "prediction_goal": "Predict the bean class from the canonical dataset contract inputs.",
        "audience": "Users exploring Dry Bean multiclass inference.",
        "usage_notes": "Use the canonical dataset contracts for required fields, accepted values, and runtime validation.",
    },
    "binding": {"dataset_slug": "dry-bean", "release": {"mode": "active"}},
    "contract_precedence": {
        "canonical_contracts_are_source_of_truth": True,
        "view_metadata_defines_runtime_validation": False,
        "view_metadata_duplicates_contract": False,
    },
}


def test_materialize_dry_bean_native_predict_view_declaration_end_to_end(tmp_path):
    """Promotion materializes the Dry Bean Predict View from a canonical
    S0218 dataset-context declaration; the view record validates; another
    dataset's already-materialized view is preserved; repeated registry
    update is idempotent; binding stays release-active-bound; and registry
    update alone never creates a customization record."""
    other_view = {**_VIEW_DECLARATION_TEMPLATE, "view_id": "other-view", "dataset_slug": "other-dataset"}
    other_view["binding"] = {"dataset_slug": "other-dataset", "release": {"mode": "active"}}
    _write_materialization_repo(
        tmp_path,
        dataset_entries=[_dataset_entry("other-dataset", "release-20260101-001")],
        existing_predict_views=[other_view],
    )
    _write_release(
        tmp_path, "release-20260818-101", "dry-bean", predict_views=[_DRY_BEAN_VIEW_DECLARATION_TEMPLATE]
    )
    run_dir = _write_promotion_run(tmp_path, "run-dry-bean", "dry-bean", "release-20260818-101")

    result = registry_update_run(str(run_dir), repo_root=tmp_path)

    assert result["predict_view_materialization"]["action"] == "created"
    views = _predict_views_of(tmp_path)["predict_views"]
    assert {v["view_id"] for v in views} == {"other-view", "dry-bean-classification"}
    assert other_view in views
    dry_bean_view = next(v for v in views if v["view_id"] == "dry-bean-classification")
    assert dry_bean_view["binding"] == {"dataset_slug": "dry-bean", "release": {"mode": "active"}}

    validation = validate_predict_views(
        _load(tmp_path / "registry" / "predict-views.json"),
        known_dataset_slugs={"other-dataset", "dry-bean"},
    )
    assert validation["valid"] is True, f"Expected valid, got errors: {validation['errors']}"

    customizations_before = (tmp_path / "registry" / "predict-view-customizations.json").read_bytes()
    predict_views_before = (tmp_path / "registry" / "predict-views.json").read_bytes()

    repeat_result = registry_update_run(str(run_dir), repo_root=tmp_path)

    assert repeat_result["predict_view_materialization"]["action"] == "preserved"
    assert (tmp_path / "registry" / "predict-views.json").read_bytes() == predict_views_before
    assert (tmp_path / "registry" / "predict-view-customizations.json").read_bytes() == customizations_before
    customizations = _load(tmp_path / "registry" / "predict-view-customizations.json")
    assert customizations["predict_view_customizations"] == []


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # The materialization tests above use pytest's tmp_path fixture -- delegate
    # to pytest itself, matching tests/registry/test_registry_validation.py's
    # own standalone-runner convention for the same reason.
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
