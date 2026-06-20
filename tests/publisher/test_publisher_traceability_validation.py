import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent.parent


@dataclass(frozen=True)
class ReducedValidationError:
    validator: str
    message: str
    path: tuple[str, ...]


def _load_schema(relative_path: str) -> dict:
    return json.loads((REPO_ROOT / relative_path).read_text(encoding="utf-8"))


def _validation_errors(
    instance: dict,
    schema: dict,
    path: tuple[str, ...] = (),
) -> list[ReducedValidationError]:
    errors = []

    for field in schema.get("required", []):
        if field not in instance:
            errors.append(
                ReducedValidationError(
                    validator="required",
                    message=f"{field!r} is a required property",
                    path=path,
                )
            )

    for field, field_schema in schema.get("properties", {}).items():
        if field not in instance:
            continue
        value = instance[field]
        if "const" in field_schema and value != field_schema["const"]:
            errors.append(
                ReducedValidationError(
                    validator="const",
                    message=f"{field!r} does not match the required constant",
                    path=path + (field,),
                )
            )
        if isinstance(value, dict) and field_schema.get("type") == "object":
            errors.extend(_validation_errors(value, field_schema, path + (field,)))

    return sorted(errors, key=lambda error: error.path)


def _has_required_error(
    errors: list[ReducedValidationError],
    *,
    field: str,
    path: tuple[str, ...],
) -> bool:
    return any(
        error.validator == "required"
        and field in error.message
        and tuple(error.path) == path
        for error in errors
    )


def _has_const_error(
    errors: list[ReducedValidationError],
    *,
    path: tuple[str, ...],
) -> bool:
    return any(error.validator == "const" and tuple(error.path) == path for error in errors)


def _promotion_evidence(**overrides) -> dict:
    evidence = {
        "schema_version": "promotion-evidence.v1",
        "evidence_kind": "promotion_evidence",
        "candidate_ref": {
            "dataset_slug": "example-dataset",
            "release_id": "release-20260620-001",
            "candidate_traceability_ref": "evidence/M14/candidate-traceability.json",
        },
        "validation_result_ref": "publisher/runs/run-001/validation-result.json",
        "manifest_ref": "releases/release-20260620-001/manifest.json",
        "artifact_hashes_ref": "releases/release-20260620-001/manifest.json",
        "promotion_outcome": "promoted",
        "promotion_timestamp": "2026-06-20T11:00:00Z",
        "evidence_safety": {
            "reduced_evidence_only": True,
            "raw_logs_persisted": False,
            "raw_runtime_persisted": False,
            "raw_api_payloads_persisted": False,
            "secrets_persisted": False,
            "raw_artifact_contents_embedded": False,
        },
        "promotion_boundary_confirmations": {
            "is_registry_activation_authorized": False,
            "is_active_release_update": False,
            "is_automatic_promotion": False,
        },
    }
    evidence.update(overrides)
    return evidence


def _activation_evidence(**overrides) -> dict:
    evidence = {
        "schema_version": "registry-activation-evidence.v1",
        "evidence_kind": "registry_activation_evidence",
        "dataset_ref": {
            "dataset_slug": "example-dataset",
            "new_active_release_id": "release-20260620-001",
            "previous_active_release_id": "release-20260619-001",
        },
        "promotion_evidence_ref": "evidence/M14/promotion-evidence.json",
        "activation_timestamp": "2026-06-20T11:05:00Z",
        "evidence_safety": {
            "reduced_evidence_only": True,
            "raw_logs_persisted": False,
            "raw_runtime_persisted": False,
            "raw_api_payloads_persisted": False,
            "secrets_persisted": False,
            "raw_artifact_contents_embedded": False,
        },
        "activation_boundary_confirmations": {
            "is_public_registry_entry": False,
            "is_automatic_activation": False,
            "exposes_internal_evidence_publicly": False,
        },
    }
    evidence.update(overrides)
    return evidence


def _validate_promotion_references(
    promotion: dict,
    candidate_traceability_by_ref: dict[str, dict],
) -> dict:
    candidate_ref = promotion["candidate_ref"]
    traceability_ref = candidate_ref.get("candidate_traceability_ref")
    if traceability_ref is None:
        return {"valid": True, "reason_code": None}

    traceability = candidate_traceability_by_ref.get(traceability_ref)
    if traceability is None:
        return {"valid": False, "reason_code": "candidate_traceability_missing"}
    if traceability["candidate_identity"]["dataset_slug"] != candidate_ref["dataset_slug"]:
        return {"valid": False, "reason_code": "candidate_dataset_mismatch"}
    if traceability["candidate_identity"]["release_id"] != candidate_ref["release_id"]:
        return {"valid": False, "reason_code": "candidate_release_mismatch"}
    if promotion["artifact_hashes_ref"] != promotion["manifest_ref"]:
        return {"valid": False, "reason_code": "artifact_hash_manifest_mismatch"}

    return {"valid": True, "reason_code": None}


def _validate_activation_reference(
    activation: dict,
    promotion_by_ref: dict[str, dict],
) -> dict:
    promotion_ref = activation["promotion_evidence_ref"]
    promotion = promotion_by_ref.get(promotion_ref)
    if promotion is None:
        return {"valid": False, "reason_code": "promotion_evidence_missing"}
    if promotion["candidate_ref"]["dataset_slug"] != activation["dataset_ref"]["dataset_slug"]:
        return {"valid": False, "reason_code": "activation_dataset_mismatch"}
    if promotion["candidate_ref"]["release_id"] != activation["dataset_ref"]["new_active_release_id"]:
        return {"valid": False, "reason_code": "activation_release_mismatch"}
    if _parse_utc(activation["activation_timestamp"]) < _parse_utc(
        promotion["promotion_timestamp"],
    ):
        return {"valid": False, "reason_code": "activation_before_promotion"}

    return {"valid": True, "reason_code": None}


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_promotion_evidence_allows_absent_candidate_traceability_ref():
    schema = _load_schema("publisher/promotion-evidence.schema.json")
    evidence = _promotion_evidence()
    del evidence["candidate_ref"]["candidate_traceability_ref"]

    errors = _validation_errors(evidence, schema)
    reference_result = _validate_promotion_references(evidence, {})

    assert errors == []
    assert reference_result == {"valid": True, "reason_code": None}


def test_promotion_with_broken_candidate_traceability_ref_fails_reduced_check():
    evidence = _promotion_evidence()

    result = _validate_promotion_references(evidence, candidate_traceability_by_ref={})

    assert result == {
        "valid": False,
        "reason_code": "candidate_traceability_missing",
    }


def test_promotion_candidate_release_mismatch_fails_reduced_check():
    evidence = _promotion_evidence()
    traceability_ref = evidence["candidate_ref"]["candidate_traceability_ref"]
    traceability = {
        "candidate_identity": {
            "dataset_slug": "example-dataset",
            "release_id": "release-20260620-999",
        }
    }

    result = _validate_promotion_references(evidence, {traceability_ref: traceability})

    assert result == {"valid": False, "reason_code": "candidate_release_mismatch"}


def test_promotion_manifest_hash_reference_mismatch_fails_reduced_check():
    evidence = _promotion_evidence(
        artifact_hashes_ref="releases/release-20260620-001/other-manifest.json",
    )
    traceability_ref = evidence["candidate_ref"]["candidate_traceability_ref"]
    traceability = {
        "candidate_identity": {
            "dataset_slug": "example-dataset",
            "release_id": "release-20260620-001",
        }
    }

    result = _validate_promotion_references(evidence, {traceability_ref: traceability})

    assert result == {
        "valid": False,
        "reason_code": "artifact_hash_manifest_mismatch",
    }


def test_activation_without_promotion_evidence_ref_fails_schema_validation():
    schema = _load_schema("publisher/registry-activation-evidence.schema.json")
    evidence = _activation_evidence()
    del evidence["promotion_evidence_ref"]

    errors = _validation_errors(evidence, schema)

    assert _has_required_error(errors, field="promotion_evidence_ref", path=())


def test_activation_with_broken_promotion_evidence_ref_fails_reduced_check():
    evidence = _activation_evidence()

    result = _validate_activation_reference(evidence, promotion_by_ref={})

    assert result == {"valid": False, "reason_code": "promotion_evidence_missing"}


def test_first_activation_without_previous_active_release_id_is_valid():
    schema = _load_schema("publisher/registry-activation-evidence.schema.json")
    evidence = _activation_evidence()
    del evidence["dataset_ref"]["previous_active_release_id"]

    errors = _validation_errors(evidence, schema)

    assert errors == []


def test_run_evidence_cannot_be_submitted_as_promotion_evidence():
    schema = _load_schema("publisher/promotion-evidence.schema.json")
    evidence = _promotion_evidence(evidence_kind="run_evidence")

    errors = _validation_errors(evidence, schema)

    assert _has_const_error(errors, path=("evidence_kind",))


def test_activation_before_promotion_fails_reduced_ordering_check():
    activation = _activation_evidence(activation_timestamp="2026-06-20T10:59:00Z")
    promotion_ref = activation["promotion_evidence_ref"]

    result = _validate_activation_reference(
        activation,
        {promotion_ref: _promotion_evidence()},
    )

    assert result == {"valid": False, "reason_code": "activation_before_promotion"}


def test_activation_reference_match_passes_reduced_check():
    activation = _activation_evidence()
    promotion_ref = activation["promotion_evidence_ref"]

    result = _validate_activation_reference(
        activation,
        {promotion_ref: _promotion_evidence()},
    )

    assert result == {"valid": True, "reason_code": None}
