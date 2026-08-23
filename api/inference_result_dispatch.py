"""Governed API inference-result validation dispatch.

The expected result family comes only from the active release's normalized
``project_result_contract`` semantics.  The returned result is never used to
select its own validator.
"""

from __future__ import annotations

from typing import Any, Mapping

from runtime.inference import (
    DIAGNOSTIC_RESULT_VALIDATION_FAILED,
    InferenceRuntimeError,
    validate_binary_classification_result,
    validate_continuous_regression_result,
    validate_multiclass_classification_result,
    validate_univariate_forecasting_result,
)


_BINARY_EXPECTED = (
    "binary-result-semantics.v1",
    "binary_classification",
    "binary-classification-result.v1",
)
_MULTICLASS_EXPECTED = (
    "multiclass-result-semantics.v1",
    "multiclass_classification",
    "multiclass-classification-result.v1",
)
_CONTINUOUS_REGRESSION_EXPECTED = (
    "continuous-regression-result-semantics.v1",
    "continuous_regression",
    "continuous-regression-result.v1",
)
# Project Spec S0246: the exact forecasting discriminator triple, routed only
# to the canonical runtime forecasting-result validator.
_FORECASTING_EXPECTED = (
    "univariate-forecasting-result-semantics.v1",
    "univariate_forecasting",
    "univariate-forecasting-result.v1",
)


def _result_validation_failure() -> InferenceRuntimeError:
    return InferenceRuntimeError(
        "Inference result validation failed.",
        diagnostic_code=DIAGNOSTIC_RESULT_VALIDATION_FAILED,
    )


def validate_inference_result(
    result: Mapping[str, Any], expected_result_contract: Mapping[str, Any]
) -> None:
    """Validate ``result`` against one closed, governed result-contract variant."""

    if not isinstance(result, Mapping) or not isinstance(expected_result_contract, Mapping):
        raise _result_validation_failure()

    discriminator = (
        expected_result_contract.get("schema_version"),
        expected_result_contract.get("problem_type"),
        expected_result_contract.get("result_schema_version"),
    )
    if discriminator == _BINARY_EXPECTED:
        expected_result_discriminator = _BINARY_EXPECTED[1:]
        validator = validate_binary_classification_result
    elif discriminator == _MULTICLASS_EXPECTED:
        expected_result_discriminator = _MULTICLASS_EXPECTED[1:]
        validator = validate_multiclass_classification_result
    elif discriminator == _CONTINUOUS_REGRESSION_EXPECTED:
        expected_result_discriminator = _CONTINUOUS_REGRESSION_EXPECTED[1:]
        validator = validate_continuous_regression_result
    elif discriminator == _FORECASTING_EXPECTED:
        expected_result_discriminator = _FORECASTING_EXPECTED[1:]
        validator = validate_univariate_forecasting_result
    else:
        raise _result_validation_failure()

    if (
        result.get("problem_type"),
        result.get("schema_version"),
    ) != expected_result_discriminator:
        raise _result_validation_failure()

    try:
        validator(result)
    except InferenceRuntimeError:
        raise
    except Exception as exc:
        raise _result_validation_failure() from exc
