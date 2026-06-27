import json
from pathlib import Path

import pytest

from publisher import validate


DATASET_SLUG = "example-dataset"
RELEASE_ID = "release-20260619-001"
RELEASE_VERSION = "2026.06.19"

REQUIRED_ROLES = (
    "contracts",
    "predictive_bundle",
    "metrics",
    "model_card",
    "public_context",
    "manifest_input",
    "candidate_metadata",
)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _candidate_dir(tmp_path: Path) -> Path:
    return tmp_path / "releases" / "candidates" / DATASET_SLUG / RELEASE_ID


def _artifact_payload(role: str, **overrides) -> dict:
    payload = {
        "role": role,
        "dataset_identity": {"dataset_slug": DATASET_SLUG},
        "release_identity": {"release_id": RELEASE_ID},
        "availability_status": "real_dataflow_artifact",
        "placeholder_policy": {
            "fixtures_allowed": False,
            "placeholders_allowed": False,
            "missing_required_behavior": "reject",
        },
    }
    if role in {"metrics", "model_card", "predictive_bundle"}:
        payload["model_id"] = "model-example-001"
    if role == "predictive_bundle":
        payload["runtime_contract_ref"] = "artifacts/contracts.json"
    if role == "public_context":
        payload["public_projection"] = {"safe_for_public": True}
    payload.update(overrides)
    return payload


def _write_candidate(tmp_path: Path, *, artifact_overrides: dict | None = None) -> Path:
    artifact_overrides = artifact_overrides or {}
    candidate_dir = _candidate_dir(tmp_path)
    candidate_dir.mkdir(parents=True, exist_ok=True)

    artifact_roles = {}
    for role in REQUIRED_ROLES:
        role_path = f"artifacts/{role}.json"
        artifact_roles[role] = {
            "role": role,
            "path": role_path,
            "required": True,
        }
        _write_json(
            candidate_dir / role_path,
            _artifact_payload(role, **artifact_overrides.get(role, {})),
        )

    candidate = {
        "schema_version": "release-candidate.v1",
        "candidate_kind": "release_candidate",
        "dataset_identity": {
            "dataset_slug": DATASET_SLUG,
            "dataset_title": "Example Dataset",
        },
        "release_identity": {
            "release_id": RELEASE_ID,
            "release_version": RELEASE_VERSION,
            "created_at": "2026-06-19T00:00:00Z",
        },
        "source_run": {
            "run_id": "test-run",
            "producer": "pytest",
            "created_at": "2026-06-19T00:00:00Z",
        },
        "artifact_roles": artifact_roles,
        "candidate_metadata": {
            "assembled_by": "pytest",
            "assembled_at": "2026-06-19T00:00:00Z",
            "intended_publisher_action": "validate_candidate",
            "completeness_validation": {
                "required_artifact_roles": list(REQUIRED_ROLES),
                "hash_policy": "publisher_calculates_hashes",
                "manifest_policy": "publisher_generates_manifest",
            },
        },
        "state_boundaries": {
            "pipeline_run_is_publishable": False,
            "candidate_is_published_release": False,
            "promotion_required": True,
            "registry_update_allowed_in_candidate": False,
            "public_upload_required": False,
            "web_administration_required": False,
            "database_publication_management_required": False,
            "runtime_consumes_temporary_pipeline_output": False,
        },
    }
    _write_json(candidate_dir / "release-candidate.json", candidate)
    return candidate_dir


def _rejection_codes(result: dict) -> set[str]:
    return {reason["code"] for reason in result["rejection_reasons"]}


def test_cross_artifact_validation_accepts_aligned_candidate(tmp_path):
    candidate_dir = _write_candidate(tmp_path)

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is True
    assert result["cross_artifact_consistency"]["valid"] is True
    assert result["cross_artifact_consistency"]["identity_checks"]
    assert result["cross_artifact_consistency"]["public_projection_checks"]


def test_cross_artifact_validation_rejects_declared_hash_mismatch(tmp_path):
    candidate_dir = _write_candidate(tmp_path)
    candidate = json.loads((candidate_dir / "release-candidate.json").read_text())
    candidate["artifact_roles"]["metrics"]["sha256"] = "f" * 64
    _write_json(candidate_dir / "release-candidate.json", candidate)

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is False
    assert "hash_mismatch" in _rejection_codes(result)
    assert result["role_results"]["metrics"]["status"] == "contradictory"


def test_cross_artifact_validation_rejects_dataset_identity_mismatch(tmp_path):
    candidate_dir = _write_candidate(
        tmp_path,
        artifact_overrides={
            "metrics": {"dataset_identity": {"dataset_slug": "other-dataset"}},
        },
    )

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is False
    assert "dataset_identifier_mismatch" in _rejection_codes(result)


def test_cross_artifact_validation_rejects_model_reference_mismatch(tmp_path):
    candidate_dir = _write_candidate(
        tmp_path,
        artifact_overrides={
            "metrics": {"model_id": "model-other-001"},
        },
    )

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is False
    assert "model_bundle_mismatch" in _rejection_codes(result)


def test_cross_artifact_validation_rejects_unsafe_public_projection(tmp_path):
    candidate_dir = _write_candidate(
        tmp_path,
        artifact_overrides={
            "public_context": {"internal_evidence": {"unsafe": True}},
        },
    )

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is False
    assert "public_projection_unsafe" in _rejection_codes(result)
    assert result["role_results"]["public_context"]["status"] == "unsafe"


@pytest.mark.parametrize(
    ("availability_status", "expected_code"),
    [
        ("fixture_only", "fixture_only_artifact"),
        ("placeholder_only", "placeholder_only_artifact"),
    ],
)
def test_cross_artifact_validation_rejects_non_real_required_artifact(
    tmp_path,
    availability_status,
    expected_code,
):
    candidate_dir = _write_candidate(
        tmp_path,
        artifact_overrides={
            "metrics": {"availability_status": availability_status},
        },
    )

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is False
    assert expected_code in _rejection_codes(result)
    assert result["role_results"]["metrics"]["status"] == "incomplete"
