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
    classify_customization_compatibility,
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
# Explicit hidden: true validator path (M19-05)
# ---------------------------------------------------------------------------

def test_hidden_optional_field_passes_validate_customization():
    result = validate_customization(
        {
            "schema_version": "1.0.0",
            "view_id": "churn-risk-overview",
            "field_hints": [
                {"field_name": "monthly_charges", "hidden": True},
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
    assert "REQUIRED_FIELD_HIDDEN" not in _codes(result)


def test_hidden_required_field_produces_required_field_hidden_explicit():
    result = validate_customization(
        {
            "schema_version": "1.0.0",
            "view_id": "churn-risk-overview",
            "field_hints": [
                {"field_name": "tenure", "hidden": True},
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
    assert "REQUIRED_FIELD_HIDDEN" in _codes(result)
    hidden_errors = [e for e in result["errors"] if e["code"] == "REQUIRED_FIELD_HIDDEN"]
    assert any("hidden" in (e.get("field") or "") for e in hidden_errors), (
        f"Expected REQUIRED_FIELD_HIDDEN with field path containing 'hidden', got: {hidden_errors}"
    )


# ---------------------------------------------------------------------------
# Project Spec S0250: public-contract v2 (univariate-forecasting
# history-series) compatibility -- strict discriminants, no groups, both
# fields always required.
# ---------------------------------------------------------------------------

_MOCK_PUBLIC_CONTRACT_V2 = {
    "schema_version": "2.0.0",
    "problem_type": "univariate_forecasting",
    "input_kind": "history_series",
    "history_series": {
        "time_index_field": {"name": "period", "label": "Period", "value_kind": "calendar_period", "display_order": 1},
        "target_field": {"name": "value", "label": "Value", "value_kind": "number", "display_order": 2},
        "frequency": "Monthly",
    },
    "forecast": {"forecast_horizon": 12, "horizon_user_editable": False},
}

_VALID_HISTORY_CUSTOMIZATION = {
    "schema_version": "1.0.0",
    "view_id": "forecast-overview",
    "field_hints": [
        {"field_name": "period", "display_order_hint": 1},
        {"field_name": "value", "display_order_hint": 2},
    ],
    "groups": [],
    "contract_precedence": {
        "canonical_contracts_are_source_of_truth": True,
        "customization_defines_runtime_validation": False,
        "customization_duplicates_contract": False,
    },
}


def test_v2_time_index_field_hint_accepted():
    result = validate_customization(_VALID_HISTORY_CUSTOMIZATION, _MOCK_PUBLIC_CONTRACT_V2)
    assert result["valid"] is True, result["errors"]


def test_v2_target_field_hint_accepted():
    result = validate_customization(
        {**_VALID_HISTORY_CUSTOMIZATION, "field_hints": [{"field_name": "value", "display_order_hint": 1}]},
        _MOCK_PUBLIC_CONTRACT_V2,
    )
    # Missing "period" hint is fine -- not every field requires an explicit
    # hint, only hints that ARE present must reference known fields.
    assert result["valid"] is True, result["errors"]


def test_v2_unknown_field_rejected():
    result = validate_customization(
        {**_VALID_HISTORY_CUSTOMIZATION, "field_hints": [{"field_name": "not_a_real_field"}]},
        _MOCK_PUBLIC_CONTRACT_V2,
    )
    assert result["valid"] is False
    assert "UNKNOWN_FIELD_REFERENCE" in _codes(result)


def test_v2_duplicate_field_rejected():
    result = validate_customization(
        {
            **_VALID_HISTORY_CUSTOMIZATION,
            "field_hints": [{"field_name": "period"}, {"field_name": "period"}],
        },
        _MOCK_PUBLIC_CONTRACT_V2,
    )
    assert result["valid"] is False
    assert "DUPLICATE_FIELD_REFERENCE" in _codes(result)


def test_v2_hidden_required_field_rejected():
    result = validate_customization(
        {**_VALID_HISTORY_CUSTOMIZATION, "field_hints": [{"field_name": "period", "hidden": True}]},
        _MOCK_PUBLIC_CONTRACT_V2,
    )
    assert result["valid"] is False
    assert "REQUIRED_FIELD_HIDDEN" in _codes(result)


def test_v2_non_empty_groups_rejected():
    result = validate_customization(
        {**_VALID_HISTORY_CUSTOMIZATION, "groups": [{"group_id": "g1", "label": "Group 1"}]},
        _MOCK_PUBLIC_CONTRACT_V2,
    )
    assert result["valid"] is False
    assert "HISTORY_SERIES_GROUPS_NOT_ALLOWED" in _codes(result)


def test_v2_field_group_reference_rejected():
    result = validate_customization(
        {
            **_VALID_HISTORY_CUSTOMIZATION,
            "groups": [{"group_id": "g1", "label": "Group 1"}],
            "field_hints": [{"field_name": "period", "group": "g1"}],
        },
        _MOCK_PUBLIC_CONTRACT_V2,
    )
    assert result["valid"] is False
    assert "HISTORY_SERIES_FIELD_GROUP_NOT_ALLOWED" in _codes(result)


def test_v1_scalar_group_customization_behavior_unchanged_alongside_v2_support():
    result = validate_customization(
        {
            "schema_version": "1.0.0",
            "view_id": "churn-risk-overview",
            "field_hints": [{"field_name": "tenure", "group": "account-history"}],
            "groups": [{"group_id": "account-history", "label": "Account History"}],
            "contract_precedence": {
                "canonical_contracts_are_source_of_truth": True,
                "customization_defines_runtime_validation": False,
                "customization_duplicates_contract": False,
            },
        },
        _MOCK_PUBLIC_CONTRACT,
    )
    assert result["valid"] is True, result["errors"]


def test_unresolvable_public_contract_shape_fails_closed():
    # Neither v1 "features" nor the exact v2 discriminants -- must not be
    # guessed; every field_hints reference becomes UNKNOWN_FIELD_REFERENCE.
    result = validate_customization(
        _VALID_HISTORY_CUSTOMIZATION,
        {"schema_version": "3.0.0", "something_else": True},
    )
    assert result["valid"] is False
    assert "UNKNOWN_FIELD_REFERENCE" in _codes(result)


def test_classify_compatible_v2_history_series_customization():
    result = classify_customization_compatibility(
        "forecast-overview",
        "example-forecasting-dataset",
        {**_VALID_HISTORY_CUSTOMIZATION, "dataset_slug": "example-forecasting-dataset"},
        _MOCK_PUBLIC_CONTRACT_V2,
    )
    assert result == {"status": "compatible", "errors": []}


# ---------------------------------------------------------------------------
# classify_customization_compatibility (Project Spec S0098)
# ---------------------------------------------------------------------------

_VALID_CUSTOMIZATION = {
    "schema_version": "1.0.0",
    "view_id": "churn-risk-overview",
    "dataset_slug": "telco-customer-churn",
    "field_hints": [{"field_name": "tenure", "display_order_hint": 1}],
    "groups": [],
    "contract_precedence": {
        "canonical_contracts_are_source_of_truth": True,
        "customization_defines_runtime_validation": False,
        "customization_duplicates_contract": False,
    },
}


def test_classify_compatible_customization():
    result = classify_customization_compatibility(
        "churn-risk-overview", "telco-customer-churn", _VALID_CUSTOMIZATION, _MOCK_PUBLIC_CONTRACT
    )
    assert result == {"status": "compatible", "errors": []}


def test_classify_incompatible_when_field_reference_unknown():
    customization = {**_VALID_CUSTOMIZATION, "field_hints": [{"field_name": "nonexistent_field"}]}
    result = classify_customization_compatibility(
        "churn-risk-overview", "telco-customer-churn", customization, _MOCK_PUBLIC_CONTRACT
    )
    assert result["status"] == "incompatible"
    assert "UNKNOWN_FIELD_REFERENCE" in _codes(result)


def test_classify_incompatible_when_view_id_identity_mismatches():
    result = classify_customization_compatibility(
        "some-other-view", "telco-customer-churn", _VALID_CUSTOMIZATION, _MOCK_PUBLIC_CONTRACT
    )
    assert result["status"] == "incompatible"
    assert "CUSTOMIZATION_VIEW_ID_MISMATCH" in _codes(result)


def test_classify_incompatible_when_dataset_slug_identity_mismatches():
    result = classify_customization_compatibility(
        "churn-risk-overview", "some-other-dataset", _VALID_CUSTOMIZATION, _MOCK_PUBLIC_CONTRACT
    )
    assert result["status"] == "incompatible"
    assert "CUSTOMIZATION_DATASET_SLUG_MISMATCH" in _codes(result)


def test_classify_incompatible_when_public_contract_unavailable():
    result = classify_customization_compatibility(
        "churn-risk-overview", "telco-customer-churn", _VALID_CUSTOMIZATION, None
    )
    assert result["status"] == "incompatible"
    assert "PUBLIC_CONTRACT_UNAVAILABLE" in _codes(result)


def test_classify_never_mutates_the_customization_it_classifies():
    customization = json.loads(json.dumps(_VALID_CUSTOMIZATION))
    before = json.loads(json.dumps(customization))
    classify_customization_compatibility(
        "churn-risk-overview", "telco-customer-churn", customization, None
    )
    assert customization == before


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
        test_hidden_optional_field_passes_validate_customization,
        test_hidden_required_field_produces_required_field_hidden_explicit,
        test_v2_time_index_field_hint_accepted,
        test_v2_target_field_hint_accepted,
        test_v2_unknown_field_rejected,
        test_v2_duplicate_field_rejected,
        test_v2_hidden_required_field_rejected,
        test_v2_non_empty_groups_rejected,
        test_v2_field_group_reference_rejected,
        test_v1_scalar_group_customization_behavior_unchanged_alongside_v2_support,
        test_unresolvable_public_contract_shape_fails_closed,
        test_classify_compatible_v2_history_series_customization,
        test_classify_compatible_customization,
        test_classify_incompatible_when_field_reference_unknown,
        test_classify_incompatible_when_view_id_identity_mismatches,
        test_classify_incompatible_when_dataset_slug_identity_mismatches,
        test_classify_incompatible_when_public_contract_unavailable,
        test_classify_never_mutates_the_customization_it_classifies,
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
