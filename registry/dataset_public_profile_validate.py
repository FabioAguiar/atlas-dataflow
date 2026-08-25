"""
Dataset public profile reference validator for M34-02.

Validates the two reference-carrying fields of a dataset public profile draft
(contracts/dataset-public-profile.schema.json) against already-loaded registry
and release-metrics data. The predict-views registry and release metrics
artifact are injected by the caller; this module does not read either file
internally.

Validates:
  - inference_presentation.bound_predict_view_id, when non-null, resolves to
    an entry in the injected predict-views registry's predict_views[] array
    whose view_id matches; and that entry's dataset_slug equals the profile's
    own dataset_slug.
  - home_card.primary_metric_key, when non-null, resolves to a key in the
    injected release metrics artifact's evaluation.metrics object.

Both reference fields are optional: null or absent values are not checked.

Does not validate field_hints, groups, view_copy, or any other presentation
surface already owned by registry/predict_view_customization_validate.py, and
does not validate result_card.badge_preset, theme.preset, or home_card.icon,
which are already bounded by contracts/dataset-public-profile.schema.json's
own JSON-Schema enums.

Validation is deterministic: identical inputs always produce identical output.
Error messages are sanitized: field path and error code only -- no filesystem
paths, release IDs, or raw registry/metrics data.
"""

PERFORMANCE_FOCUS_LABELS = {
    "overall_discrimination": "Overall discrimination",
    "positive_class_detection": "Positive-class detection",
    "balanced_classification": "Balanced classification",
    "probability_quality": "Probability quality",
    "operational_decision": "Operational decision",
    "regression_performance": "Regression performance",
    "forecasting_performance": "Forecasting performance",
}

PERFORMANCE_SCORE_CATALOG = {
    "overall_discrimination": {
        "roc_auc": "ROC-AUC", "pr_auc": "PR-AUC",
        "gini_coefficient": "Gini coefficient", "ks_statistic": "KS statistic",
    },
    "positive_class_detection": {
        "recall": "Recall", "precision": "Precision", "f1_score": "F1-score",
        "f_beta_score": "F-beta score", "pr_auc": "PR-AUC",
        "false_negative_rate": "False Negative Rate",
    },
    "balanced_classification": {
        "balanced_accuracy": "Balanced Accuracy", "mcc": "MCC",
        "f1_score": "F1-score", "accuracy": "Accuracy", "recall": "Recall",
        "specificity": "Specificity", "cohens_kappa": "Cohen's Kappa",
        "g_mean": "G-Mean",
        # Project Spec S0215: explicit multiclass aggregate score ids --
        # distinct from the binary-era f1_score/recall above, never
        # collapsed into them.
        "f1_macro": "F1 Macro", "f1_weighted": "F1 Weighted",
        "precision_macro": "Precision Macro", "recall_macro": "Recall Macro",
    },
    "probability_quality": {
        "log_loss": "Log Loss", "brier_score": "Brier Score",
        "calibration_error": "Calibration Error",
        "calibration_slope": "Calibration Slope",
        "calibration_intercept": "Calibration Intercept",
        "expected_calibration_error": "Expected Calibration Error",
    },
    "operational_decision": {
        "precision_at_k": "Precision@K", "recall_at_k": "Recall@K",
        "lift_at_k": "Lift@K", "gain_at_k": "Gain@K",
        "expected_cost": "Expected Cost", "expected_profit": "Expected Profit",
        "net_benefit": "Net Benefit",
        "cost_per_correct_detection": "Cost per Correct Detection",
        "false_positives_at_k": "False Positives at K",
        "false_negatives_at_k": "False Negatives at K",
    },
    # Project Spec S0229: the bounded canonical continuous-regression score
    # catalog. Never applicable to binary/multiclass, and never extended with
    # classification-only scores.
    "regression_performance": {
        "r2": "R²", "mae": "MAE", "rmse": "RMSE",
    },
    # Project Spec S0247: the bounded canonical univariate-forecasting score
    # catalog. Never applicable to binary/multiclass/continuous_regression,
    # and never extended with classification-only scores. mae/rmse share the
    # same identity as regression_performance's own catalog entries above;
    # seasonal_mase is forecasting-only.
    "forecasting_performance": {
        "mae": "MAE", "rmse": "RMSE", "seasonal_mase": "Seasonal MASE",
    },
}

# Project Spec S0240: the closed backend focus/problem-type applicability
# mapping, kept consistent with the governed frontend focus applicability
# (web/src/lib/performanceMetricMetadata.ts). Used only to reject an entire
# incompatible focus when a trusted expected_problem_type is supplied to
# validate_profile_references -- it never changes score-level vocabulary.
PERFORMANCE_FOCUS_PROBLEM_TYPES = {
    "overall_discrimination": {"binary_classification"},
    "positive_class_detection": {"binary_classification"},
    "balanced_classification": {"binary_classification", "multiclass_classification"},
    "probability_quality": {"binary_classification", "multiclass_classification"},
    "operational_decision": {"binary_classification"},
    "regression_performance": {"continuous_regression"},
    "forecasting_performance": {"univariate_forecasting"},
}

BINARY_RESULT_PRESENTATION_SCHEMA_VERSION = "binary-result-presentation.v1"
MULTICLASS_RESULT_PRESENTATION_SCHEMA_VERSION = "multiclass-result-presentation.v1"
CONTINUOUS_REGRESSION_RESULT_PRESENTATION_SCHEMA_VERSION = "continuous-regression-result-presentation.v1"
UNIVARIATE_FORECASTING_RESULT_PRESENTATION_SCHEMA_VERSION = "univariate-forecasting-result-presentation.v1"
_RESULT_CARD_FALLBACKS = {
    "positive_class_probability_label": "Positive class probability",
    "predicted_outcome_label": "Predicted outcome",
    "positive_outcome_copy": "Positive outcome",
    "negative_outcome_copy": "Negative outcome",
    "model_section_label": "Model",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
}
_MULTICLASS_RESULT_CARD_FALLBACKS = {
    "predicted_class_label": "Predicted class",
    "class_probability_distribution_label": "Class probability distribution",
    "model_section_label": "Model",
}
_CONTINUOUS_REGRESSION_RESULT_CARD_FALLBACKS = {
    "predicted_value_label": "Predicted value",
    "model_section_label": "Model",
}
_CONTINUOUS_REGRESSION_DECIMAL_PLACES_FALLBACK = 2
_UNIVARIATE_FORECASTING_RESULT_CARD_FALLBACKS = {
    "forecast_series_label": "Forecast",
    "future_time_index_label": "Period",
    "forecast_value_label": "Forecast",
    "model_section_label": "Model",
}
_UNIVARIATE_FORECASTING_DECIMAL_PLACES_FALLBACK = 2


def normalize_binary_result_presentation(result_card: object) -> dict:
    """Return the one canonical, dataset-neutral Result Card presentation.

    Historical legacy keys are read only as presentation copy. Technical
    result semantics and the legacy submit action are intentionally ignored.
    Schema validation remains responsible for rejecting unknown/unsafe input;
    this pure projection is deterministic and idempotent.
    """
    source = result_card if isinstance(result_card, dict) else {}
    legacy_labels = source.get("badge_labels")
    if not isinstance(legacy_labels, dict):
        legacy_labels = {}
    interpretation = source.get("interpretation")
    if not isinstance(interpretation, dict):
        interpretation = {}
    canonical_labels = interpretation.get("labels")
    if not isinstance(canonical_labels, dict):
        canonical_labels = {}

    def copy(canonical_key: str, legacy_key: str | None = None) -> str:
        value = source.get(canonical_key)
        if not isinstance(value, str) or not value.strip():
            value = source.get(legacy_key) if legacy_key else None
        return value.strip() if isinstance(value, str) and value.strip() else _RESULT_CARD_FALLBACKS[canonical_key]

    def label(key: str) -> str:
        value = canonical_labels.get(key)
        if not isinstance(value, str) or not value.strip():
            value = legacy_labels.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else _RESULT_CARD_FALLBACKS[key]

    # risk is the only supported renderer preset. Invalid values cannot pass
    # schema validation and must never be projected as a new authority.
    #
    # Project Spec S0239: model_section_label is fixed to "Model" -- neither
    # the canonical key nor the legacy model_label compatibility key may
    # control the normalized output value. Both remain readable-only inputs
    # so historical payloads stay schema-compatible.
    return {
        "schema_version": BINARY_RESULT_PRESENTATION_SCHEMA_VERSION,
        "positive_class_probability_label": copy(
            "positive_class_probability_label", "probability_label"
        ),
        "predicted_outcome_label": copy("predicted_outcome_label"),
        "positive_outcome_copy": copy("positive_outcome_copy"),
        "negative_outcome_copy": copy("negative_outcome_copy"),
        "model_section_label": _RESULT_CARD_FALLBACKS["model_section_label"],
        "interpretation": {
            "preset": "risk",
            "labels": {key: label(key) for key in ("high", "medium", "low")},
        },
    }


def normalize_multiclass_result_presentation(result_card: object) -> dict:
    """Return canonical copy-only multiclass presentation deterministically."""
    source = result_card if isinstance(result_card, dict) else {}

    def copy(key: str) -> str:
        value = source.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else _MULTICLASS_RESULT_CARD_FALLBACKS[key]

    # Project Spec S0239: model_section_label is fixed to "Model" regardless
    # of incoming presentation copy.
    return {
        "schema_version": MULTICLASS_RESULT_PRESENTATION_SCHEMA_VERSION,
        **{key: copy(key) for key in _MULTICLASS_RESULT_CARD_FALLBACKS if key != "model_section_label"},
        "model_section_label": _MULTICLASS_RESULT_CARD_FALLBACKS["model_section_label"],
    }


def normalize_continuous_regression_result_presentation(result_card: object) -> dict:
    """Return canonical copy-only continuous-regression presentation deterministically.

    decimal_places is bounded 0..6, defaulting when absent/invalid. The
    optional value_unit_label is presentation copy only and is included only
    when it is a non-empty string; it never carries a fallback of its own.
    """
    source = result_card if isinstance(result_card, dict) else {}

    def copy(key: str) -> str:
        value = source.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else _CONTINUOUS_REGRESSION_RESULT_CARD_FALLBACKS[key]

    decimal_places = source.get("decimal_places")
    if not isinstance(decimal_places, int) or isinstance(decimal_places, bool) or not (0 <= decimal_places <= 6):
        decimal_places = _CONTINUOUS_REGRESSION_DECIMAL_PLACES_FALLBACK

    # Project Spec S0239: model_section_label is fixed to "Model" regardless
    # of incoming presentation copy.
    normalized = {
        "schema_version": CONTINUOUS_REGRESSION_RESULT_PRESENTATION_SCHEMA_VERSION,
        **{key: copy(key) for key in _CONTINUOUS_REGRESSION_RESULT_CARD_FALLBACKS if key != "model_section_label"},
        "model_section_label": _CONTINUOUS_REGRESSION_RESULT_CARD_FALLBACKS["model_section_label"],
        "decimal_places": decimal_places,
    }
    value_unit_label = source.get("value_unit_label")
    if isinstance(value_unit_label, str) and value_unit_label.strip():
        normalized["value_unit_label"] = value_unit_label.strip()
    return normalized


def normalize_univariate_forecasting_result_presentation(result_card: object) -> dict:
    """Return canonical copy-only univariate-forecasting presentation deterministically.

    decimal_places is bounded 0..6, defaulting when absent/invalid. The
    optional value_unit_label is presentation copy only and is included only
    when it is a non-empty string; it never carries a fallback of its own.
    Mirrors normalize_continuous_regression_result_presentation's
    deterministic/idempotent normalization discipline exactly.
    """
    source = result_card if isinstance(result_card, dict) else {}

    def copy(key: str) -> str:
        value = source.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else _UNIVARIATE_FORECASTING_RESULT_CARD_FALLBACKS[key]

    decimal_places = source.get("decimal_places")
    if not isinstance(decimal_places, int) or isinstance(decimal_places, bool) or not (0 <= decimal_places <= 6):
        decimal_places = _UNIVARIATE_FORECASTING_DECIMAL_PLACES_FALLBACK

    # Project Spec S0239-style discipline (extended by S0249): model_section_label
    # is fixed to "Model" regardless of incoming presentation copy.
    normalized = {
        "schema_version": UNIVARIATE_FORECASTING_RESULT_PRESENTATION_SCHEMA_VERSION,
        **{key: copy(key) for key in _UNIVARIATE_FORECASTING_RESULT_CARD_FALLBACKS if key != "model_section_label"},
        "model_section_label": _UNIVARIATE_FORECASTING_RESULT_CARD_FALLBACKS["model_section_label"],
        "decimal_places": decimal_places,
    }
    value_unit_label = source.get("value_unit_label")
    if isinstance(value_unit_label, str) and value_unit_label.strip():
        normalized["value_unit_label"] = value_unit_label.strip()
    return normalized


def normalize_result_presentation(result_card: object, expected_problem_type: str | None = None) -> dict:
    """Dispatch only from trusted problem type or the governed schema version."""
    if expected_problem_type == "multiclass_classification":
        return normalize_multiclass_result_presentation(result_card)
    if expected_problem_type == "continuous_regression":
        return normalize_continuous_regression_result_presentation(result_card)
    if expected_problem_type == "univariate_forecasting":
        return normalize_univariate_forecasting_result_presentation(result_card)
    if expected_problem_type == "binary_classification":
        return normalize_binary_result_presentation(result_card)
    if isinstance(result_card, dict) and result_card.get("schema_version") == MULTICLASS_RESULT_PRESENTATION_SCHEMA_VERSION:
        return normalize_multiclass_result_presentation(result_card)
    if isinstance(result_card, dict) and result_card.get("schema_version") == CONTINUOUS_REGRESSION_RESULT_PRESENTATION_SCHEMA_VERSION:
        return normalize_continuous_regression_result_presentation(result_card)
    if isinstance(result_card, dict) and result_card.get("schema_version") == UNIVARIATE_FORECASTING_RESULT_PRESENTATION_SCHEMA_VERSION:
        return normalize_univariate_forecasting_result_presentation(result_card)
    return normalize_binary_result_presentation(result_card)


def _err(code: str, field: str | None, message: str) -> dict:
    return {"code": code, "field": field, "message": message}


def validate_profile_references(
    profile: dict,
    predict_views_registry: dict,
    release_metrics: dict,
    expected_problem_type: str | None = None,
) -> dict:
    """
    Validate a dataset public profile draft's reference fields.

    Returns {"valid": bool, "errors": [{"code": str, "field": str|None, "message": str}]}.
    Accumulates all errors before returning -- does not short-circuit on the first error.

    predict_views_registry must contain a "predict_views" list; each entry must
    have "view_id" and "dataset_slug" fields. The caller is responsible for
    loading registry/predict-views.json before invoking this function.

    release_metrics must be the relevant release's metrics artifact dict,
    containing an "evaluation" object with a "metrics" object keyed by metric
    name. The caller is responsible for resolving and loading the relevant
    release's metrics.json before invoking this function; this validator does
    not select a release itself.

    expected_problem_type (Project Spec S0240, extended by S0249) is a
    bounded, optional trusted input -- one of "binary_classification",
    "multiclass_classification", "continuous_regression", or
    "univariate_forecasting" -- supplied by a caller that has already resolved
    it from a trusted source (e.g. an active release's governed result
    semantics). When omitted (the existing private draft validation call
    site), performance_focus applicability is not checked against a problem
    type, preserving prior behavior exactly. When supplied and recognized, a
    known performance_focus.focus_id that is not applicable to that problem
    type is rejected with PERFORMANCE_FOCUS_PROBLEM_TYPE_MISMATCH; this never
    replaces the existing PERFORMANCE_FOCUS_UNKNOWN behavior for an
    unrecognized focus_id, and never changes score-level vocabulary checks.
    """
    errors: list[dict] = []

    if not isinstance(profile, dict):
        errors.append(_err(
            "PROFILE_NOT_AN_OBJECT",
            None,
            "Profile must be a JSON object.",
        ))
        return {"valid": False, "errors": errors}

    dataset_slug = profile.get("dataset_slug")

    inference_presentation = profile.get("inference_presentation")
    if isinstance(inference_presentation, dict):
        bound_predict_view_id = inference_presentation.get("bound_predict_view_id")
        if isinstance(bound_predict_view_id, str) and bound_predict_view_id:
            predict_views = (
                predict_views_registry.get("predict_views")
                if isinstance(predict_views_registry, dict)
                else None
            )
            if not isinstance(predict_views, list):
                predict_views = []

            matched_view = None
            view_id_exists_for_other_dataset = False
            for view in predict_views:
                if not isinstance(view, dict):
                    continue
                if view.get("view_id") != bound_predict_view_id:
                    continue
                if view.get("dataset_slug") == dataset_slug:
                    matched_view = view
                    break
                view_id_exists_for_other_dataset = True

            if matched_view is None:
                if view_id_exists_for_other_dataset:
                    errors.append(_err(
                        "BOUND_PREDICT_VIEW_DATASET_MISMATCH",
                        "inference_presentation.bound_predict_view_id",
                        "inference_presentation.bound_predict_view_id references a predict view bound to a different dataset.",
                    ))
                else:
                    errors.append(_err(
                        "BOUND_PREDICT_VIEW_NOT_FOUND",
                        "inference_presentation.bound_predict_view_id",
                        "inference_presentation.bound_predict_view_id does not reference an existing predict view.",
                    ))

    home_card = profile.get("home_card")
    if isinstance(home_card, dict):
        primary_metric_key = home_card.get("primary_metric_key")
        if isinstance(primary_metric_key, str) and primary_metric_key:
            evaluation = (
                release_metrics.get("evaluation")
                if isinstance(release_metrics, dict)
                else None
            )
            metrics = evaluation.get("metrics") if isinstance(evaluation, dict) else None
            if not isinstance(metrics, dict):
                metrics = {}

            if primary_metric_key not in metrics:
                errors.append(_err(
                    "PRIMARY_METRIC_KEY_NOT_FOUND",
                    "home_card.primary_metric_key",
                    "home_card.primary_metric_key does not reference an existing release metric.",
                ))

    performance_focus = profile.get("performance_focus")
    if isinstance(performance_focus, dict):
        focus_id = performance_focus.get("focus_id")
        catalog = PERFORMANCE_SCORE_CATALOG.get(focus_id)
        if catalog is None:
            errors.append(_err(
                "PERFORMANCE_FOCUS_UNKNOWN",
                "performance_focus.focus_id",
                "performance_focus.focus_id is not supported.",
            ))
            catalog = {}
        elif expected_problem_type is not None:
            applicable_problem_types = PERFORMANCE_FOCUS_PROBLEM_TYPES.get(focus_id)
            if applicable_problem_types is not None and expected_problem_type not in applicable_problem_types:
                errors.append(_err(
                    "PERFORMANCE_FOCUS_PROBLEM_TYPE_MISMATCH",
                    "performance_focus.focus_id",
                    "performance_focus.focus_id is not supported for the governed problem type.",
                ))

        visible_scores = performance_focus.get("visible_scores")
        seen_ids: set[str] = set()
        seen_orders: set[int] = set()
        if isinstance(visible_scores, list):
            for index, score in enumerate(visible_scores):
                if not isinstance(score, dict):
                    continue
                score_id = score.get("score_id")
                field = f"performance_focus.visible_scores.{index}"
                if isinstance(score_id, str):
                    if score_id in seen_ids:
                        errors.append(_err(
                            "PERFORMANCE_SCORE_DUPLICATE",
                            f"{field}.score_id",
                            "Visible performance score identifiers must be unique.",
                        ))
                    seen_ids.add(score_id)
                    expected_label = catalog.get(score_id)
                    if expected_label is None:
                        errors.append(_err(
                            "PERFORMANCE_SCORE_NOT_SUPPORTED_FOR_FOCUS",
                            f"{field}.score_id",
                            "Visible score is not supported for the selected performance focus.",
                        ))
                    elif score.get("display_label") != expected_label:
                        errors.append(_err(
                            "PERFORMANCE_SCORE_LABEL_INVALID",
                            f"{field}.display_label",
                            "Visible score label must use the safe catalog label.",
                        ))
                order = score.get("order")
                if isinstance(order, int) and not isinstance(order, bool):
                    if order in seen_orders:
                        errors.append(_err(
                            "PERFORMANCE_SCORE_ORDER_DUPLICATE",
                            f"{field}.order",
                            "Visible performance score ordering values must be unique.",
                        ))
                    seen_orders.add(order)

        highlighted_score_id = performance_focus.get("highlighted_score_id")
        if not isinstance(highlighted_score_id, str) or not highlighted_score_id:
            errors.append(_err(
                "PERFORMANCE_HIGHLIGHT_EMPTY",
                "performance_focus.highlighted_score_id",
                "A highlighted performance score identifier is required.",
            ))
        elif highlighted_score_id not in seen_ids:
            errors.append(_err(
                "PERFORMANCE_HIGHLIGHT_NOT_VISIBLE",
                "performance_focus.highlighted_score_id",
                "The highlighted performance score must be visible.",
            ))

    return {"valid": len(errors) == 0, "errors": errors}
