"""
Tests for Project Spec S0168: Capability-Aware Release Candidate and
Publisher Contract Evolution.

Uses only synthetic in-memory/tmp_path fixtures. Never requires a real
(Telco-trained) model file, never deserializes joblib, never executes a
notebook, and never requires the external Telco filesystem. Fixtures reuse
a generic dataset slug (mirroring
tests/pipeline/test_capability_aware_contract_projection.py's own
convention) to demonstrate the new capability-aware machinery is
capability-driven, not dataset-name-driven.
"""

import hashlib
import inspect
import json
import sys
from pathlib import Path

import jsonschema
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pipeline import assemble_candidate  # noqa: E402
from pipeline.assemble_candidate import (  # noqa: E402
    CAPABILITY_REJECTION_PHASE_DATASET_MISMATCH,
    CAPABILITY_REJECTION_PHASE_PROFILE_MISMATCH,
    CAPABILITY_REJECTION_PHASE_ROLE_POLICY_MISMATCH,
    CAPABILITY_REJECTION_PHASE_UNSUPPORTED,
    CURRENTLY_SUPPORTED_RELEASE_CAPABILITY_PROFILE_ID,
    LayoutRolePolicyResult,
    resolve_capability_release_policy,
    validate_candidate_layout_role_policy,
)
from publisher.validate import validate_capability_conditional_roles  # noqa: E402

REPO_ROOT = Path(__file__).parent.parent.parent
RELEASE_CANDIDATE_INPUT_SCHEMA_PATH = REPO_ROOT / "pipeline" / "release-candidate-input.schema.json"
CANDIDATE_LAYOUT_SCHEMA_PATH = REPO_ROOT / "pipeline" / "candidate-layout.schema.json"

DATASET_SLUG = "sample-binary-classification-dataset"
AUTHORING_GENERATION_ID = "authoring-gen-0001"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, doc: dict) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(doc).encode("utf-8")
    path.write_bytes(data)
    return data


def _binary_predictive_profile() -> dict:
    return {
        "schema_version": "capability-profile.v1",
        "artifact_type": "capability_profile",
        "capability_profile_id": CURRENTLY_SUPPORTED_RELEASE_CAPABILITY_PROFILE_ID,
        "capability_profile_version": "v1",
        "support_status": "current_supported",
        "semantic_requirements": {"target_semantics_applicability": "required"},
        "artifact_roles": [
            {"role_name": "contracts", "applicability": "required"},
            {"role_name": "visualizations", "applicability": "optional"},
            {"role_name": "no_model_analysis_summary", "applicability": "forbidden"},
        ],
        "prediction_runtime": {
            "applicable": True,
            "mode": "single_model_binary_classification",
        },
        "publication": {"public_prediction_capability_applicability": "optional"},
        "capability_boundary_confirmations": {
            "dataset_specific_selector_used": False,
            "dataset_specific_feature_names_present": False,
            "concrete_model_hashes_present": False,
            "model_bytes_embedded": False,
            "release_instance_metadata_embedded": False,
            "absolute_external_path_present": False,
            "training_result_values_embedded": False,
        },
        "generated_at": "2026-08-07T00:00:00+00:00",
    }


def _future_probe_profile() -> dict:
    """A future-architecture-probe profile: syntactically representable but
    never operationally supported for release candidate assembly."""
    profile = _binary_predictive_profile()
    profile["capability_profile_id"] = "non-predictive-dataset-analysis"
    profile["support_status"] = "future_architecture_probe"
    return profile


def _role_policy_for(profile: dict, *, present_by_role: dict[str, bool]) -> list[dict]:
    return [
        {
            "role_name": entry["role_name"],
            "applicability": entry["applicability"],
            "present": present_by_role.get(entry["role_name"], entry["applicability"] == "required"),
        }
        for entry in profile["artifact_roles"]
    ]


def _capability_binding(profile: dict, *, dataset_slug: str = DATASET_SLUG, role_policy=None) -> dict:
    return {
        "dataset_slug": dataset_slug,
        "authoring_generation_id": AUTHORING_GENERATION_ID,
        "authoring_manifest_ref": {"path": "governed/authoring-manifest.json", "sha256": "0" * 64},
        "capability_profile_id": profile["capability_profile_id"],
        "capability_profile_version": profile["capability_profile_version"],
        "capability_profile_ref": {"path": "governed/capability-profile.json", "sha256": "0" * 64},
        "resolved_role_policy": role_policy or _role_policy_for(profile, present_by_role={}),
    }


# --- resolve_capability_release_policy (criteria 62-69, 76, 80) -----------


def test_resolve_capability_release_policy_accepts_current_supported_binary_profile():
    profile = _binary_predictive_profile()
    binding = _capability_binding(profile)

    result = resolve_capability_release_policy(binding, profile)

    assert result.status == "accepted"
    assert result.capability_profile_id == CURRENTLY_SUPPORTED_RELEASE_CAPABILITY_PROFILE_ID
    assert result.rejection_phase is None


def test_resolve_capability_release_policy_rejects_profile_identity_mismatch():
    profile = _binary_predictive_profile()
    binding = _capability_binding(profile)
    binding["capability_profile_version"] = "v2"

    result = resolve_capability_release_policy(binding, profile)

    assert result.status == "rejected"
    assert result.rejection_phase == CAPABILITY_REJECTION_PHASE_PROFILE_MISMATCH


def test_resolve_capability_release_policy_rejects_role_policy_profile_mismatch():
    profile = _binary_predictive_profile()
    role_policy = _role_policy_for(profile, present_by_role={})
    role_policy[0]["applicability"] = "optional"  # profile declares this role "required"
    binding = _capability_binding(profile, role_policy=role_policy)

    result = resolve_capability_release_policy(binding, profile)

    assert result.status == "rejected"
    assert result.rejection_phase == CAPABILITY_REJECTION_PHASE_ROLE_POLICY_MISMATCH


def test_resolve_capability_release_policy_fails_closed_for_unsupported_capability():
    profile = _future_probe_profile()
    binding = _capability_binding(profile)

    result = resolve_capability_release_policy(binding, profile)

    assert result.status == "rejected"
    assert result.rejection_phase == CAPABILITY_REJECTION_PHASE_UNSUPPORTED
    assert result.support_status == "future_architecture_probe"


def test_resolve_capability_release_policy_never_fabricates_artifacts_on_rejection():
    """The typed result carries no model/runtime/predictive fields at all --
    an unsupported capability cannot leak fabricated evidence through this
    function's return shape."""
    profile = _future_probe_profile()
    result = resolve_capability_release_policy(_capability_binding(profile), profile)
    result_fields = set(vars(result))
    assert result_fields == {
        "status",
        "capability_profile_id",
        "capability_profile_version",
        "support_status",
        "rejection_phase",
        "rejection_reason",
    }


# --- validate_candidate_layout_role_policy (criteria 19-30, 71-75, 78-79) -


def test_layout_role_policy_signature_has_no_dataset_or_filesystem_parameters():
    """Structural proof that applicability can never be derived from a
    dataset slug, Telco identity, filesystem existence, or a milestone id:
    the function only accepts already-resolved dicts."""
    params = set(inspect.signature(validate_candidate_layout_role_policy).parameters)
    assert params == {"declared_roles", "role_policy"}


def test_layout_role_policy_accepts_valid_binary_predictive_layout():
    profile = _binary_predictive_profile()
    declared_roles = {
        "contracts": {"path": "contracts/runtime-contract.json", "sha256": "a" * 64},
    }
    role_policy = profile["artifact_roles"]

    result = validate_candidate_layout_role_policy(declared_roles, role_policy)

    assert isinstance(result, LayoutRolePolicyResult)
    assert result.valid
    assert result.rejections == ()


def test_layout_role_policy_accepts_optional_role_absence():
    profile = _binary_predictive_profile()
    declared_roles = {"contracts": {"path": "contracts/runtime-contract.json"}}

    result = validate_candidate_layout_role_policy(declared_roles, profile["artifact_roles"])

    assert result.valid  # "visualizations" (optional) is absent and that's fine


def test_layout_role_policy_rejects_missing_required_role():
    profile = _binary_predictive_profile()
    declared_roles: dict = {}

    result = validate_candidate_layout_role_policy(declared_roles, profile["artifact_roles"])

    assert not result.valid
    assert any(r.code == "missing_required_role" and r.role_name == "contracts" for r in result.rejections)


def test_layout_role_policy_rejects_forbidden_role_presence():
    profile = _binary_predictive_profile()
    declared_roles = {
        "contracts": {"path": "contracts/runtime-contract.json"},
        "no_model_analysis_summary": {"path": "analysis/summary.json"},
    }

    result = validate_candidate_layout_role_policy(declared_roles, profile["artifact_roles"])

    assert not result.valid
    assert any(
        r.code == "forbidden_role_present" and r.role_name == "no_model_analysis_summary"
        for r in result.rejections
    )


def test_layout_role_policy_rejects_duplicate_role_assignment():
    profile = _binary_predictive_profile()
    declared_roles = {
        "contracts": {"path": "shared/artifact.json"},
        "visualizations": {"path": "shared/artifact.json"},
    }

    result = validate_candidate_layout_role_policy(declared_roles, profile["artifact_roles"])

    assert not result.valid
    assert any(r.code == "duplicate_role_assignment" for r in result.rejections)


def test_layout_role_policy_rejects_unsafe_absolute_path():
    profile = _binary_predictive_profile()
    declared_roles = {"contracts": {"path": "/etc/passwd"}}

    result = validate_candidate_layout_role_policy(declared_roles, profile["artifact_roles"])

    assert not result.valid
    assert any(r.code == "unsafe_role_path" and r.role_name == "contracts" for r in result.rejections)


def test_layout_role_policy_rejects_parent_traversal_path():
    profile = _binary_predictive_profile()
    declared_roles = {"contracts": {"path": "../../etc/passwd"}}

    result = validate_candidate_layout_role_policy(declared_roles, profile["artifact_roles"])

    assert not result.valid
    assert any(r.code == "unsafe_role_path" and r.role_name == "contracts" for r in result.rejections)


def test_layout_role_policy_rejects_malformed_integrity_reference():
    profile = _binary_predictive_profile()
    declared_roles = {"contracts": {"path": "contracts/runtime-contract.json", "sha256": "not-hex"}}

    result = validate_candidate_layout_role_policy(declared_roles, profile["artifact_roles"])

    assert not result.valid
    assert any(r.code == "malformed_integrity_reference" for r in result.rejections)


# --- release-candidate-input.schema.json capability_binding (criterion 16) -


def _sub_schema_validator(schema: dict, def_name: str) -> jsonschema.Draft202012Validator:
    """A validator for schema["$defs"][def_name] that still resolves
    internal $ref pointers (e.g. "#/$defs/role_applicability") against the
    full document, not just the extracted fragment."""
    return jsonschema.Draft202012Validator(schema).evolve(schema=schema["$defs"][def_name])


def test_release_candidate_input_schema_rejects_present_forbidden_role_policy_entry():
    schema = json.loads(RELEASE_CANDIDATE_INPUT_SCHEMA_PATH.read_text(encoding="utf-8"))
    entry = {"role_name": "no_model_analysis_summary", "applicability": "forbidden", "present": True}

    with pytest.raises(jsonschema.ValidationError):
        _sub_schema_validator(schema, "role_policy_entry").validate(entry)


def test_release_candidate_input_schema_accepts_absent_forbidden_role_policy_entry():
    schema = json.loads(RELEASE_CANDIDATE_INPUT_SCHEMA_PATH.read_text(encoding="utf-8"))
    entry = {"role_name": "no_model_analysis_summary", "applicability": "forbidden", "present": False}
    _sub_schema_validator(schema, "role_policy_entry").validate(entry)


# --- candidate-layout.schema.json path safety (criteria 24-25) ------------


def test_candidate_layout_schema_rejects_absolute_artifact_role_path():
    schema = json.loads(CANDIDATE_LAYOUT_SCHEMA_PATH.read_text(encoding="utf-8"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            "/etc/passwd", schema["$defs"]["safe_relative_role_path"], cls=jsonschema.Draft202012Validator
        )


def test_candidate_layout_schema_rejects_traversal_artifact_role_path():
    schema = json.loads(CANDIDATE_LAYOUT_SCHEMA_PATH.read_text(encoding="utf-8"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            "../../etc/passwd",
            schema["$defs"]["safe_relative_role_path"],
            cls=jsonschema.Draft202012Validator,
        )


def test_candidate_layout_schema_accepts_safe_relative_artifact_role_path():
    schema = json.loads(CANDIDATE_LAYOUT_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(
        "contracts/runtime-contract.json",
        schema["$defs"]["safe_relative_role_path"],
        cls=jsonschema.Draft202012Validator,
    )


# --- publisher.validate.validate_capability_conditional_roles (criteria 41-48, 77) -


def test_capability_conditional_roles_no_binding_is_pure_pass_through():
    result = validate_capability_conditional_roles({"dataset_identity": {"dataset_slug": DATASET_SLUG}}, {})
    assert result == {
        "checked": False,
        "capability_gated": False,
        "valid": True,
        "rejection_reasons": [],
    }


def test_capability_conditional_roles_accepts_optional_role_absent():
    profile = _binary_predictive_profile()
    candidate = {
        "dataset_identity": {"dataset_slug": DATASET_SLUG},
        "artifact_roles": {"contracts": {"path": "contracts/runtime-contract.json"}},
        "capability_binding": _capability_binding(
            profile,
            role_policy=_role_policy_for(profile, present_by_role={"contracts": True}),
        ),
    }
    role_results = {"contracts": {"status": "present"}}

    result = validate_capability_conditional_roles(candidate, role_results)

    assert result["checked"] is True
    assert result["valid"] is True


def test_capability_conditional_roles_rejects_missing_required_role():
    profile = _binary_predictive_profile()
    candidate = {
        "dataset_identity": {"dataset_slug": DATASET_SLUG},
        "artifact_roles": {},
        "capability_binding": _capability_binding(profile),
    }

    result = validate_capability_conditional_roles(candidate, {"contracts": {"status": "missing"}})

    assert result["valid"] is False
    assert any(r["code"] == "capability_missing_required_role" for r in result["rejection_reasons"])


def test_capability_conditional_roles_rejects_forbidden_role_present():
    profile = _binary_predictive_profile()
    candidate = {
        "dataset_identity": {"dataset_slug": DATASET_SLUG},
        "artifact_roles": {
            "contracts": {"path": "contracts/runtime-contract.json"},
            "no_model_analysis_summary": {"path": "analysis/summary.json"},
        },
        "capability_binding": _capability_binding(
            profile,
            role_policy=_role_policy_for(
                profile, present_by_role={"contracts": True, "no_model_analysis_summary": True}
            ),
        ),
    }
    role_results = {
        "contracts": {"status": "present"},
        "no_model_analysis_summary": {"status": "present"},
    }

    result = validate_capability_conditional_roles(candidate, role_results)

    assert result["valid"] is False
    assert any(r["code"] == "capability_forbidden_role_present" for r in result["rejection_reasons"])


def test_capability_conditional_roles_rejects_dataset_identity_mismatch():
    profile = _binary_predictive_profile()
    candidate = {
        "dataset_identity": {"dataset_slug": "a-different-dataset"},
        "artifact_roles": {"contracts": {"path": "contracts/runtime-contract.json"}},
        "capability_binding": _capability_binding(profile, dataset_slug=DATASET_SLUG),
    }

    result = validate_capability_conditional_roles(candidate, {"contracts": {"status": "present"}})

    assert result["valid"] is False
    assert any(r["code"] == "capability_dataset_identity_mismatch" for r in result["rejection_reasons"])


# --- assemble_release_candidate integration wiring (criteria 62-69, 77, 80) -


def _minimal_artifact_inputs() -> dict:
    def role(name: str) -> dict:
        return {
            "role": name,
            "required": True,
            "source_stage": "M26",
            "path": f"fake/{name}.json",
            "contract_version": f"{name}.v1",
            "sha256": "0" * 64,
            "hash_policy": "sha256_required",
            "public_projection": "internal_only",
            "evidence_classification": "not_evidence",
            "placeholder_policy": {
                "fixtures_allowed": False,
                "placeholders_allowed": False,
                "missing_required_behavior": "reject",
            },
            "availability_status": "real_dataflow_artifact",
        }

    return {
        "discovery_evidence": role("discovery_evidence"),
        "promoted_contracts": {
            "execution_contract": role("execution_contract"),
            "runtime_contract": role("runtime_contract"),
            "public_contract": role("public_contract"),
        },
        "preparation_recipe": role("preparation_recipe"),
        "prepared_data_metadata": role("prepared_data_metadata"),
        "training_parameter_record": role("training_parameter_record"),
        "model_artifact": role("model_artifact"),
        "training_metrics": role("training_metrics"),
        "model_card": role("model_card"),
        "public_context": role("public_context"),
        "visualizations": role("visualizations"),
        "inference_bundle": role("inference_bundle"),
        "internal_evidence_references": [
            {
                "role": "discovery_evidence",
                "path": "fake/discovery_evidence.json",
                "sha256": "0" * 64,
                "source_stage": "M22",
                "evidence_classification": "internal_evidence",
                "public_projection": "internal_only",
            }
        ],
    }


def _minimal_candidate_input(*, dataset_slug: str = DATASET_SLUG, capability_binding=None) -> dict:
    data = {
        "contract_version": "release-candidate-input.v1",
        "input_kind": "release_candidate_input",
        "dataset_identity": {"dataset_slug": dataset_slug, "dataset_title": "Sample"},
        "release_identity": {
            "release_id": "release-20260807-001",
            "release_version": "1.0.0-rc.1",
            "created_at": "2026-08-07T00:00:00Z",
        },
        "source_run": {
            "run_id": "candidate-input-20260807T000000Z",
            "producer": "test",
            "created_at": "2026-08-07T00:00:00Z",
        },
        "artifact_inputs": _minimal_artifact_inputs(),
        "candidate_mapping": assemble_candidate._CANDIDATE_INPUT_CANDIDATE_MAPPING,
        "classification_policy": assemble_candidate._CANDIDATE_INPUT_CLASSIFICATION_POLICY,
        "boundary_confirmations": assemble_candidate._CANDIDATE_INPUT_BOUNDARY_CONFIRMATIONS,
    }
    if capability_binding is not None:
        data["capability_binding"] = capability_binding
    return data


def test_assemble_release_candidate_rejects_dataset_identity_mismatch(tmp_path):
    profile = _binary_predictive_profile()
    binding = _capability_binding(profile, dataset_slug="a-different-dataset")
    candidate_input = _minimal_candidate_input(dataset_slug=DATASET_SLUG, capability_binding=binding)

    result = assemble_candidate.assemble_release_candidate(
        candidate_input, tmp_path / "releases" / "candidates", repo_root=tmp_path
    )

    assert result["status"] == "rejected"
    assert result["reason"] == CAPABILITY_REJECTION_PHASE_DATASET_MISMATCH or (
        result.get("rejection_phase") == CAPABILITY_REJECTION_PHASE_DATASET_MISMATCH
    )


def test_assemble_release_candidate_fails_closed_for_unsupported_capability(tmp_path):
    profile = _future_probe_profile()
    profile_bytes = json.dumps(profile).encode("utf-8")
    profile_path = tmp_path / "governed" / "capability-profile.json"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_bytes(profile_bytes)

    binding = _capability_binding(profile)
    binding["capability_profile_ref"] = {
        "path": "governed/capability-profile.json",
        "sha256": _sha256_bytes(profile_bytes),
    }
    candidate_input = _minimal_candidate_input(capability_binding=binding)

    result = assemble_candidate.assemble_release_candidate(
        candidate_input, tmp_path / "releases" / "candidates", repo_root=tmp_path
    )

    assert result["status"] == "rejected"
    assert result["rejection_phase"] == CAPABILITY_REJECTION_PHASE_UNSUPPORTED
    # No candidate directory, model, or runtime artifact was ever materialized.
    assert not (tmp_path / "releases").exists()


def test_assemble_release_candidate_ignores_absent_capability_binding():
    """Historical release-candidate-input.v1 behavior (no capability_binding)
    is unaffected: input validation runs exactly as before this Project
    Spec, independent of any capability-aware machinery."""
    candidate_input = _minimal_candidate_input(capability_binding=None)
    assert "capability_binding" not in candidate_input
    errors = assemble_candidate._validate_candidate_input(candidate_input)
    assert errors == []
