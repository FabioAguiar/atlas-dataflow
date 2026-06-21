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
    result = validate_predict_views_file(
        VALID_DIR / "predict-views.json",
        datasets_path=DATASETS_PATH,
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
    result = validate_predict_views_file(
        INVALID_DIR / "invalid-release-reference.json",
        datasets_path=DATASETS_PATH,
    )
    assert result["valid"] is False
    assert "RELEASE_REFERENCE_INVALID" in _codes(result)


def test_incompatible_contract_binding_rejected():
    result = validate_predict_views_file(
        INVALID_DIR / "incompatible-contract-binding.json",
        datasets_path=DATASETS_PATH,
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


def test_duplicate_view_id_rejected():
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


def test_registry_discovery_returns_only_valid_views():
    """The production registry file must pass binding validation end-to-end."""
    result = validate_predict_views_file(
        REPO_ROOT / "registry" / "predict-views.json",
        datasets_path=DATASETS_PATH,
    )
    assert result["valid"] is True, f"Production registry invalid: {result['errors']}"


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
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_valid_predict_views_passes,
        test_invalid_dataset_reference_rejected,
        test_invalid_release_reference_rejected,
        test_incompatible_contract_binding_rejected,
        test_missing_schema_version_rejected,
        test_invalid_schema_version_rejected,
        test_compatible_mode_with_valid_release_id_passes,
        test_active_mode_with_release_id_rejected,
        test_contract_precedence_violation_rejected,
        test_duplicate_view_id_rejected,
        test_registry_discovery_returns_only_valid_views,
        test_error_messages_contain_no_filesystem_paths,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except AssertionError as exc:
            print(f"  FAIL  {t.__name__}: {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
