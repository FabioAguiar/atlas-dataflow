from dataclasses import dataclass
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

_MESSAGES = {
    MISSING_REQUIRED_FIELD: "A required field is missing from the inference payload.",
    TYPE_MISMATCH: "The value provided for this field is not the expected type.",
    DOMAIN_VIOLATION: "The value provided for this field is outside the accepted domain.",
}

_VIOLATIONS = {
    MISSING_REQUIRED_FIELD: "missing_required_field",
    TYPE_MISMATCH: "type_mismatch",
    DOMAIN_VIOLATION: "domain_violation",
}


def _failure(error_code: str, field: str) -> ValidationFailure:
    return ValidationFailure(
        error_code=error_code,
        message=_MESSAGES[error_code],
        field=field,
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


def _value_matches_type(value: Any, feature_type: str) -> bool:
    if feature_type == "numeric":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if feature_type == "categorical":
        return isinstance(value, str)
    if feature_type == "boolean":
        return isinstance(value, bool)
    return False


def _violates_domain(value: Any, feature: dict[str, Any]) -> bool:
    feature_type = feature.get("type")
    domain_constraints = feature.get("domain_constraints")
    if not isinstance(domain_constraints, dict):
        return False

    if feature_type == "numeric":
        minimum = domain_constraints.get("min")
        maximum = domain_constraints.get("max")
        if isinstance(minimum, (int, float)) and not isinstance(minimum, bool):
            if value < minimum:
                return True
        if isinstance(maximum, (int, float)) and not isinstance(maximum, bool):
            if value > maximum:
                return True
        return False

    if feature_type == "categorical":
        values = domain_constraints.get("values")
        if isinstance(values, list):
            return value not in values
        return False

    return False


def validate_payload(
    payload: dict[str, Any],
    runtime_contract: dict[str, Any],
) -> list[ValidationFailure]:
    """
    Validate an inference payload against the active-release runtime contract.

    Implements phases 2, 3, and 4 from the payload validation rules. Contract
    availability is handled before this function by the runtime contract loader.
    """
    features = _feature_map(runtime_contract)

    missing_required = [
        _failure(MISSING_REQUIRED_FIELD, name)
        for name, feature in features.items()
        if feature.get("required", True) is True and name not in payload
    ]
    if missing_required:
        return missing_required

    type_failures: list[ValidationFailure] = []
    type_valid_fields: list[tuple[str, Any, dict[str, Any]]] = []
    for name, value in payload.items():
        feature = features.get(name)
        if feature is None:
            continue
        feature_type = feature.get("type")
        if not isinstance(feature_type, str) or not _value_matches_type(value, feature_type):
            type_failures.append(_failure(TYPE_MISMATCH, name))
            continue
        type_valid_fields.append((name, value, feature))

    if type_failures:
        return type_failures

    domain_failures = [
        _failure(DOMAIN_VIOLATION, name)
        for name, value, feature in type_valid_fields
        if _violates_domain(value, feature)
    ]
    if domain_failures:
        return domain_failures

    return []
