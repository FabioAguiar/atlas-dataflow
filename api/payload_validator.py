import math
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ValidationFailure:
    error_code: str
    message: str
    field: str
    violation: str

    def as_public_error(self) -> dict[str, str]:
        return {
            "error_type": "validation_error",
            "error_code": self.error_code,
            "message": self.message,
            "field": self.field,
            "violation": self.violation,
        }


MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
TYPE_MISMATCH = "TYPE_MISMATCH"
DOMAIN_VIOLATION = "DOMAIN_VIOLATION"

# Project Spec S0156: a blank representation that violates its declared
# conditional policy. Distinct from MISSING_REQUIRED_FIELD (the key itself is
# present), TYPE_MISMATCH (the value is a well-formed blank-after-trim
# string), and generic DOMAIN_VIOLATION (this is a cross-field condition
# failure, not a single-field domain bound).
CONDITIONAL_BLANK_REJECTED = "CONDITIONAL_BLANK_REJECTED"

# Project Spec S0246: closed forecasting history-series payload error
# vocabulary. Distinct from the scalar-feature codes above so a forecasting
# validation failure is never confused with a scalar-feature one.
FORECASTING_UNKNOWN_TOP_LEVEL_FIELD = "FORECASTING_UNKNOWN_TOP_LEVEL_FIELD"
FORECASTING_INVALID_HISTORY_SHAPE = "FORECASTING_INVALID_HISTORY_SHAPE"
FORECASTING_INVALID_HISTORY_ROW = "FORECASTING_INVALID_HISTORY_ROW"
FORECASTING_INVALID_TIME_INDEX = "FORECASTING_INVALID_TIME_INDEX"
FORECASTING_INVALID_TARGET_VALUE = "FORECASTING_INVALID_TARGET_VALUE"
FORECASTING_MINIMUM_HISTORY_NOT_MET = "FORECASTING_MINIMUM_HISTORY_NOT_MET"

_MESSAGES = {
    MISSING_REQUIRED_FIELD: "A required field is missing from the inference payload.",
    TYPE_MISMATCH: "The value provided for this field is not the expected type.",
    DOMAIN_VIOLATION: "The value provided for this field is outside the accepted domain.",
    CONDITIONAL_BLANK_REJECTED: (
        "A blank value for this field is only accepted when its declared condition holds."
    ),
    FORECASTING_UNKNOWN_TOP_LEVEL_FIELD: (
        "The inference payload must contain exactly the configured history container key."
    ),
    FORECASTING_INVALID_HISTORY_SHAPE: (
        "The history value must be a non-empty ordered list of rows."
    ),
    FORECASTING_INVALID_HISTORY_ROW: (
        "Each history row must be an object with exactly the governed time-index and target keys."
    ),
    FORECASTING_INVALID_TIME_INDEX: (
        "History time-index values must be valid, unique, strictly increasing, and frequency-contiguous."
    ),
    FORECASTING_INVALID_TARGET_VALUE: "History target values must be finite numeric values.",
    FORECASTING_MINIMUM_HISTORY_NOT_MET: (
        "The supplied history does not reach the required minimum historical coverage."
    ),
}

_VIOLATIONS = {
    MISSING_REQUIRED_FIELD: "missing_required_field",
    TYPE_MISMATCH: "type_mismatch",
    DOMAIN_VIOLATION: "domain_violation",
    CONDITIONAL_BLANK_REJECTED: "conditional_blank_rejected",
    FORECASTING_UNKNOWN_TOP_LEVEL_FIELD: "forecasting_unknown_top_level_field",
    FORECASTING_INVALID_HISTORY_SHAPE: "forecasting_invalid_history_shape",
    FORECASTING_INVALID_HISTORY_ROW: "forecasting_invalid_history_row",
    FORECASTING_INVALID_TIME_INDEX: "forecasting_invalid_time_index",
    FORECASTING_INVALID_TARGET_VALUE: "forecasting_invalid_target_value",
    FORECASTING_MINIMUM_HISTORY_NOT_MET: "forecasting_minimum_history_not_met",
}

# Project Spec S0156: the sole non-fatal input observation code. An
# observation carries only `code` and `field` -- never the submitted value,
# the known-value list, model details, contract paths, exception text, or a
# stack trace.
UNKNOWN_CATEGORY_ACCEPTED = "UNKNOWN_CATEGORY_ACCEPTED"


@dataclass(frozen=True)
class ValidationReport:
    """Project Spec S0156: the bounded typed result of validating and
    normalizing an inference payload against a runtime contract.

    `normalized_payload` is always a fresh mapping -- the caller's original
    payload object is never mutated. `observations` is a bounded, non-fatal
    list of {"code", "field"} dicts (currently only UNKNOWN_CATEGORY_ACCEPTED).
    """

    failures: list[ValidationFailure] = field(default_factory=list)
    normalized_payload: dict[str, Any] = field(default_factory=dict)
    observations: list[dict[str, str]] = field(default_factory=list)


def _failure(error_code: str, field_name: str) -> ValidationFailure:
    return ValidationFailure(
        error_code=error_code,
        message=_MESSAGES[error_code],
        field=field_name,
        violation=_VIOLATIONS[error_code],
    )


def _feature_map(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    features = contract.get("features")
    if not isinstance(features, list):
        return {}

    mapped: dict[str, dict[str, Any]] = {}
    for feature in features:
        if not isinstance(feature, dict):
            continue
        name = feature.get("name")
        if isinstance(name, str) and name:
            mapped[name] = feature
    return mapped


# ---------------------------------------------------------------------------
# Project Spec S0156: categorical scalar-type/known-value/validation-behavior
# helpers. Deliberately duplicated (not imported) from
# pipeline/contract_derivation.py's equivalent helpers -- api/ and pipeline/
# are separate architectural layers and this module stays self-contained
# rather than introducing a new api -> pipeline dependency for a handful of
# small, stable rules.
# ---------------------------------------------------------------------------


def _categorical_scalar_type(domain_constraints: Any) -> str:
    if not isinstance(domain_constraints, dict):
        return "string"
    declared = domain_constraints.get("categorical_value_type")
    if declared in ("string", "integer"):
        return declared
    return "string"


def _categorical_known_values(domain_constraints: Any) -> list[Any] | None:
    if not isinstance(domain_constraints, dict):
        return None
    known_values = domain_constraints.get("known_values")
    if known_values is not None:
        return known_values
    return domain_constraints.get("values")


def _categorical_validation_behavior(domain_constraints: Any) -> str:
    if not isinstance(domain_constraints, dict):
        return "reject_unknown"
    behavior = domain_constraints.get("validation_behavior")
    if behavior in ("reject_unknown", "ignore_and_report"):
        return behavior
    return "reject_unknown"


def _categorical_value_matches_scalar_type(value: Any, scalar_type: str) -> bool:
    if scalar_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, str)


def _value_matches_type(value: Any, feature_type: str, feature: dict[str, Any] | None = None) -> bool:
    if feature_type == "numeric":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if feature_type == "categorical":
        scalar_type = _categorical_scalar_type((feature or {}).get("domain_constraints"))
        return _categorical_value_matches_scalar_type(value, scalar_type)
    if feature_type == "boolean":
        return isinstance(value, bool)
    return False


def _violates_numeric_domain(value: Any, domain_constraints: Any) -> bool:
    if not isinstance(domain_constraints, dict):
        return False
    minimum = domain_constraints.get("min")
    maximum = domain_constraints.get("max")
    if isinstance(minimum, (int, float)) and not isinstance(minimum, bool):
        if value < minimum:
            return True
    if isinstance(maximum, (int, float)) and not isinstance(maximum, bool):
        if value > maximum:
            return True
    return False


def _violates_domain(value: Any, feature: dict[str, Any]) -> bool:
    """Retained for backward compatibility with any existing direct caller.
    Only covers numeric bounds and the legacy closed-categorical case
    (reject_unknown with no observation reporting) -- validate_and_normalize
    below is the governed path for full Project Spec S0156 categorical
    behavior (ignore_and_report + UNKNOWN_CATEGORY_ACCEPTED observations).
    """
    feature_type = feature.get("type")
    domain_constraints = feature.get("domain_constraints")

    if feature_type == "numeric":
        return _violates_numeric_domain(value, domain_constraints)

    if feature_type == "categorical":
        if _categorical_validation_behavior(domain_constraints) != "reject_unknown":
            return False
        known_values = _categorical_known_values(domain_constraints)
        if isinstance(known_values, list):
            return value not in known_values
        return False

    return False


_BLANK_REPRESENTATION = "blank_string_after_trim"


def _condition_holds(payload: dict[str, Any], when: dict[str, Any]) -> bool:
    """Strict, type-aware equality check for a single equality_condition
    (Project Spec S0156). Never coerces across types (e.g. 0 != False)."""
    ref_field = when.get("field")
    expected = when.get("value")
    if not isinstance(ref_field, str) or ref_field not in payload:
        return False
    actual = payload[ref_field]

    if isinstance(expected, bool) or isinstance(actual, bool):
        return isinstance(actual, bool) and isinstance(expected, bool) and actual == expected
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return actual == expected
    if isinstance(expected, str) and isinstance(actual, str):
        return actual == expected
    return False


def _apply_conditional_blank_normalization(
    payload: dict[str, Any],
    features: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[ValidationFailure]]:
    """Project Spec S0156, validator processing phase 3. Returns a NEW
    normalized payload (the input `payload` is never mutated) and any
    conditional-blank failures. JSON null is never reclassified as an
    accepted blank representation -- only string values are inspected here.
    """
    normalized = dict(payload)
    failures: list[ValidationFailure] = []

    for name, feature in features.items():
        if name not in payload:
            continue
        input_policy = feature.get("input_policy")
        conditional = (
            input_policy.get("conditional_blank_normalization")
            if isinstance(input_policy, dict)
            else None
        )
        if not isinstance(conditional, dict):
            continue
        if conditional.get("accepted_representation") != _BLANK_REPRESENTATION:
            continue

        value = payload[name]
        if not isinstance(value, str) or value.strip() != "":
            continue  # not a blank-after-trim string; not this policy's concern

        when = conditional.get("when")
        if isinstance(when, dict) and _condition_holds(payload, when):
            normalized[name] = conditional.get("materialized_value")
        else:
            failures.append(_failure(CONDITIONAL_BLANK_REJECTED, name))

    return normalized, failures


# ---------------------------------------------------------------------------
# Project Spec S0246: forecasting history-series payload validation. Dispatch
# happens only when the validated runtime contract declares the exact
# forecasting v2 identity -- never inferred from the payload itself. Never
# sorts, fills, interpolates, deduplicates, coerces an invalid horizon, or
# invents periods.
# ---------------------------------------------------------------------------

# Bounded, dataset-neutral logical-frequency -> pandas frequency alias table.
# The persisted runtime contract's `frequency` value is never a pandas alias
# itself; this internal adapter is the only place that vocabulary is
# consulted, and only to interpret calendar_period/timestamp history values.
# A declared frequency absent from this table fails closed rather than
# silently substituting a default cadence.
_LOGICAL_FREQUENCY_ALIASES = {
    "daily": "D",
    "weekly": "W",
    "monthly": "M",
    "quarterly": "Q",
    "annual": "A",
    "yearly": "A",
    "hourly": "H",
}


def _resolve_pandas_frequency_alias(frequency: Any) -> str | None:
    if not isinstance(frequency, str):
        return None
    return _LOGICAL_FREQUENCY_ALIASES.get(frequency.strip().lower())


def _resolve_history_series_block(runtime_contract: dict[str, Any]) -> dict[str, Any] | None:
    """Returns the forecasting history_series/forecast blocks only when the
    runtime contract declares the exact forecasting v2 identity; otherwise
    None (dispatch falls back to scalar-feature validation)."""
    if not isinstance(runtime_contract, dict):
        return None
    if runtime_contract.get("schema_version") != "2.0.0":
        return None
    if runtime_contract.get("problem_type") != "univariate_forecasting":
        return None
    if runtime_contract.get("payload_shape") != "history_series":
        return None
    history_series = runtime_contract.get("history_series")
    forecast = runtime_contract.get("forecast")
    if not isinstance(history_series, dict) or not isinstance(forecast, dict):
        return None
    return {"history_series": history_series, "forecast": forecast}


def _parse_and_normalize_index_value(
    value: Any, index_kind: str | None, pandas_freq_alias: str | None
) -> tuple[Any, Any, bool]:
    """Strictly parse one caller-supplied history row's time-index value.

    Returns (comparable_parsed_value, canonical_normalized_value, ok). Only
    ever accepts the exact JSON type the governed index kind requires --
    never a caller-supplied string masquerading as an ordinal integer.
    """
    if index_kind == "ordinal_time":
        if isinstance(value, bool) or not isinstance(value, int):
            return None, None, False
        return value, value, True

    if index_kind == "calendar_period":
        if not isinstance(value, str) or not value.strip() or pandas_freq_alias is None:
            return None, None, False
        try:
            import pandas as pd

            period = pd.Period(value, freq=pandas_freq_alias)
        except (ValueError, TypeError):
            return None, None, False
        return period, str(period), True

    if index_kind == "timestamp":
        if not isinstance(value, str) or not value.strip() or pandas_freq_alias is None:
            return None, None, False
        try:
            import pandas as pd

            timestamp = pd.Timestamp(value)
        except (ValueError, TypeError):
            return None, None, False
        return timestamp, timestamp.isoformat(), True

    return None, None, False


def _parse_governed_boundary_value(
    value: Any, index_kind: str | None, pandas_freq_alias: str | None
) -> tuple[Any, bool]:
    """Parse the runtime contract's own governed
    `minimum_history_required_through` boundary value. Distinct from
    `_parse_and_normalize_index_value` because this value is always
    materialized by the trusted derivation pipeline (Project Spec S0246
    Section B) as a reduced string boundary label -- including for
    ordinal_time, where it is a digit string rather than a JSON integer --
    never caller-supplied payload data."""
    if index_kind == "ordinal_time":
        if isinstance(value, bool):
            return None, False
        if isinstance(value, int):
            return value, True
        if isinstance(value, str) and value.strip():
            try:
                return int(value.strip()), True
            except ValueError:
                return None, False
        return None, False

    if index_kind in ("calendar_period", "timestamp"):
        if not isinstance(value, str) or not value.strip() or pandas_freq_alias is None:
            return None, False
        try:
            import pandas as pd

            if index_kind == "calendar_period":
                return pd.Period(value, freq=pandas_freq_alias), True
            return pd.Timestamp(value), True
        except (ValueError, TypeError):
            return None, False

    return None, False


def _index_value_is_contiguous_successor(
    previous_value: Any, current_value: Any, index_kind: str | None, pandas_freq_alias: str | None
) -> bool:
    """A single check that simultaneously enforces strict increase,
    uniqueness, and frequency-contiguous stepping -- any duplicate,
    out-of-order, or gapped pair fails this check."""
    if index_kind == "ordinal_time":
        return current_value - previous_value == 1
    if index_kind == "calendar_period":
        return current_value == previous_value + 1
    if index_kind == "timestamp":
        try:
            import pandas as pd

            offset = pd.tseries.frequencies.to_offset(pandas_freq_alias)
        except (ValueError, TypeError):
            return False
        return previous_value + offset == current_value
    return False


def _validate_and_normalize_forecasting_payload(
    payload: Any,
    history_series: dict[str, Any],
    forecast: dict[str, Any],
) -> ValidationReport:
    container_key = history_series.get("container_key") or "history"

    if not isinstance(payload, dict):
        return ValidationReport(
            failures=[_failure(TYPE_MISMATCH, "payload")], normalized_payload={}, observations=[]
        )

    unexpected_keys = sorted(key for key in payload.keys() if key != container_key)
    if unexpected_keys:
        return ValidationReport(
            failures=[_failure(FORECASTING_UNKNOWN_TOP_LEVEL_FIELD, unexpected_keys[0])],
            normalized_payload=dict(payload),
            observations=[],
        )

    if container_key not in payload:
        return ValidationReport(
            failures=[_failure(MISSING_REQUIRED_FIELD, container_key)],
            normalized_payload=dict(payload),
            observations=[],
        )

    history = payload[container_key]
    minimum_observation_count = history_series.get("minimum_observation_count")
    if not isinstance(history, list) or len(history) == 0:
        return ValidationReport(
            failures=[_failure(FORECASTING_INVALID_HISTORY_SHAPE, container_key)],
            normalized_payload=dict(payload),
            observations=[],
        )
    if isinstance(minimum_observation_count, int) and len(history) < minimum_observation_count:
        return ValidationReport(
            failures=[_failure(FORECASTING_INVALID_HISTORY_SHAPE, container_key)],
            normalized_payload=dict(payload),
            observations=[],
        )

    time_field = history_series.get("time_index_field_name")
    target_field = history_series.get("target_field_name")
    index_kind = history_series.get("index_value_kind")
    frequency = history_series.get("frequency")
    expected_keys = {time_field, target_field}

    pandas_freq_alias = (
        _resolve_pandas_frequency_alias(frequency) if index_kind != "ordinal_time" else None
    )
    if index_kind in ("calendar_period", "timestamp") and pandas_freq_alias is None:
        return ValidationReport(
            failures=[_failure(FORECASTING_INVALID_TIME_INDEX, f"{container_key}.frequency")],
            normalized_payload=dict(payload),
            observations=[],
        )

    normalized_rows: list[dict[str, Any]] = []
    parsed_index_values: list[Any] = []
    for row_index, row in enumerate(history):
        field_path = f"{container_key}[{row_index}]"
        if not isinstance(row, dict) or set(row.keys()) != expected_keys:
            return ValidationReport(
                failures=[_failure(FORECASTING_INVALID_HISTORY_ROW, field_path)],
                normalized_payload=dict(payload),
                observations=[],
            )

        target_value = row[target_field]
        if (
            isinstance(target_value, bool)
            or not isinstance(target_value, (int, float))
            or not math.isfinite(target_value)
        ):
            return ValidationReport(
                failures=[_failure(FORECASTING_INVALID_TARGET_VALUE, f"{field_path}.{target_field}")],
                normalized_payload=dict(payload),
                observations=[],
            )

        raw_time_value = row[time_field]
        parsed_time_value, normalized_time_value, ok = _parse_and_normalize_index_value(
            raw_time_value, index_kind, pandas_freq_alias
        )
        if not ok:
            return ValidationReport(
                failures=[_failure(FORECASTING_INVALID_TIME_INDEX, f"{field_path}.{time_field}")],
                normalized_payload=dict(payload),
                observations=[],
            )

        parsed_index_values.append(parsed_time_value)
        normalized_rows.append({time_field: normalized_time_value, target_field: target_value})

    for row_index in range(1, len(parsed_index_values)):
        previous_value = parsed_index_values[row_index - 1]
        current_value = parsed_index_values[row_index]
        if not _index_value_is_contiguous_successor(previous_value, current_value, index_kind, pandas_freq_alias):
            return ValidationReport(
                failures=[_failure(FORECASTING_INVALID_TIME_INDEX, f"{container_key}[{row_index}].{time_field}")],
                normalized_payload=dict(payload),
                observations=[],
            )

    minimum_boundary_raw = history_series.get("minimum_history_required_through")
    minimum_boundary_parsed, boundary_ok = _parse_governed_boundary_value(
        minimum_boundary_raw, index_kind, pandas_freq_alias
    )
    last_parsed_value = parsed_index_values[-1]
    if not boundary_ok or last_parsed_value < minimum_boundary_parsed:
        return ValidationReport(
            failures=[_failure(FORECASTING_MINIMUM_HISTORY_NOT_MET, container_key)],
            normalized_payload=dict(payload),
            observations=[],
        )

    return ValidationReport(
        failures=[], normalized_payload={container_key: normalized_rows}, observations=[]
    )


def validate_and_normalize_payload(
    payload: dict[str, Any],
    runtime_contract: dict[str, Any],
) -> ValidationReport:
    """
    Validate and normalize an inference payload against the active-release
    runtime contract (Project Spec S0156; Project Spec S0246 forecasting
    dispatch).

    Project Spec S0246: forecasting history-series validation is dispatched
    first, only when the validated runtime contract declares the exact
    forecasting v2 identity (`schema_version` "2.0.0",
    `problem_type` "univariate_forecasting", `payload_shape` "history_series").
    Every other runtime contract falls through unchanged to the historical
    scalar-feature processing below.

    Scalar-feature processing order:
      1. contract feature-map validation
      2. required-key presence
      3. conditional blank normalization for explicitly declared policies
      4. primitive/scalar type validation
      5. numeric domain validation
      6. categorical known-value behavior
      7. bounded observations

    Never mutates `payload` -- `normalized_payload` is always a fresh dict.
    """
    forecasting_blocks = _resolve_history_series_block(runtime_contract)
    if forecasting_blocks is not None:
        return _validate_and_normalize_forecasting_payload(
            payload, forecasting_blocks["history_series"], forecasting_blocks["forecast"]
        )

    features = _feature_map(runtime_contract)

    missing_required = [
        _failure(MISSING_REQUIRED_FIELD, name)
        for name, feature in features.items()
        if feature.get("required", True) is True and name not in payload
    ]
    if missing_required:
        return ValidationReport(
            failures=missing_required, normalized_payload=dict(payload), observations=[]
        )

    normalized, conditional_failures = _apply_conditional_blank_normalization(payload, features)
    if conditional_failures:
        return ValidationReport(
            failures=conditional_failures, normalized_payload=normalized, observations=[]
        )

    type_failures: list[ValidationFailure] = []
    type_valid_fields: list[tuple[str, Any, dict[str, Any]]] = []
    for name, value in normalized.items():
        feature = features.get(name)
        if feature is None:
            continue
        feature_type = feature.get("type")
        if not isinstance(feature_type, str) or not _value_matches_type(value, feature_type, feature):
            type_failures.append(_failure(TYPE_MISMATCH, name))
            continue
        type_valid_fields.append((name, value, feature))

    if type_failures:
        return ValidationReport(failures=type_failures, normalized_payload=normalized, observations=[])

    domain_failures: list[ValidationFailure] = []
    observations: list[dict[str, str]] = []
    for name, value, feature in type_valid_fields:
        feature_type = feature.get("type")
        domain_constraints = feature.get("domain_constraints")

        if feature_type == "numeric":
            if _violates_numeric_domain(value, domain_constraints):
                domain_failures.append(_failure(DOMAIN_VIOLATION, name))
            continue

        if feature_type == "categorical":
            known_values = _categorical_known_values(domain_constraints)
            if not isinstance(known_values, list):
                continue  # fully open categorical: no declared domain at all
            if value in known_values:
                continue
            behavior = _categorical_validation_behavior(domain_constraints)
            if behavior == "ignore_and_report":
                observations.append({"code": UNKNOWN_CATEGORY_ACCEPTED, "field": name})
            else:
                domain_failures.append(_failure(DOMAIN_VIOLATION, name))

    if domain_failures:
        return ValidationReport(failures=domain_failures, normalized_payload=normalized, observations=[])

    return ValidationReport(failures=[], normalized_payload=normalized, observations=observations)


def validate_payload(
    payload: dict[str, Any],
    runtime_contract: dict[str, Any],
) -> list[ValidationFailure]:
    """
    Compatibility wrapper preserving the pre-S0156 call surface: validate an
    inference payload against the active-release runtime contract and return
    only the list of validation failures. Governed callers that need the
    normalized payload or bounded observations should call
    validate_and_normalize_payload directly.
    """
    return validate_and_normalize_payload(payload, runtime_contract).failures
