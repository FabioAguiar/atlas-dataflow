import json
from dataclasses import dataclass
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


def _run_evidence(**overrides) -> dict:
    evidence = {
        "schema_version": "run-evidence.v1",
        "run_identity": {
            "run_id": "run-20260620-001",
            "run_type": "candidate_assembly",
            "producer": "pipeline-build",
        },
        "run_inputs": {
            "input_ref": "inputs/example-dataset/source-contract-input.json",
            "input_hash": "a" * 64,
        },
        "run_outputs": {
            "output_ref": "releases/candidates/example-dataset/release-20260620-001",
            "output_hash": "b" * 64,
        },
        "run_timestamps": {
            "started_at": "2026-06-20T10:00:00Z",
            "completed_at": "2026-06-20T10:05:00Z",
        },
        "run_status": "accepted",
        "run_boundary_confirmations": {
            "is_release_candidate": False,
            "is_published_release": False,
            "is_active_release": False,
        },
        "evidence_policy": {
            "raw_logs_prohibited": True,
            "raw_runtime_prohibited": True,
            "raw_api_payloads_prohibited": True,
            "secrets_prohibited": True,
            "private_source_paths_prohibited": True,
            "reduced_and_sanitized": True,
        },
    }
    evidence.update(overrides)
    return evidence


def _candidate_traceability(**overrides) -> dict:
    evidence = {
        "schema_version": "candidate-traceability.v1",
        "source_run_ref": {
            "run_id": "run-20260620-001",
            "run_evidence_ref": "evidence/M14/run-20260620-001.json",
            "producer": "pipeline-build",
            "run_type": "candidate_assembly",
        },
        "candidate_identity": {
            "dataset_slug": "example-dataset",
            "release_id": "release-20260620-001",
        },
        "candidate_artifacts": [
            {
                "artifact_role": "manifest_input",
                "artifact_name": "manifest-input.json",
                "artifact_hash": "c" * 64,
            }
        ],
        "validation_status": "publisher_validated",
        "traceability_boundary_confirmations": {
            "is_promotion_authorized": False,
            "is_active_release": False,
            "is_published_release": False,
            "raw_run_evidence_embedded": False,
        },
    }
    evidence.update(overrides)
    return evidence


def _validate_candidate_source_run(
    candidate: dict,
    run_evidence_by_ref: dict[str, dict],
) -> dict:
    source_ref = candidate["source_run_ref"]
    run_ref = source_ref["run_evidence_ref"]
    run_evidence = run_evidence_by_ref.get(run_ref)
    if run_evidence is None:
        return {"valid": False, "reason_code": "source_run_missing"}

    run_identity = run_evidence["run_identity"]
    if run_identity["run_id"] != source_ref["run_id"]:
        return {"valid": False, "reason_code": "source_run_id_mismatch"}
    if run_identity["producer"] != source_ref["producer"]:
        return {"valid": False, "reason_code": "source_run_producer_mismatch"}
    if run_evidence["run_status"] != "accepted":
        return {"valid": False, "reason_code": "source_run_not_accepted"}

    return {"valid": True, "reason_code": None}


def test_run_evidence_requires_run_id():
    schema = _load_schema("pipeline/run-evidence.schema.json")
    evidence = _run_evidence()
    del evidence["run_identity"]["run_id"]

    errors = _validation_errors(evidence, schema)

    assert _has_required_error(errors, field="run_id", path=("run_identity",))


def test_candidate_traceability_requires_source_run_reference():
    schema = _load_schema("pipeline/candidate-traceability.schema.json")
    evidence = _candidate_traceability()
    del evidence["source_run_ref"]["run_evidence_ref"]

    errors = _validation_errors(evidence, schema)

    assert _has_required_error(
        errors,
        field="run_evidence_ref",
        path=("source_run_ref",),
    )


def test_candidate_without_resolvable_source_run_fails_reduced_check():
    candidate = _candidate_traceability()

    result = _validate_candidate_source_run(candidate, run_evidence_by_ref={})

    assert result == {"valid": False, "reason_code": "source_run_missing"}


def test_candidate_source_run_identity_mismatch_fails_reduced_check():
    candidate = _candidate_traceability()
    run_ref = candidate["source_run_ref"]["run_evidence_ref"]
    run_evidence = _run_evidence()
    run_evidence["run_identity"]["run_id"] = "run-20260620-999"

    result = _validate_candidate_source_run(candidate, {run_ref: run_evidence})

    assert result == {"valid": False, "reason_code": "source_run_id_mismatch"}


def test_candidate_source_run_rejected_status_fails_reduced_check():
    candidate = _candidate_traceability()
    run_ref = candidate["source_run_ref"]["run_evidence_ref"]
    run_evidence = _run_evidence(run_status="rejected")

    result = _validate_candidate_source_run(candidate, {run_ref: run_evidence})

    assert result == {"valid": False, "reason_code": "source_run_not_accepted"}


def test_candidate_source_run_match_passes_reduced_check():
    candidate = _candidate_traceability()
    run_ref = candidate["source_run_ref"]["run_evidence_ref"]

    result = _validate_candidate_source_run(candidate, {run_ref: _run_evidence()})

    assert result == {"valid": True, "reason_code": None}
