"""
Dataset public profile reference validator tests for M34-02.

Verifies that validate_profile_references accepts profiles whose reference
fields resolve correctly and rejects profiles whose bound_predict_view_id or
primary_metric_key do not resolve against the injected predict-views registry
and release metrics data, with deterministic, sanitized errors.

Run from the repository root:
    python -m pytest tests/registry/test_dataset_public_profile_validate.py -v
or directly:
    python tests/registry/test_dataset_public_profile_validate.py
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from registry.dataset_public_profile_validate import validate_profile_references  # noqa: E402


_MOCK_PREDICT_VIEWS_REGISTRY = {
    "schema_version": "atlas.dataflow.predict-views.v1",
    "predict_views": [
        {"view_id": "churn-risk-overview", "dataset_slug": "telco-customer-churn"},
        {"view_id": "bank-subscription-predictor", "dataset_slug": "bank-marketing"},
    ],
}

_MOCK_RELEASE_METRICS = {
    "schema_version": "metrics.v1",
    "dataset_slug": "telco-customer-churn",
    "release_id": "release-20260101-001",
    "evaluation": {
        "split": "test",
        "sample_size": 1000,
        "metrics": {
            "accuracy": 0.9,
            "precision": 0.8,
            "recall": 0.7,
            "f1_score": 0.75,
            "auc_roc": 0.85,
        },
    },
}


def _codes(result: dict) -> set[str]:
    return {e["code"] for e in result["errors"]}


def _profile(**overrides) -> dict:
    base = {
        "schema_version": "1.0.0",
        "dataset_slug": "telco-customer-churn",
    }
    base.update(overrides)
    return base


def _performance_focus(**overrides) -> dict:
    focus = {
        "focus_id": "positive_class_detection",
        "highlighted_score_id": "recall",
        "visible_scores": [
            {"score_id": "recall", "display_label": "Recall", "value": "0.574", "value_source": "manual", "order": 0},
            {"score_id": "precision", "display_label": "Precision", "value": "0.679", "value_source": "canonical", "order": 1},
        ],
    }
    focus.update(overrides)
    return focus


# ---------------------------------------------------------------------------
# Passing cases
# ---------------------------------------------------------------------------

def test_profile_with_no_references_passes():
    result = validate_profile_references(
        _profile(),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
    )
    assert result["valid"] is True, f"Expected valid, got errors: {result['errors']}"
    assert result["errors"] == []


def test_profile_with_null_references_passes():
    result = validate_profile_references(
        _profile(
            inference_presentation={"bound_predict_view_id": None},
            home_card={"primary_metric_key": None},
        ),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
    )
    assert result["valid"] is True, f"Expected valid, got errors: {result['errors']}"


def test_profile_with_valid_bound_predict_view_id_passes():
    result = validate_profile_references(
        _profile(inference_presentation={"bound_predict_view_id": "churn-risk-overview"}),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
    )
    assert result["valid"] is True, f"Expected valid, got errors: {result['errors']}"


def test_duplicate_predict_view_id_uses_first_match_deterministically():
    duplicate_registry = {
        "schema_version": "atlas.dataflow.predict-views.v1",
        "predict_views": [
            {"view_id": "churn-risk-overview", "dataset_slug": "telco-customer-churn"},
            {"view_id": "churn-risk-overview", "dataset_slug": "bank-marketing"},
        ],
    }
    profile = _profile(
        inference_presentation={"bound_predict_view_id": "churn-risk-overview"},
    )

    first_result = validate_profile_references(
        profile,
        duplicate_registry,
        _MOCK_RELEASE_METRICS,
    )
    second_result = validate_profile_references(
        profile,
        duplicate_registry,
        _MOCK_RELEASE_METRICS,
    )

    assert first_result == second_result
    assert first_result["valid"] is True, f"Expected valid, got errors: {first_result['errors']}"
    assert first_result["errors"] == []


def test_profile_with_valid_primary_metric_key_passes():
    result = validate_profile_references(
        _profile(home_card={"primary_metric_key": "accuracy"}),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
    )
    assert result["valid"] is True, f"Expected valid, got errors: {result['errors']}"


def test_valid_performance_focus_passes():
    result = validate_profile_references(
        _profile(performance_focus=_performance_focus()),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
    )
    assert result == {"valid": True, "errors": []}


# ---------------------------------------------------------------------------
# Rejection cases
# ---------------------------------------------------------------------------

def test_bound_predict_view_not_found_rejected():
    result = validate_profile_references(
        _profile(inference_presentation={"bound_predict_view_id": "nonexistent-view"}),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
    )
    assert result["valid"] is False
    assert "BOUND_PREDICT_VIEW_NOT_FOUND" in _codes(result)


def test_bound_predict_view_dataset_mismatch_rejected():
    result = validate_profile_references(
        _profile(
            dataset_slug="telco-customer-churn",
            inference_presentation={"bound_predict_view_id": "bank-subscription-predictor"},
        ),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
    )
    assert result["valid"] is False
    assert "BOUND_PREDICT_VIEW_DATASET_MISMATCH" in _codes(result)
    assert "BOUND_PREDICT_VIEW_NOT_FOUND" not in _codes(result)


def test_primary_metric_key_not_found_rejected():
    result = validate_profile_references(
        _profile(home_card={"primary_metric_key": "nonexistent_metric"}),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
    )
    assert result["valid"] is False
    assert "PRIMARY_METRIC_KEY_NOT_FOUND" in _codes(result)


def test_both_references_invalid_accumulates_both_errors():
    result = validate_profile_references(
        _profile(
            inference_presentation={"bound_predict_view_id": "nonexistent-view"},
            home_card={"primary_metric_key": "nonexistent_metric"},
        ),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
    )
    assert result["valid"] is False
    codes = _codes(result)
    assert "BOUND_PREDICT_VIEW_NOT_FOUND" in codes
    assert "PRIMARY_METRIC_KEY_NOT_FOUND" in codes


def test_performance_focus_rejects_unknown_focus_duplicates_and_invisible_highlight():
    duplicate = {"score_id": "recall", "display_label": "Recall", "value": "0.1", "value_source": "manual", "order": 1}
    result = validate_profile_references(
        _profile(performance_focus=_performance_focus(
            focus_id="unknown_focus",
            highlighted_score_id="precision",
            visible_scores=[duplicate, {**duplicate, "order": 2}],
        )),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
    )
    codes = _codes(result)
    assert result["valid"] is False
    assert "PERFORMANCE_FOCUS_UNKNOWN" in codes
    assert "PERFORMANCE_SCORE_DUPLICATE" in codes
    assert "PERFORMANCE_HIGHLIGHT_NOT_VISIBLE" in codes


def test_performance_focus_rejects_score_outside_focus_and_unsafe_label():
    result = validate_profile_references(
        _profile(performance_focus=_performance_focus(visible_scores=[{
            "score_id": "roc_auc", "display_label": "<script>", "value": "0.85",
            "value_source": "manual", "order": 0,
        }], highlighted_score_id="roc_auc")),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
    )
    assert "PERFORMANCE_SCORE_NOT_SUPPORTED_FOR_FOCUS" in _codes(result)


# ---------------------------------------------------------------------------
# Sanitization
# ---------------------------------------------------------------------------

def test_error_messages_contain_no_filesystem_paths():
    result = validate_profile_references(
        _profile(
            inference_presentation={"bound_predict_view_id": "nonexistent-view"},
            home_card={"primary_metric_key": "nonexistent_metric"},
        ),
        _MOCK_PREDICT_VIEWS_REGISTRY,
        _MOCK_RELEASE_METRICS,
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
        test_profile_with_no_references_passes,
        test_profile_with_null_references_passes,
        test_profile_with_valid_bound_predict_view_id_passes,
        test_duplicate_predict_view_id_uses_first_match_deterministically,
        test_profile_with_valid_primary_metric_key_passes,
        test_bound_predict_view_not_found_rejected,
        test_bound_predict_view_dataset_mismatch_rejected,
        test_primary_metric_key_not_found_rejected,
        test_both_references_invalid_accumulates_both_errors,
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
