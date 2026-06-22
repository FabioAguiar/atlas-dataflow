"""
Unit tests for api/public_predict_view_customization_loader.py (M19-03).

Exercises load_public_predict_view_customization using temporary registry
files and monkey-patched validator/contract dependencies. Tests confirm:
  - A valid registry entry with a passing validator is returned correctly.
  - CustomizationNotFoundError is raised when no entry matches the given
    dataset_slug + view_id.
  - CustomizationNotFoundError is raised when the matched entry fails
    validate_customization (treated as absent).
  - The returned dict does not include internal registry metadata.
  - Registry unavailable conditions raise CustomizationNotFoundError.

Run from the repository root:
    python -m pytest tests/api/test_predict_view_customization_loader.py -v
or directly:
    python tests/api/test_predict_view_customization_loader.py
"""

import json
import sys
import tempfile
import types
import unittest.mock as mock
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
API_ROOT = REPO_ROOT / "api"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(API_ROOT))

import public_predict_view_customization_loader as loader_module  # noqa: E402
from public_predict_view_customization_loader import (  # noqa: E402
    CustomizationNotFoundError,
    load_public_predict_view_customization,
)
from registry.predict_view_customization_validate import validate_customization as _real_validate_customization  # noqa: E402

_VALID_CUSTOMIZATION = {
    "schema_version": "1.0.0",
    "view_id": "churn-risk-overview",
    "dataset_slug": "telco-customer-churn",
    "view_copy": {
        "heading": "Churn Risk Assessment",
        "description": "Estimate churn likelihood.",
        "usage_guidance": "Use canonical contracts.",
    },
    "field_hints": [
        {
            "field_name": "tenure",
            "display_label": "Months with Company",
            "explanatory_copy": "How long the customer has been with the provider.",
            "display_order_hint": 1,
            "group": "account-history",
        }
    ],
    "groups": [
        {
            "group_id": "account-history",
            "label": "Account History",
            "description": "Tenure and demographic fields.",
        }
    ],
    "contract_precedence": {
        "canonical_contracts_are_source_of_truth": True,
        "customization_defines_runtime_validation": False,
        "customization_duplicates_contract": False,
    },
}

_VALID_REGISTRY = {
    "schema_version": "atlas.dataflow.predict-view-customizations.v1",
    "predict_view_customizations": [_VALID_CUSTOMIZATION],
}

_STUB_CONTRACT = {
    "schema_version": "1.0.0",
    "features": [
        {
            "name": "tenure",
            "label": "Tenure",
            "input_type": "number",
            "optional": False,
            "display_order": 1,
        }
    ],
}


def _write_customization_registry(tmp_dir: Path, content: dict) -> Path:
    path = tmp_dir / "predict-view-customizations.json"
    path.write_text(json.dumps(content), encoding="utf-8")
    return path


def _passing_validator(customization: dict, public_contract: dict) -> dict:
    return {"valid": True, "errors": []}


def _failing_validator(customization: dict, public_contract: dict) -> dict:
    return {"valid": False, "errors": [{"field": "field_hints", "message": "Field not found in contract."}]}


def _stub_load_contract(dataset_slug: str) -> dict:
    return _STUB_CONTRACT


# ---------------------------------------------------------------------------
# Load succeeds: valid registry entry + passing validator
# ---------------------------------------------------------------------------

def test_load_returns_customization_record():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_customization_registry(Path(tmp), _VALID_REGISTRY)

        sys.modules["registry.predict_view_customization_validate"] = types.SimpleNamespace(
            validate_customization=_passing_validator
        )
        try:
            with mock.patch.object(loader_module, "load_public_contract", _stub_load_contract):
                result = load_public_predict_view_customization(
                    "telco-customer-churn",
                    "churn-risk-overview",
                    customizations_path=path,
                )
        finally:
            del sys.modules["registry.predict_view_customization_validate"]

        assert result["view_id"] == "churn-risk-overview"
        assert result["dataset_slug"] == "telco-customer-churn"
        assert "view_copy" in result
        assert "field_hints" in result
        assert "groups" in result


# ---------------------------------------------------------------------------
# CustomizationNotFoundError: no matching entry
# ---------------------------------------------------------------------------

def test_raises_not_found_for_unknown_view_id():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_customization_registry(Path(tmp), _VALID_REGISTRY)

        sys.modules["registry.predict_view_customization_validate"] = types.SimpleNamespace(
            validate_customization=_passing_validator
        )
        try:
            with mock.patch.object(loader_module, "load_public_contract", _stub_load_contract):
                raised = False
                try:
                    load_public_predict_view_customization(
                        "telco-customer-churn",
                        "nonexistent-view",
                        customizations_path=path,
                    )
                except CustomizationNotFoundError:
                    raised = True
        finally:
            del sys.modules["registry.predict_view_customization_validate"]
        assert raised, "Expected CustomizationNotFoundError for unknown view_id"


def test_raises_not_found_for_unknown_dataset_slug():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_customization_registry(Path(tmp), _VALID_REGISTRY)

        sys.modules["registry.predict_view_customization_validate"] = types.SimpleNamespace(
            validate_customization=_passing_validator
        )
        try:
            with mock.patch.object(loader_module, "load_public_contract", _stub_load_contract):
                raised = False
                try:
                    load_public_predict_view_customization(
                        "unknown-dataset",
                        "churn-risk-overview",
                        customizations_path=path,
                    )
                except CustomizationNotFoundError:
                    raised = True
        finally:
            del sys.modules["registry.predict_view_customization_validate"]
        assert raised, "Expected CustomizationNotFoundError for unknown dataset_slug"


# ---------------------------------------------------------------------------
# CustomizationNotFoundError: validation fails — treat as absent
# ---------------------------------------------------------------------------

def test_raises_not_found_when_validation_fails():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_customization_registry(Path(tmp), _VALID_REGISTRY)

        sys.modules["registry.predict_view_customization_validate"] = types.SimpleNamespace(
            validate_customization=_failing_validator
        )
        try:
            with mock.patch.object(loader_module, "load_public_contract", _stub_load_contract):
                raised = False
                try:
                    load_public_predict_view_customization(
                        "telco-customer-churn",
                        "churn-risk-overview",
                        customizations_path=path,
                    )
                except CustomizationNotFoundError:
                    raised = True
        finally:
            del sys.modules["registry.predict_view_customization_validate"]
        assert raised, "Expected CustomizationNotFoundError when validation fails"


# ---------------------------------------------------------------------------
# Registry unavailable conditions
# ---------------------------------------------------------------------------

def test_raises_not_found_when_registry_file_missing():
    raised = False
    try:
        load_public_predict_view_customization(
            "telco-customer-churn",
            "churn-risk-overview",
            customizations_path=Path("/nonexistent/path/predict-view-customizations.json"),
        )
    except CustomizationNotFoundError:
        raised = True
    assert raised, "Expected CustomizationNotFoundError when registry file is missing"


def test_raises_not_found_when_registry_is_malformed():
    with tempfile.TemporaryDirectory() as tmp:
        path = tmp / Path("predict-view-customizations.json")
        path.write_text("not-valid-json", encoding="utf-8")
        raised = False
        try:
            load_public_predict_view_customization(
                "telco-customer-churn",
                "churn-risk-overview",
                customizations_path=path,
            )
        except CustomizationNotFoundError:
            raised = True
        assert raised, "Expected CustomizationNotFoundError for malformed registry"


# ---------------------------------------------------------------------------
# Returned record does not expose unwanted internal fields
# ---------------------------------------------------------------------------

def test_result_does_not_contain_schema_version_root_key_added_by_registry():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_customization_registry(Path(tmp), _VALID_REGISTRY)

        sys.modules["registry.predict_view_customization_validate"] = types.SimpleNamespace(
            validate_customization=_passing_validator
        )
        try:
            with mock.patch.object(loader_module, "load_public_contract", _stub_load_contract):
                result = load_public_predict_view_customization(
                    "telco-customer-churn",
                    "churn-risk-overview",
                    customizations_path=path,
                )
        finally:
            del sys.modules["registry.predict_view_customization_validate"]

        # The top-level registry schema_version must not bleed into the record
        assert result.get("predict_view_customizations") is None
        # The returned record is the individual entry
        assert "view_id" in result
        assert "dataset_slug" in result


# ---------------------------------------------------------------------------
# CustomizationNotFoundError has the expected error code
# ---------------------------------------------------------------------------

def test_customization_not_found_error_code():
    assert CustomizationNotFoundError.code == "CUSTOMIZATION_NOT_FOUND"


# ---------------------------------------------------------------------------
# M19-04: hidden field visibility checks
# ---------------------------------------------------------------------------

def test_hidden_optional_field_passes_validation():
    """A field_hint with hidden: true on an optional field must not produce REQUIRED_FIELD_HIDDEN."""
    customization = {
        "field_hints": [{"field_name": "tenure", "hidden": True}],
        "groups": [],
    }
    public_contract = {
        "features": [
            {"name": "tenure", "label": "Tenure", "input_type": "number", "optional": True, "display_order": 1}
        ]
    }
    result = _real_validate_customization(customization, public_contract)
    hidden_errors = [e for e in result["errors"] if e["code"] == "REQUIRED_FIELD_HIDDEN"]
    assert len(hidden_errors) == 0, (
        f"Expected no REQUIRED_FIELD_HIDDEN for a hidden optional field, got: {hidden_errors}"
    )


def test_hidden_required_field_produces_required_field_hidden():
    """A field_hint with hidden: true on a required field must produce REQUIRED_FIELD_HIDDEN."""
    customization = {
        "field_hints": [{"field_name": "tenure", "hidden": True}],
        "groups": [],
    }
    public_contract = {
        "features": [
            {"name": "tenure", "label": "Tenure", "input_type": "number", "optional": False, "display_order": 1}
        ]
    }
    result = _real_validate_customization(customization, public_contract)
    hidden_errors = [e for e in result["errors"] if e["code"] == "REQUIRED_FIELD_HIDDEN"]
    assert len(hidden_errors) >= 1, (
        f"Expected at least one REQUIRED_FIELD_HIDDEN error for a hidden required field, got: {result['errors']}"
    )
    assert any("hidden" in (e.get("field") or "") for e in hidden_errors), (
        f"Expected field path to contain 'hidden', got: {[e.get('field') for e in hidden_errors]}"
    )


def test_existing_records_unaffected_by_hidden_field_check():
    """Records without hidden fields are not affected by the new hidden-field validation check."""
    result = _real_validate_customization(_VALID_CUSTOMIZATION, _STUB_CONTRACT)
    hidden_errors = [e for e in result["errors"] if e["code"] == "REQUIRED_FIELD_HIDDEN"]
    assert len(hidden_errors) == 0, (
        f"Expected no REQUIRED_FIELD_HIDDEN errors for a record without hidden fields, got: {hidden_errors}"
    )


# ---------------------------------------------------------------------------
# Direct runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_load_returns_customization_record,
        test_raises_not_found_for_unknown_view_id,
        test_raises_not_found_for_unknown_dataset_slug,
        test_raises_not_found_when_validation_fails,
        test_raises_not_found_when_registry_file_missing,
        test_raises_not_found_when_registry_is_malformed,
        test_result_does_not_contain_schema_version_root_key_added_by_registry,
        test_customization_not_found_error_code,
        test_hidden_optional_field_passes_validation,
        test_hidden_required_field_produces_required_field_hidden,
        test_existing_records_unaffected_by_hidden_field_check,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {t.__name__}: {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
