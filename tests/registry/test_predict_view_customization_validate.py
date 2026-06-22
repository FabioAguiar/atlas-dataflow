"""
Customization metadata validator tests for M19-02.

Verifies that validate_customization accepts valid customization metadata
and rejects unknown field references, duplicate field references, broken
group references, required-field hiding, duplicate group IDs, and
contract_precedence violations with predictable, deterministic errors.

Run from the repository root:
    python -m pytest tests/registry/test_predict_view_customization_validate.py -v
or directly:
    python tests/registry/test_predict_view_customization_validate.py
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from registry.predict_view_customization_validate import (  # noqa: E402
    validate_customization,
    validate_customization_file,
)

EXAMPLES_DIR = REPO_ROOT / "contracts" / "examples"

_MOCK_PUBLIC_CONTRACT = {
    "features": [
        {"name": "tenure", "optional": False, "label": "Tenure", "input_type": "number", "display_order": 1},
        {"name": "monthly_charges", "optional": True, "label": "Monthly Charges", "input_type": "number", "display_order": 2},
        {"name": "total_charges", "optional": True, "label": "Total Charges", "input_type": "number", "display_order": 3},
        {"name": "contract", "optional": True, "label": "Contract", "input_type": "string", "display_order": 4},
        {"name": "internet_service", "optional": True, "label": "Internet Service", "input_type": "string", "display_order": 5},
        {"name": "payment_method", "optional": True, "label": "Payment Method", "input_type": "string", "display_order": 6},
        {"name": "tech_support", "optional": True, "label": "Tech Support", "input_type": "string", "display_order": 7},
        {"name": "senior_citizen", "optional": True, "label": "Senior Citizen", "input_type": "boolean", "display_order": 8},
    ]
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _codes(result: dict) -> set[str]:
    return {e["code"] for e in result["errors"]}


# ---------------------------------------------------------------------------
# Valid fixture
# ---------------------------------------------------------------------------

def test_valid_customization_example_passes():
    result = validate_customization_file(
        EXAMPLES_DIR / "predict-view-customization.example.json",
        _MOCK_PUBLIC_CONTRACT,
    )
    assert result["valid"] is True, f"Expected valid, got errors: {result['errors']}"
    assert result["errors"] == []


# ---------------------------------------------------------------------------
# Invalid fixtures
# ---------------------------------------------------------------------------

def test_unknown_field_reference_rejected():
    result = validate_customization_file(
        EXAMPLES_DIR / "invalid-predict-view-customization-unknown-field.example.json",
        _MOCK_PUBLIC_CONTRACT,
    )
    assert result["valid"] is False
    assert "UNKNOWN_FIELD_REFERENCE" in _codes(result)


def test_duplicate_field_reference_rejected():
    result = validate_customization_file(
        EXAMPLES_DIR / "invalid-predict-view-customization-duplicate-field.example.json",
        _MOCK_PUBLIC_CONTRACT,
    )
    assert result["valid"] is False
    assert "DUPLICATE_FIELD_REFERENCE" in _codes(result)


def test_required_field_hidden_rejected():
    result = validate_customization_file(
        EXAMPLES_DIR / "invalid-predict-view-customization-required-field-hidden.example.json",
        _MOCK_PUBLIC_CONTRACT,
    )
    assert result["valid"] is False
    assert "REQUIRED_FIELD_HIDDEN" in _codes(result)


def test_broken_group_reference_rejected():
    result = validate_customization_file(
        EXAMPLES_DIR / "invalid-predict-view-customization-broken-group-ref.example.json",
        _MOCK_PUBLIC_CONTRACT,
    )
    assert result["valid"] is False
    assert "BROKEN_GROUP_REFERENCE" in _codes(result)


# ---------------------------------------------------------------------------
# Inline semantic checks
# ---------------------------------------------------------------------------

def test_duplicate_group_id_rejected():
    result = validate_customization(
        {
            "schema_version": "1.0.0",
            "view_id": "churn-risk-overview",
            "field_hints": [
                {"field_name": "tenure", "group": "account-history"},
            ],
            "groups": [
                {"group_id": "account-history", "label": "Account History"},
                {"group_id": "account-history", "label": "Duplicate"},
            ],
            "contract_precedence": {
                "canonical_contracts_are_source_of_truth": True,
                "customization_defines_runtime_validation": False,
                "customization_duplicates_contract": False,
            },
        },
        _MOCK_PUBLIC_CONTRACT,
    )
    assert result["valid"] is False
    assert "DUPLICATE_GROUP_ID" in _codes(result)


def test_contract_precedence_violation_rejected():
    result = validate_customization(
        {
            "schema_version": "1.0.0",
            "view_id": "churn-risk-overview",
            "contract_precedence": {
                "canonical_contracts_are_source_of_truth": False,
                "customization_defines_runtime_validation": False,
                "customization_duplicates_contract": False,
            },
        },
        _MOCK_PUBLIC_CONTRACT,
    )
    assert result["valid"] is False
    assert "CONTRACT_PRECEDENCE_VIOLATION" in _codes(result)


def test_empty_field_hints_passes():
    result = validate_customization(
        {
            "schema_version": "1.0.0",
            "view_id": "churn-risk-overview",
            "field_hints": [],
            "groups": [],
            "contract_precedence": {
                "canonical_contracts_are_source_of_truth": True,
                "customization_defines_runtime_validation": False,
                "customization_duplicates_contract": False,
            },
        },
        _MOCK_PUBLIC_CONTRACT,
    )
    assert result["valid"] is True, f"Expected valid, got errors: {result['errors']}"


def test_required_field_absent_from_field_hints_passes():
    """A required field absent from field_hints uses default presentation — not rejected."""
    result = validate_customization(
        {
            "schema_version": "1.0.0",
            "view_id": "churn-risk-overview",
            "field_hints": [
                {"field_name": "monthly_charges", "display_order_hint": 1},
            ],
            "contract_precedence": {
                "canonical_contracts_are_source_of_truth": True,
                "customization_defines_runtime_validation": False,
                "customization_duplicates_contract": False,
            },
        },
        _MOCK_PUBLIC_CONTRACT,
    )
    assert result["valid"] is True, f"Expected valid, got errors: {result['errors']}"


def test_error_messages_contain_no_filesystem_paths():
    """Validation errors must not leak internal filesystem details."""
    result = validate_customization(
        {
            "schema_version": "1.0.0",
            "view_id": "churn-risk-overview",
            "field_hints": [{"field_name": "nonexistent_feature"}],
            "contract_precedence": {
                "canonical_contracts_are_source_of_truth": True,
                "customization_defines_runtime_validation": False,
                "customization_duplicates_contract": False,
            },
        },
        _MOCK_PUBLIC_CONTRACT,
    )
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
        test_valid_customization_example_passes,
        test_unknown_field_reference_rejected,
        test_duplicate_field_reference_rejected,
        test_required_field_hidden_rejected,
        test_broken_group_reference_rejected,
        test_duplicate_group_id_rejected,
        test_contract_precedence_violation_rejected,
        test_empty_field_hints_passes,
        test_required_field_absent_from_field_hints_passes,
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
