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

_MESSAGES = {
    MISSING_REQUIRED_FIELD: "A required field is missing from the inference payload.",
    TYPE_MISMATCH: "The value provided for this field is not the expected type.",
    DOMAIN_VIOLATION: "The value provided for this field is outside the accepted domain.",
    CONDITIONAL_BLANK_REJECTED: (
        "A blank value for this field is only accepted when its declared condition holds."
    ),
}

_VIOLATIONS = {
    MISSING_REQUIRED_FIELD: "missing_required_field",
    TYPE_MISMATCH: "type_mismatch",
    DOMAIN_VIOLATION: "domain_violation",
    CONDITIONAL_BLANK_REJECTED: "conditional_blank_rejected",
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


def validate_and_normalize_payload(
    payload: dict[str, Any],
    runtime_contract: dict[str, Any],
) -> ValidationReport:
    """
    Validate and normalize an inference payload against the active-release
    runtime contract (Project Spec S0156).

    Processing order:
      1. contract feature-map validation
      2. required-key presence
      3. conditional blank normalization for explicitly declared policies
      4. primitive/scalar type validation
      5. numeric domain validation
      6. categorical known-value behavior
      7. bounded observations

    Never mutates `payload` -- `normalized_payload` is always a fresh dict.
    """
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
