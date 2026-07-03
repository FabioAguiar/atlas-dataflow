"""
Dataset public profile snapshot publication traceability evidence tests
for M36-04.

Mirrors the reduced-schema-assertion style already established by
tests/publisher/test_publisher_traceability_validation.py and
tests/pipeline/test_pipeline_traceability_validation.py for this
repository's repeated evidence-writer convention: load the real schema
file from disk and check required/const constraints with a small
hand-rolled reduced validator, rather than depending on the jsonschema
library for these traceability tests.

Run from the repository root:
    python -m pytest tests/registry/test_dataset_public_profile_snapshot_traceability_validation.py -v
"""

import json
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from registry.dataset_public_profile_snapshot_evidence import (  # noqa: E402
    build_snapshot_evidence,
)


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


_CANDIDATE = {
    "schema_version": "1.0.0",
    "dataset_slug": "telco-customer-churn",
    "published_at": "2026-07-03T18:00:00Z",
    "active_release_at_publish_time": "release-20260619-001",
    "profile": {"display": {"title": "Churn Risk"}},
    "source_draft_schema_version": "1.0.0",
}


def _snapshot_evidence(**overrides) -> dict:
    evidence = build_snapshot_evidence(
        candidate=dict(_CANDIDATE),
        validation_errors=[],
        visibility_value="public",
    )
    evidence.update(overrides)
    return evidence


def test_snapshot_evidence_schema_requires_snapshot_identifier():
    schema = _load_schema(
        "registry/evidence/dataset-public-profile-snapshot-evidence.schema.json"
    )
    evidence = _snapshot_evidence()
    del evidence["snapshot_identifier"]

    errors = _validation_errors(evidence, schema)

    assert _has_required_error(errors, field="snapshot_identifier", path=())


def test_snapshot_evidence_schema_requires_visibility_at_publish_time():
    schema = _load_schema(
        "registry/evidence/dataset-public-profile-snapshot-evidence.schema.json"
    )
    evidence = _snapshot_evidence()
    del evidence["visibility_at_publish_time"]

    errors = _validation_errors(evidence, schema)

    assert _has_required_error(errors, field="visibility_at_publish_time", path=())


def test_snapshot_evidence_visibility_must_be_read_only():
    schema = _load_schema(
        "registry/evidence/dataset-public-profile-snapshot-evidence.schema.json"
    )
    evidence = _snapshot_evidence()
    evidence["visibility_at_publish_time"]["read_only_snapshot"] = False

    errors = _validation_errors(evidence, schema)

    assert _has_const_error(errors, path=("visibility_at_publish_time", "read_only_snapshot"))


def test_snapshot_evidence_requires_reduced_candidate_validation_shape():
    schema = _load_schema(
        "registry/evidence/dataset-public-profile-snapshot-evidence.schema.json"
    )
    evidence = _snapshot_evidence()
    del evidence["candidate_validation"]["validated_at"]

    errors = _validation_errors(evidence, schema)

    assert _has_required_error(errors, field="validated_at", path=("candidate_validation",))


def test_snapshot_evidence_evidence_safety_forbids_raw_logs():
    schema = _load_schema(
        "registry/evidence/dataset-public-profile-snapshot-evidence.schema.json"
    )
    evidence = _snapshot_evidence()
    evidence["evidence_safety"]["raw_logs_persisted"] = True

    errors = _validation_errors(evidence, schema)

    assert _has_const_error(errors, path=("evidence_safety", "raw_logs_persisted"))


def test_build_snapshot_evidence_derives_deterministic_identifier():
    evidence = build_snapshot_evidence(
        candidate=dict(_CANDIDATE),
        validation_errors=[],
        visibility_value="public",
    )

    assert evidence["snapshot_identifier"] == (
        "telco-customer-churn@2026-07-03T18:00:00Z"
    )
    assert evidence["dataset_slug"] == "telco-customer-churn"
    assert evidence["draft_source_reference"]["path"] == (
        "registry/profile-drafts/telco-customer-churn.json"
    )
    assert evidence["draft_source_reference"]["source_draft_schema_version"] == "1.0.0"


def test_build_snapshot_evidence_reuses_existing_reduced_error_identifiers():
    reduced_errors = [
        {"code": "SCHEMA_VALIDATION_ERROR", "field": "profile.display.title", "message": "too short"}
    ]

    evidence = build_snapshot_evidence(
        candidate=dict(_CANDIDATE),
        validation_errors=reduced_errors,
        visibility_value="public",
    )

    assert evidence["candidate_validation"]["validation_outcome"] == "rejected"
    assert evidence["candidate_validation"]["errors"] == reduced_errors


def test_build_snapshot_evidence_captures_visibility_read_only():
    evidence = build_snapshot_evidence(
        candidate=dict(_CANDIDATE),
        validation_errors=[],
        visibility_value=None,
    )

    assert evidence["visibility_at_publish_time"]["value"] is None
    assert evidence["visibility_at_publish_time"]["read_only_snapshot"] is True
    assert evidence["visibility_at_publish_time"]["source_field"] == (
        "registry/datasets.json:public_metadata.visibility"
    )


def test_build_snapshot_evidence_never_persists_raw_data():
    evidence = build_snapshot_evidence(
        candidate=dict(_CANDIDATE),
        validation_errors=[],
        visibility_value="public",
    )

    safety = evidence["evidence_safety"]
    assert safety["raw_logs_persisted"] is False
    assert safety["raw_runtime_persisted"] is False
    assert safety["raw_api_payloads_persisted"] is False
    assert safety["secrets_persisted"] is False
    assert safety["raw_artifact_contents_embedded"] is False
