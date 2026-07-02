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


def _err(code: str, field: str | None, message: str) -> dict:
    return {"code": code, "field": field, "message": message}


def validate_profile_references(
    profile: dict,
    predict_views_registry: dict,
    release_metrics: dict,
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
            for view in predict_views:
                if not isinstance(view, dict):
                    continue
                if view.get("view_id") == bound_predict_view_id:
                    matched_view = view
                    break

            if matched_view is None:
                errors.append(_err(
                    "BOUND_PREDICT_VIEW_NOT_FOUND",
                    "inference_presentation.bound_predict_view_id",
                    "inference_presentation.bound_predict_view_id does not reference an existing predict view.",
                ))
            elif matched_view.get("dataset_slug") != dataset_slug:
                errors.append(_err(
                    "BOUND_PREDICT_VIEW_DATASET_MISMATCH",
                    "inference_presentation.bound_predict_view_id",
                    "inference_presentation.bound_predict_view_id references a predict view bound to a different dataset.",
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

    return {"valid": len(errors) == 0, "errors": errors}
