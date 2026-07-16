import hashlib
import json
from pathlib import Path

import pytest

from pipeline import assemble_candidate
from publisher import validate


DATASET_SLUG = "example-dataset"
RELEASE_ID = "release-20260619-001"
RELEASE_VERSION = "2026.06.19"

REQUIRED_ROLES = (
    "contracts",
    "public_contract",
    "predictive_bundle",
    "model_artifact",
    "metrics",
    "model_card",
    "public_context",
    "manifest_input",
    "candidate_metadata",
)

# Project Spec S0107: the model artifact is a private binary, never JSON.
MODEL_ARTIFACT_BYTES = b"pytest-fixture-model-bytes-not-a-real-model"
MODEL_ARTIFACT_SHA256 = hashlib.sha256(MODEL_ARTIFACT_BYTES).hexdigest()
MODEL_ARTIFACT_PATH = "models/model.pkl"


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _candidate_dir(tmp_path: Path) -> Path:
    return tmp_path / "releases" / "candidates" / DATASET_SLUG / RELEASE_ID


def _valid_public_contract_payload(**overrides) -> dict:
    payload = {
        "schema_version": "1.0.0",
        "features": [
            {
                "name": "example_feature",
                "label": "Example Feature",
                "input_type": "number",
                "optional": False,
                "display_order": 1,
            }
        ],
    }
    payload.update(overrides)
    return payload


def _artifact_payload(role: str, **overrides) -> dict:
    if role == "public_contract":
        # A real contracts/public-contract.schema.json instance
        # (additionalProperties: false) -- cannot carry the generic
        # dataset_identity/role/etc keys the other roles use below
        # (Project Spec S0101).
        return _valid_public_contract_payload(**overrides)
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
        payload["model_artifact"] = {"path": MODEL_ARTIFACT_PATH, "sha256": MODEL_ARTIFACT_SHA256}
    if role == "public_context":
        payload["public_projection"] = {"safe_for_public": True}
    payload.update(overrides)
    return payload


def _role_path(role: str) -> str:
    if role == "model_artifact":
        return MODEL_ARTIFACT_PATH
    return f"artifacts/{role}.json"


def _write_candidate(tmp_path: Path, *, artifact_overrides: dict | None = None) -> Path:
    artifact_overrides = artifact_overrides or {}
    candidate_dir = _candidate_dir(tmp_path)
    candidate_dir.mkdir(parents=True, exist_ok=True)

    artifact_roles = {}
    for role in REQUIRED_ROLES:
        role_path = _role_path(role)
        artifact_roles[role] = {
            "role": role,
            "path": role_path,
            "required": True,
        }
        if role == "model_artifact":
            (candidate_dir / role_path).parent.mkdir(parents=True, exist_ok=True)
            (candidate_dir / role_path).write_bytes(MODEL_ARTIFACT_BYTES)
            continue
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


# --- S0101: public_contract as the eighth required publisher artifact role ---


def test_public_contract_accepts_a_conformant_candidate(tmp_path):
    candidate_dir = _write_candidate(tmp_path)

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is True
    assert result["role_results"]["public_contract"]["status"] == "present"
    assert result["schema_compatibility"]["public_contract"] == {"checked": True, "compatible": True}


def test_public_contract_missing_role_definition_is_rejected(tmp_path):
    candidate_dir = _candidate_dir(tmp_path)
    candidate_dir.mkdir(parents=True, exist_ok=True)

    artifact_roles = {}
    for role in REQUIRED_ROLES:
        if role == "public_contract":
            continue
        role_path = _role_path(role)
        artifact_roles[role] = {"role": role, "path": role_path, "required": True}
        if role == "model_artifact":
            (candidate_dir / role_path).parent.mkdir(parents=True, exist_ok=True)
            (candidate_dir / role_path).write_bytes(MODEL_ARTIFACT_BYTES)
            continue
        _write_json(candidate_dir / role_path, _artifact_payload(role))

    candidate = {
        "schema_version": "release-candidate.v1",
        "candidate_kind": "release_candidate",
        "dataset_identity": {"dataset_slug": DATASET_SLUG, "dataset_title": "Example Dataset"},
        "release_identity": {
            "release_id": RELEASE_ID,
            "release_version": RELEASE_VERSION,
            "created_at": "2026-06-19T00:00:00Z",
        },
        "source_run": {"run_id": "test-run", "producer": "pytest", "created_at": "2026-06-19T00:00:00Z"},
        "artifact_roles": artifact_roles,
        "candidate_metadata": {
            "assembled_by": "pytest",
            "assembled_at": "2026-06-19T00:00:00Z",
            "intended_publisher_action": "validate_candidate",
            "completeness_validation": {
                "required_artifact_roles": [r for r in REQUIRED_ROLES if r != "public_contract"],
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

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is False
    assert "missing_public_contract" in _rejection_codes(result)
    assert result["role_results"]["public_contract"]["status"] == "missing"


def test_public_contract_unsafe_reference_is_rejected(tmp_path):
    candidate_dir = _write_candidate(tmp_path)
    candidate = json.loads((candidate_dir / "release-candidate.json").read_text())
    candidate["artifact_roles"]["public_contract"]["path"] = "../../../etc/passwd"
    _write_json(candidate_dir / "release-candidate.json", candidate)

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is False
    assert "unsafe_candidate_artifact" in _rejection_codes(result)
    assert result["role_results"]["public_contract"]["status"] == "unsafe"
    assert result["role_results"]["public_contract"]["artifact_reference"] is None


def test_public_contract_absolute_reference_is_rejected(tmp_path):
    candidate_dir = _write_candidate(tmp_path)
    candidate = json.loads((candidate_dir / "release-candidate.json").read_text())
    candidate["artifact_roles"]["public_contract"]["path"] = "/etc/passwd"
    _write_json(candidate_dir / "release-candidate.json", candidate)

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is False
    assert "unsafe_candidate_artifact" in _rejection_codes(result)


def test_public_contract_invalid_json_is_rejected(tmp_path):
    candidate_dir = _write_candidate(tmp_path)
    artifact_path = candidate_dir / "artifacts" / "public_contract.json"
    artifact_path.write_text("{not valid json", encoding="utf-8")

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is False
    assert "public_contract_schema_incompatible" in _rejection_codes(result)
    assert result["schema_compatibility"]["public_contract"]["compatible"] is False


def test_public_contract_schema_incompatible_payload_is_rejected(tmp_path):
    candidate_dir = _write_candidate(
        tmp_path,
        artifact_overrides={
            "public_contract": {"schema_version": "1.0.0", "features": [], "extra_field": "not allowed"},
        },
    )

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is False
    assert "public_contract_schema_incompatible" in _rejection_codes(result)
    assert result["schema_compatibility"]["public_contract"]["compatible"] is False


def test_public_contract_missing_file_is_rejected(tmp_path):
    candidate_dir = _write_candidate(tmp_path)
    (candidate_dir / "artifacts" / "public_contract.json").unlink()

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is False
    assert "missing_public_contract" in _rejection_codes(result)
    assert result["role_results"]["public_contract"]["status"] == "missing"


# --- S0107: model_artifact as the ninth required publisher artifact role ---


def test_model_artifact_accepts_a_conformant_candidate(tmp_path):
    candidate_dir = _write_candidate(tmp_path)

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is True
    assert result["role_results"]["model_artifact"]["status"] == "present"
    assert "model_artifact" not in result["schema_compatibility"]


def test_model_artifact_missing_file_is_rejected(tmp_path):
    candidate_dir = _write_candidate(tmp_path)
    (candidate_dir / MODEL_ARTIFACT_PATH).unlink()

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is False
    assert "missing_model_artifact" in _rejection_codes(result)
    assert result["role_results"]["model_artifact"]["status"] == "missing"


def test_model_artifact_unsafe_reference_is_rejected(tmp_path):
    candidate_dir = _write_candidate(tmp_path)
    candidate = json.loads((candidate_dir / "release-candidate.json").read_text())
    candidate["artifact_roles"]["model_artifact"]["path"] = "/etc/passwd"
    _write_json(candidate_dir / "release-candidate.json", candidate)

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is False
    assert "unsafe_model_reference" in _rejection_codes(result)
    assert result["role_results"]["model_artifact"]["status"] == "unsafe"
    assert result["role_results"]["model_artifact"]["artifact_reference"] is None


def test_model_artifact_path_mismatch_with_bundle_is_rejected(tmp_path):
    candidate_dir = _write_candidate(tmp_path)
    bundle_path = candidate_dir / "artifacts" / "predictive_bundle.json"
    bundle = json.loads(bundle_path.read_text())
    bundle["model_artifact"]["path"] = "models/some-other-model.pkl"
    _write_json(bundle_path, bundle)

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is False
    assert "model_bundle_path_mismatch" in _rejection_codes(result)
    assert result["role_results"]["model_artifact"]["status"] == "contradictory"


def test_model_artifact_hash_mismatch_with_bundle_is_rejected(tmp_path):
    candidate_dir = _write_candidate(tmp_path)
    bundle_path = candidate_dir / "artifacts" / "predictive_bundle.json"
    bundle = json.loads(bundle_path.read_text())
    bundle["model_artifact"]["sha256"] = "0" * 64
    _write_json(bundle_path, bundle)

    result = validate.validate_candidate_file(candidate_dir)

    assert result["valid"] is False
    assert "model_bundle_hash_mismatch" in _rejection_codes(result)
    assert result["role_results"]["model_artifact"]["status"] == "contradictory"


def test_model_artifact_bytes_never_parsed_as_json(tmp_path):
    candidate_dir = _write_candidate(tmp_path)
    non_json_bytes = b"\x80\x81not-json-binary\x00\xff"
    (candidate_dir / MODEL_ARTIFACT_PATH).write_bytes(non_json_bytes)
    bundle_path = candidate_dir / "artifacts" / "predictive_bundle.json"
    bundle = json.loads(bundle_path.read_text())
    bundle["model_artifact"]["sha256"] = hashlib.sha256(non_json_bytes).hexdigest()
    _write_json(bundle_path, bundle)

    result = validate.validate_candidate_file(candidate_dir)

    # Non-JSON, non-UTF8 model bytes must not raise or be schema-checked --
    # the model role is never JSON-parsed, only hashed.
    assert result["valid"] is True
    assert result["role_results"]["model_artifact"]["status"] == "present"
    assert "model_artifact" not in result["schema_compatibility"]


# --- Release-candidate-input assembly from a governed training run (Project Spec S0032) ---
#
# These tests exercise pipeline/assemble_candidate.py's build_release_candidate_input,
# derive_deterministic_release_id, and assemble_release_candidate end to end: proving a
# valid, Telco-style release-candidate-input.v1 can be built from explicit governed
# artifact references and assembled into a publisher-compatible candidate, and that a
# missing required artifact is rejected -- both before input construction (handoff not
# ready) and at assembly time (artifact removed after the input was built).

S0032_DATASET_SLUG = "telco-style-dataset"
S0032_TRAINING_RUN_ID = "train-20260709T224340Z"

# Project Spec S0107: the model artifact is a private binary, never JSON.
_S0032_MODEL_ARTIFACT_BYTES = b"not-a-real-model-but-real-bytes"
_S0032_MODEL_ARTIFACT_SHA256 = hashlib.sha256(_S0032_MODEL_ARTIFACT_BYTES).hexdigest()


def _write_s0032_governed_artifacts(repo_root: Path, *, omit_role: str | None = None) -> dict:
    dataset_slug = S0032_DATASET_SLUG
    run_id = S0032_TRAINING_RUN_ID
    references = {
        "discovery_evidence": f"pipeline/evidence/{dataset_slug}/discovery-evidence.json",
        "execution_contract": f"contracts/{dataset_slug}/execution-contract.json",
        "runtime_contract": f"contracts/{dataset_slug}/runtime-contract.json",
        "public_contract": f"contracts/{dataset_slug}/public-contract.json",
        "preparation_recipe": f"pipeline/evidence/{dataset_slug}/preparation-recipe.json",
        "prepared_data_metadata": f"pipeline/prepared/{dataset_slug}/prepared-data-metadata.json",
        "training_parameter_record": (
            f"pipeline/training-runs/{dataset_slug}/{run_id}/training-parameter-record.json"
        ),
        "model_artifact": f"pipeline/training-runs/{dataset_slug}/{run_id}/model.pkl",
        "training_metrics": f"pipeline/training-runs/{dataset_slug}/{run_id}/metrics.json",
        "model_card": f"pipeline/training-runs/{dataset_slug}/{run_id}/model-card.json",
        "public_context": f"contracts/{dataset_slug}/dataset-context.json",
        "inference_bundle": f"contracts/{dataset_slug}/inference-bundle.json",
    }
    for role, relative_path in references.items():
        if role == omit_role:
            continue
        if role == "model_artifact":
            path = repo_root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(_S0032_MODEL_ARTIFACT_BYTES)
        elif role == "public_contract":
            # Must be a real contracts/public-contract.schema.json instance
            # (additionalProperties: false), not the generic
            # role/contract_version placeholder used below (Project Spec
            # S0101 -- publisher/validate.py now validates this role for
            # real against that schema).
            _write_json(repo_root / relative_path, _valid_public_contract_payload())
        elif role == "inference_bundle":
            _write_json(
                repo_root / relative_path,
                {
                    "role": role,
                    "contract_version": f"{role}.v1",
                    "schema_version": f"{role}.v1",
                    "model_artifact": {
                        "path": "models/model.pkl",
                        "sha256": _S0032_MODEL_ARTIFACT_SHA256,
                    },
                },
            )
        else:
            _write_json(
                repo_root / relative_path,
                {"role": role, "contract_version": f"{role}.v1", "schema_version": f"{role}.v1"},
            )
    return references


def test_build_release_candidate_input_assembles_valid_telco_style_candidate(tmp_path):
    repo_root = tmp_path / "repo"
    artifact_references = _write_s0032_governed_artifacts(repo_root)

    release_id = assemble_candidate.derive_deterministic_release_id(S0032_TRAINING_RUN_ID)
    assert release_id == "release-20260709t224340z"

    candidate_input = assemble_candidate.build_release_candidate_input(
        dataset_slug=S0032_DATASET_SLUG,
        release_id=release_id,
        source_run_id=S0032_TRAINING_RUN_ID,
        artifact_references=artifact_references,
        repo_root=repo_root,
    )
    assert candidate_input["contract_version"] == "release-candidate-input.v1"
    assert candidate_input["artifact_inputs"]["inference_bundle"]["availability_status"] == (
        "real_dataflow_artifact"
    )

    result = assemble_candidate.assemble_release_candidate(
        candidate_input,
        repo_root / "releases" / "candidates",
        repo_root=repo_root,
        source_input_label="s0032-test-input",
    )

    assert result["status"] == "accepted", result
    candidate_dir = Path(result["candidate_dir"])
    assert (candidate_dir / "release-candidate.json").is_file()
    assert (candidate_dir / "manifest-input.json").is_file()
    assert (candidate_dir / "build-evidence.json").is_file()
    assert (candidate_dir / "contracts" / "runtime-contract.json").is_file()
    assert (candidate_dir / "contracts" / "public-contract.json").is_file()
    assert (candidate_dir / "metrics" / "metrics.json").is_file()
    assert (candidate_dir / "predictions" / "bundle.json").is_file()
    assert (candidate_dir / "model-card.json").is_file()
    assert (candidate_dir / "public-context.json").is_file()
    # The candidate is assembled, not published: this spec must not create a
    # publisher run.
    assert not (repo_root / "publisher" / "runs").exists()


def test_build_release_candidate_input_rejects_when_a_required_role_is_missing(tmp_path):
    repo_root = tmp_path / "repo"
    artifact_references = _write_s0032_governed_artifacts(repo_root, omit_role="inference_bundle")
    release_id = assemble_candidate.derive_deterministic_release_id(S0032_TRAINING_RUN_ID)

    with pytest.raises(ValueError, match="inference_bundle"):
        assemble_candidate.build_release_candidate_input(
            dataset_slug=S0032_DATASET_SLUG,
            release_id=release_id,
            source_run_id=S0032_TRAINING_RUN_ID,
            artifact_references=artifact_references,
            repo_root=repo_root,
        )


def test_assemble_release_candidate_rejects_when_a_referenced_artifact_goes_missing(tmp_path):
    repo_root = tmp_path / "repo"
    artifact_references = _write_s0032_governed_artifacts(repo_root)
    release_id = assemble_candidate.derive_deterministic_release_id(S0032_TRAINING_RUN_ID)

    candidate_input = assemble_candidate.build_release_candidate_input(
        dataset_slug=S0032_DATASET_SLUG,
        release_id=release_id,
        source_run_id=S0032_TRAINING_RUN_ID,
        artifact_references=artifact_references,
        repo_root=repo_root,
    )

    # Simulate a required artifact disappearing between input construction and
    # assembly (for example a caller reusing a stale input document).
    (repo_root / artifact_references["public_contract"]).unlink()

    result = assemble_candidate.assemble_release_candidate(
        candidate_input,
        repo_root / "releases" / "candidates",
        repo_root=repo_root,
        source_input_label="s0032-test-input",
    )

    assert result["status"] == "rejected"
    assert result["rejection_phase"] == "candidate_artifact_missing"
    assert artifact_references["public_contract"] in result["missing_paths"]
    assert not any((repo_root / "releases").rglob("release-candidate.json"))
