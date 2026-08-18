"""
Tests for Project Spec S0167: Capability-Aware Source Input and Contract
Projection Contract.

Uses only synthetic in-memory/tmp_path fixtures. Never requires the external
Telco filesystem, never uses a real model file, never deserializes joblib,
and never executes a notebook. Fixtures use a generic dataset slug (mirroring
tests/pipeline/test_authoring_contracts.py's own convention) to demonstrate
the new capability-aware projection path is capability-driven, not
dataset-name-driven.
"""

import hashlib
import inspect
import json
import re
import sys
from pathlib import Path

import jsonschema
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pipeline import build, contract_derivation
from pipeline.contract_derivation import (
    CONTRACT_PROJECTION_SUPPORTED_CAPABILITY_PROFILE_IDS,
    CURRENTLY_SUPPORTED_CAPABILITY_PROFILE_ID,
    CapabilityProjectionResult,
    project_capability_aware_source_contract,
    resolve_manifest_role_reference,
)

REPO_ROOT = Path(__file__).parent.parent.parent
SOURCE_CONTRACT_INPUT_SCHEMA_PATH = REPO_ROOT / "pipeline" / "source-contract-input.schema.json"

DATASET_SLUG = "sample-binary-classification-dataset"
AUTHORING_GENERATION_ID = "authoring-gen-0001"

RUNTIME_CONTRACT = {
    "schema_version": "1.0.0",
    "features": [{"name": "tenure_months", "type": "numeric"}],
}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _write_json(path: Path, doc: dict) -> bytes:
    data = json.dumps(doc).encode("utf-8")
    _write_bytes(path, data)
    return data


def _binary_classification_profile(*, model_artifact_authoring_boundary_applicability: str | None = None) -> dict:
    """`model_artifact_authoring_boundary_applicability` additively sets
    the model_artifact role's authoring_boundary_applicability override
    (S0185) when supplied; the default (None) omits the field entirely so
    every pre-existing test in this module keeps its exact legacy
    behavior."""
    model_artifact_role = {"role_name": "model_artifact", "applicability": "required"}
    if model_artifact_authoring_boundary_applicability is not None:
        model_artifact_role["authoring_boundary_applicability"] = model_artifact_authoring_boundary_applicability
    return {
        "schema_version": "capability-profile.v1",
        "artifact_type": "capability_profile",
        "capability_profile_id": "binary-predictive-classification",
        "capability_profile_version": "v1",
        "support_status": "current_supported",
        "semantic_requirements": {"target_semantics_applicability": "required"},
        "artifact_roles": [
            {"role_name": "discovery_evidence", "applicability": "required"},
            {"role_name": "semantic_intent", "applicability": "required"},
            {"role_name": "preparation_recipe", "applicability": "required"},
            model_artifact_role,
            {"role_name": "visual_evidence", "applicability": "optional"},
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


def _no_model_analysis_profile() -> dict:
    """A future-architecture-probe profile: syntactically representable but
    never operationally supported for contract projection."""
    return {
        "schema_version": "capability-profile.v1",
        "artifact_type": "capability_profile",
        "capability_profile_id": "non-predictive-dataset-analysis",
        "capability_profile_version": "v1",
        "support_status": "future_architecture_probe",
        "semantic_requirements": {"target_semantics_applicability": "forbidden"},
        "artifact_roles": [
            {"role_name": "discovery_evidence", "applicability": "required"},
            {"role_name": "semantic_intent", "applicability": "required"},
            {"role_name": "model_artifact", "applicability": "forbidden"},
        ],
        "prediction_runtime": {"applicable": False, "mode": "none"},
        "publication": {"public_prediction_capability_applicability": "forbidden"},
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


BINARY_CLASSIFICATION_ROLES = {
    "discovery_evidence": b'{"schema_version": "dataset-discovery-evidence.v1"}',
    "preparation_recipe": b'{"schema_version": "candidate-preparation-recipe.v1"}',
    "model_artifact": b"synthetic-inert-opaque-model-bytes-not-a-real-joblib-file",
}


def _semantic_intent_doc(profile: dict, *, include_target: bool, dataset_slug: str = DATASET_SLUG) -> dict:
    document = {
        "schema_version": "dataset-semantic-intent.v1",
        "artifact_type": "dataset_semantic_intent",
        "dataset_identity": {"dataset_slug": dataset_slug},
        "authoring_generation_id": AUTHORING_GENERATION_ID,
        "governing_capability_profile": {
            "capability_profile_id": profile["capability_profile_id"],
            "capability_profile_version": profile["capability_profile_version"],
        },
        "field_role_decisions": [
            {"field_name": "tenure_months", "role": "feature", "include_in_features": True},
        ],
        "semantic_boundary_confirmations": {
            "observed_source_statistics_embedded": False,
            "scientific_conclusions_embedded": False,
            "training_outcome_embedded": False,
            "release_state_embedded": False,
            "model_bytes_embedded": False,
        },
        "generated_at": "2026-08-07T00:00:00+00:00",
    }
    if include_target:
        document["target_semantics"] = {
            "target_field_name": "churned",
            "task_type": "binary_classification",
            "positive_class": {"class_id": "yes", "event_label": "churn"},
            "is_final_training_configuration": False,
        }
    return document


def _build_repo(
    tmp_path: Path,
    profile: dict,
    roles: dict[str, bytes],
    *,
    semantic_intent: dict | None = "default",
    dataset_slug: str = DATASET_SLUG,
    authoring_generation_id: str = AUTHORING_GENERATION_ID,
    manifest_dataset_slug: str | None = None,
    manifest_profile_selection: dict | None = None,
    declared_capability_profile_id: str | None = None,
    declared_capability_profile_version: str | None = None,
    include_runtime_contract: bool = True,
) -> dict:
    """Build a tmp_path-rooted governed-artifact tree (authoring manifest,
    capability profile, role artifacts, optional semantic intent, optional
    runtime contract) and return the matching capability-aware
    source-contract-input instance. `semantic_intent="default"` builds a
    profile-appropriate semantic-intent fixture and wires it in as the
    manifest's own `semantic_intent` role reference (never a separate
    top-level source-input field); pass `None` to omit it entirely."""
    if manifest_dataset_slug is None:
        manifest_dataset_slug = dataset_slug

    artifact_refs = []
    for role_name, data in roles.items():
        path = tmp_path / "pipeline" / "evidence" / f"{role_name}.json"
        _write_bytes(path, data)
        artifact_refs.append(
            {
                "role": role_name,
                "path": str(path.relative_to(tmp_path)),
                "sha256": _sha256_bytes(data),
                "contract_version": f"{role_name}.v1",
            }
        )

    if semantic_intent == "default":
        semantic_intent = _semantic_intent_doc(profile, include_target=True, dataset_slug=dataset_slug)
    if semantic_intent is not None:
        semantic_path = tmp_path / "pipeline" / "evidence" / "semantic_intent.json"
        semantic_bytes = _write_json(semantic_path, semantic_intent)
        artifact_refs.append(
            {
                "role": "semantic_intent",
                "path": str(semantic_path.relative_to(tmp_path)),
                "sha256": _sha256_bytes(semantic_bytes),
                "contract_version": "dataset-semantic-intent.v1",
            }
        )

    manifest = {
        "schema_version": "dataset-integration-authoring-manifest.v1",
        "artifact_type": "dataset_integration_authoring_manifest",
        "dataset_identity": {"dataset_slug": manifest_dataset_slug},
        "authoring_generation": {
            "authoring_generation_id": authoring_generation_id,
            "immutable": True,
            "generated_at": "2026-08-07T00:00:00+00:00",
        },
        "capability_profile_selection": manifest_profile_selection
        or {
            "capability_profile_id": profile["capability_profile_id"],
            "capability_profile_version": profile["capability_profile_version"],
        },
        "artifact_references": artifact_refs,
        "provenance": [],
        "boundary_confirmations": {
            "complete_discovery_evidence_embedded": False,
            "complete_semantic_intent_embedded": False,
            "complete_preparation_recipe_embedded": False,
            "training_metrics_embedded": False,
            "model_selection_payload_embedded": False,
            "model_bytes_embedded": False,
            "inference_bundle_payload_embedded": False,
            "visual_payloads_embedded": False,
            "absolute_external_project_root_present": False,
            "external_analysis_handoff_replacement": False,
            "operational_importer_instruction_present": False,
        },
        "generated_at": "2026-08-07T00:00:00+00:00",
    }
    manifest_path = tmp_path / "pipeline" / "authoring-manifest.json"
    manifest_bytes = _write_json(manifest_path, manifest)

    profile_path = tmp_path / "pipeline" / "capability-profile.json"
    profile_bytes = _write_json(profile_path, profile)

    source_input = {
        "schema_version": "source-contract-input.v1",
        "dataset_slug": dataset_slug,
        "release_id": "release-0001",
        "source_data_ref": "sample-study",
        "authoring_generation_id": authoring_generation_id,
        "authoring_manifest_ref": {
            "path": str(manifest_path.relative_to(tmp_path)),
            "sha256": _sha256_bytes(manifest_bytes),
        },
        "capability_profile_id": declared_capability_profile_id or profile["capability_profile_id"],
        "capability_profile_version": declared_capability_profile_version or profile["capability_profile_version"],
        "capability_profile_ref": {
            "path": str(profile_path.relative_to(tmp_path)),
            "sha256": _sha256_bytes(profile_bytes),
        },
    }

    if include_runtime_contract:
        runtime_path = tmp_path / "contracts" / "runtime-contract.json"
        _write_json(runtime_path, RUNTIME_CONTRACT)
        source_input["source_contract_ref"] = str(runtime_path.relative_to(tmp_path))

    return source_input


class TestSourceContractInputSchemaBackwardCompatibility:
    def test_schema_is_valid_json_schema(self):
        schema = json.loads(SOURCE_CONTRACT_INPUT_SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)

    def test_historical_v1_only_instance_remains_valid(self):
        schema = json.loads(SOURCE_CONTRACT_INPUT_SCHEMA_PATH.read_text(encoding="utf-8"))
        v1_instance = {
            "schema_version": "source-contract-input.v1",
            "dataset_slug": "telco-customer-churn",
            "release_id": "release-20260620-001",
            "source_contract_ref": "contracts/runtime-contract.schema.json",
            "source_data_ref": "telco-customer-churn-study",
        }
        jsonschema.validate(v1_instance, schema)

    def test_partial_capability_aware_fields_are_rejected(self):
        schema = json.loads(SOURCE_CONTRACT_INPUT_SCHEMA_PATH.read_text(encoding="utf-8"))
        instance = {
            "schema_version": "source-contract-input.v1",
            "dataset_slug": "telco-customer-churn",
            "release_id": "release-20260620-001",
            "source_contract_ref": "contracts/runtime-contract.schema.json",
            "source_data_ref": "telco-customer-churn-study",
            "capability_profile_id": "binary-predictive-classification",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance, schema)

    def test_absolute_authoring_manifest_ref_path_is_rejected(self, tmp_path):
        schema = json.loads(SOURCE_CONTRACT_INPUT_SCHEMA_PATH.read_text(encoding="utf-8"))
        source_input = _build_repo(tmp_path, _binary_classification_profile(), BINARY_CLASSIFICATION_ROLES)
        source_input["authoring_manifest_ref"]["path"] = "/etc/passwd"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(source_input, schema)


class TestValidCurrentBinaryClassificationProjection:
    def test_valid_projection_is_accepted(self, tmp_path):
        source_input = _build_repo(tmp_path, _binary_classification_profile(), BINARY_CLASSIFICATION_ROLES)

        result = project_capability_aware_source_contract(source_input, repo_root=tmp_path)

        assert isinstance(result, CapabilityProjectionResult)
        assert result.status == "accepted"
        assert result.rejection_phase is None
        assert result.rejection_reason is None
        assert result.dataset_slug == DATASET_SLUG
        assert result.capability_profile_id == CURRENTLY_SUPPORTED_CAPABILITY_PROFILE_ID
        assert result.capability_support_status == "current_supported"
        assert result.runtime_contract == RUNTIME_CONTRACT
        assert result.public_contract["schema_version"] == "1.0.0"
        assert result.public_contract["features"] == [
            {
                "name": "tenure_months",
                "input_type": "number",
                "optional": False,
                "label": "Tenure Months",
                "display_order": 1,
            }
        ]

    def test_valid_projection_via_build_entrypoint(self, tmp_path, monkeypatch):
        source_input = _build_repo(tmp_path, _binary_classification_profile(), BINARY_CLASSIFICATION_ROLES)
        input_path = tmp_path / "source-input.json"
        input_path.write_text(json.dumps(source_input), encoding="utf-8")

        monkeypatch.setattr(build, "REPO_ROOT", tmp_path)

        assert build._is_capability_aware(source_input) is True

        schema, schema_err = build._load_json(str(build.SCHEMA_PATH))
        assert schema_err is None
        assert build._validate(source_input, schema) == []

        result = build.project_capability_aware_source_contract(source_input, repo_root=build.REPO_ROOT)
        assert result.status == "accepted"
        acceptance = build._capability_acceptance(result, str(input_path))
        assert acceptance["status"] == "accepted"
        assert acceptance["capability_profile_id"] == CURRENTLY_SUPPORTED_CAPABILITY_PROFILE_ID


class TestMissingRequiredRole:
    def test_missing_required_role_is_rejected(self, tmp_path):
        roles = dict(BINARY_CLASSIFICATION_ROLES)
        del roles["model_artifact"]
        source_input = _build_repo(tmp_path, _binary_classification_profile(), roles)

        result = project_capability_aware_source_contract(source_input, repo_root=tmp_path)

        assert result.status == "rejected"
        assert result.rejection_phase == "authoring_boundary_validation"
        assert result.authoring_boundary_valid is False
        assert "required_role_missing" in result.rejection_reason
        assert "model_artifact" in result.rejection_reason
        assert result.runtime_contract is None
        assert result.public_contract is None


class TestAuthoringBoundaryApplicabilityOverrideReachesProjection:
    """Project Spec S0185: a valid pre-materialization authoring manifest
    without model_artifact must be able to pass the authoring boundary and
    reach the existing capability-aware projector, when the profile
    additively declares model_artifact.authoring_boundary_applicability ==
    optional. Never weakens capability identity/hash verification."""

    def test_pre_materialization_manifest_without_model_artifact_reaches_projection(self, tmp_path):
        profile = _binary_classification_profile(model_artifact_authoring_boundary_applicability="optional")
        roles = {role_name: data for role_name, data in BINARY_CLASSIFICATION_ROLES.items() if role_name != "model_artifact"}
        source_input = _build_repo(tmp_path, profile, roles)

        result = project_capability_aware_source_contract(source_input, repo_root=tmp_path)

        assert result.status == "accepted"
        assert result.rejection_phase is None
        assert result.authoring_boundary_valid is True
        assert result.runtime_contract == RUNTIME_CONTRACT
        assert result.capability_profile_id == CURRENTLY_SUPPORTED_CAPABILITY_PROFILE_ID


class TestOptionalRoleAbsence:
    def test_optional_role_absent_is_still_accepted(self, tmp_path):
        source_input = _build_repo(tmp_path, _binary_classification_profile(), BINARY_CLASSIFICATION_ROLES)
        manifest_path = tmp_path / source_input["authoring_manifest_ref"]["path"]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert "visual_evidence" not in {ref["role"] for ref in manifest["artifact_references"]}

        result = project_capability_aware_source_contract(source_input, repo_root=tmp_path)

        assert result.status == "accepted"


class TestForbiddenRolePresence:
    def test_forbidden_role_present_is_rejected(self, tmp_path):
        roles = dict(BINARY_CLASSIFICATION_ROLES)
        roles["no_model_analysis_summary"] = b"forbidden-role-payload"
        source_input = _build_repo(tmp_path, _binary_classification_profile(), roles)

        result = project_capability_aware_source_contract(source_input, repo_root=tmp_path)

        assert result.status == "rejected"
        assert result.rejection_phase == "authoring_boundary_validation"
        assert "forbidden_role_present" in result.rejection_reason
        assert "no_model_analysis_summary" in result.rejection_reason


class TestProfileMismatch:
    def test_manifest_capability_selection_disagrees_with_profile_document(self, tmp_path):
        profile = _binary_classification_profile()
        source_input = _build_repo(
            tmp_path,
            profile,
            BINARY_CLASSIFICATION_ROLES,
            manifest_profile_selection={
                "capability_profile_id": profile["capability_profile_id"],
                "capability_profile_version": "v2",
            },
            declared_capability_profile_version="v2",
        )

        result = project_capability_aware_source_contract(source_input, repo_root=tmp_path)

        assert result.status == "rejected"
        assert result.rejection_phase == "authoring_boundary_validation"
        assert "capability_profile_identity_mismatch" in result.rejection_reason

    def test_declared_capability_version_disagrees_with_validated_manifest_selection(self, tmp_path):
        profile = _binary_classification_profile()
        source_input = _build_repo(tmp_path, profile, BINARY_CLASSIFICATION_ROLES)
        # Manifest/profile agree with each other (boundary is valid), but the
        # source-contract-input's own declared version silently drifts --
        # this must still be caught independently (defense in depth).
        source_input["capability_profile_version"] = "v2"

        result = project_capability_aware_source_contract(source_input, repo_root=tmp_path)

        assert result.status == "rejected"
        assert result.rejection_phase == "capability_profile_identity_mismatch"
        assert result.authoring_boundary_valid is True


class TestDatasetIdentityMismatch:
    def test_semantic_intent_dataset_slug_mismatch_is_rejected(self, tmp_path):
        profile = _binary_classification_profile()
        mismatched_semantic_intent = _semantic_intent_doc(profile, include_target=True, dataset_slug="a-different-dataset")
        source_input = _build_repo(
            tmp_path, profile, BINARY_CLASSIFICATION_ROLES, semantic_intent=mismatched_semantic_intent
        )

        result = project_capability_aware_source_contract(source_input, repo_root=tmp_path)

        assert result.status == "rejected"
        assert result.rejection_phase == "authoring_boundary_validation"
        assert "dataset_identity_mismatch" in result.rejection_reason

    def test_source_input_dataset_slug_mismatch_is_rejected(self, tmp_path):
        profile = _binary_classification_profile()
        source_input = _build_repo(
            tmp_path, profile, BINARY_CLASSIFICATION_ROLES, manifest_dataset_slug=DATASET_SLUG
        )
        source_input["dataset_slug"] = "not-the-real-dataset"

        result = project_capability_aware_source_contract(source_input, repo_root=tmp_path)

        assert result.status == "rejected"
        assert result.rejection_phase == "authoring_boundary_validation"
        assert "dataset_slug_mismatch" in result.rejection_reason


class TestUnsupportedCapabilityFailsClosed:
    def test_future_architecture_probe_fails_closed(self, tmp_path):
        profile = _no_model_analysis_profile()
        roles = {"discovery_evidence": b'{"schema_version": "dataset-discovery-evidence.v1"}'}
        semantic_intent = _semantic_intent_doc(profile, include_target=False)
        source_input = _build_repo(tmp_path, profile, roles, semantic_intent=semantic_intent)

        result = project_capability_aware_source_contract(source_input, repo_root=tmp_path)

        assert result.status == "rejected"
        assert result.rejection_phase == "capability_unsupported"
        assert result.capability_support_status == "future_architecture_probe"
        assert result.authoring_boundary_valid is True
        # Fail closed: never fabricates a runtime/public contract for an
        # unsupported capability, even though the authoring boundary itself
        # is perfectly valid.
        assert result.runtime_contract is None
        assert result.public_contract is None

    def test_currently_supported_status_alone_is_not_sufficient_without_known_capability_id(self, tmp_path):
        """A profile could (hypothetically) declare support_status
        'current_supported' for a capability_profile_id this module has no
        explicit projection code for. That must still fail closed rather
        than silently reusing the binary-classification projection."""
        profile = _no_model_analysis_profile()
        profile["support_status"] = "current_supported"
        roles = {"discovery_evidence": b'{"schema_version": "dataset-discovery-evidence.v1"}'}
        semantic_intent = _semantic_intent_doc(profile, include_target=False)
        source_input = _build_repo(tmp_path, profile, roles, semantic_intent=semantic_intent)

        result = project_capability_aware_source_contract(source_input, repo_root=tmp_path)

        assert result.status == "rejected"
        assert result.rejection_phase == "capability_unsupported"
        assert result.public_contract is None


def _multiclass_classification_profile(*, support_status: str = "requires_future_contract_evolution") -> dict:
    """Mirrors the real committed
    pipeline/capabilities/multiclass-predictive-classification.v1.json
    profile shape (same capability_profile_id/version, same artifact role
    set). support_status defaults to the real committed value
    (requires_future_contract_evolution); pass 'current_supported' to build
    a synthetic clone that proves the contract-projection layer is
    implemented, without ever mutating the committed profile file."""
    return {
        "schema_version": "capability-profile.v1",
        "artifact_type": "capability_profile",
        "capability_profile_id": "multiclass-predictive-classification",
        "capability_profile_version": "v1",
        "support_status": support_status,
        "semantic_requirements": {"target_semantics_applicability": "required"},
        "artifact_roles": [
            {"role_name": "discovery_evidence", "applicability": "required"},
            {"role_name": "semantic_intent", "applicability": "required"},
            {"role_name": "preparation_recipe", "applicability": "required"},
            {"role_name": "model_artifact", "applicability": "required", "authoring_boundary_applicability": "optional"},
            {"role_name": "visual_evidence", "applicability": "optional"},
            {"role_name": "no_model_analysis_summary", "applicability": "forbidden"},
        ],
        "prediction_runtime": {
            "applicable": True,
            "mode": "single_model_multiclass_classification",
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
        "generated_at": "2026-08-16T00:00:00+00:00",
    }


def _multiclass_semantic_intent_doc(profile: dict, *, include_target: bool, dataset_slug: str = DATASET_SLUG) -> dict:
    document = {
        "schema_version": "dataset-semantic-intent.v2",
        "artifact_type": "dataset_semantic_intent",
        "dataset_identity": {"dataset_slug": dataset_slug},
        "authoring_generation_id": AUTHORING_GENERATION_ID,
        "governing_capability_profile": {
            "capability_profile_id": profile["capability_profile_id"],
            "capability_profile_version": profile["capability_profile_version"],
        },
        "field_role_decisions": [
            {"field_name": "tenure_months", "role": "feature", "include_in_features": True},
        ],
        "semantic_boundary_confirmations": {
            "observed_source_statistics_embedded": False,
            "scientific_conclusions_embedded": False,
            "training_outcome_embedded": False,
            "release_state_embedded": False,
            "model_bytes_embedded": False,
        },
        "generated_at": "2026-08-16T00:00:00+00:00",
    }
    if include_target:
        document["target_semantics"] = {
            "target_field_name": "segment",
            "task_type": "multiclass_classification",
            "classes": [
                {"class_id": "class-a", "display_label": "Class A"},
                {"class_id": "class-b", "display_label": "Class B"},
                {"class_id": "class-c", "display_label": "Class C"},
            ],
            "is_final_training_configuration": False,
        }
    return document


class TestMulticlassCapabilityContractProjection:
    """Project Spec S0209 Desired Change M / acceptance criteria 39-41:
    contract_derivation explicitly knows both binary and multiclass
    capability identities. A synthetic multiclass profile whose
    support_status is not current_supported still rejects (this is the
    generic, permanent lifecycle fail-closed behavior for any not-yet-
    activated capability, preserved unchanged by Project Spec S0216); the
    real committed multiclass profile itself was later activated to
    support_status: current_supported once every S0216 native gate passed
    (see tests/pipeline/test_multiclass_predictive_classification_capability_profile.py
    for real-file coverage), which is the same synthetic-current_supported
    acceptance path already proven below."""

    def test_synthetic_future_status_multiclass_profile_still_rejects(self, tmp_path):
        profile = _multiclass_classification_profile()
        semantic_intent = _multiclass_semantic_intent_doc(profile, include_target=True)
        source_input = _build_repo(tmp_path, profile, BINARY_CLASSIFICATION_ROLES, semantic_intent=semantic_intent)

        result = project_capability_aware_source_contract(source_input, repo_root=tmp_path)

        assert result.status == "rejected"
        assert result.rejection_phase == "capability_unsupported"
        assert result.capability_support_status == "requires_future_contract_evolution"
        assert result.runtime_contract is None
        assert result.public_contract is None

    def test_synthetic_current_supported_multiclass_profile_is_accepted(self, tmp_path):
        profile = _multiclass_classification_profile(support_status="current_supported")
        semantic_intent = _multiclass_semantic_intent_doc(profile, include_target=True)
        source_input = _build_repo(tmp_path, profile, BINARY_CLASSIFICATION_ROLES, semantic_intent=semantic_intent)

        result = project_capability_aware_source_contract(source_input, repo_root=tmp_path)

        assert result.status == "accepted"
        assert result.rejection_phase is None
        assert result.capability_profile_id == "multiclass-predictive-classification"
        assert result.capability_support_status == "current_supported"
        assert result.runtime_contract == RUNTIME_CONTRACT
        assert result.public_contract is not None

    def test_binary_current_supported_behavior_remains_unchanged(self, tmp_path):
        source_input = _build_repo(tmp_path, _binary_classification_profile(), BINARY_CLASSIFICATION_ROLES)

        result = project_capability_aware_source_contract(source_input, repo_root=tmp_path)

        assert result.status == "accepted"
        assert result.capability_profile_id == CURRENTLY_SUPPORTED_CAPABILITY_PROFILE_ID

    def test_unknown_capability_still_rejects_even_when_current_supported(self, tmp_path):
        profile = _no_model_analysis_profile()
        profile["support_status"] = "current_supported"
        roles = {"discovery_evidence": b'{"schema_version": "dataset-discovery-evidence.v1"}'}
        semantic_intent = _semantic_intent_doc(profile, include_target=False)
        source_input = _build_repo(tmp_path, profile, roles, semantic_intent=semantic_intent)

        result = project_capability_aware_source_contract(source_input, repo_root=tmp_path)

        assert result.status == "rejected"
        assert result.rejection_phase == "capability_unsupported"
        assert result.public_contract is None

    def test_multiclass_capability_id_is_a_member_of_the_supported_set(self):
        assert "multiclass-predictive-classification" in CONTRACT_PROJECTION_SUPPORTED_CAPABILITY_PROFILE_IDS
        assert CURRENTLY_SUPPORTED_CAPABILITY_PROFILE_ID in CONTRACT_PROJECTION_SUPPORTED_CAPABILITY_PROFILE_IDS


class TestNoDatasetNameBranching:
    _NEW_FUNCTIONS = (
        contract_derivation.project_capability_aware_source_contract,
        contract_derivation.resolve_manifest_role_reference,
        contract_derivation._load_governed_reference,
        contract_derivation._resolve_repo_relative,
        build.main,
        build._is_capability_aware,
    )

    def test_new_capability_aware_code_contains_no_telco_reference(self):
        combined_source = "\n".join(inspect.getsource(fn) for fn in self._NEW_FUNCTIONS)
        assert "telco" not in combined_source.lower()

    def test_new_capability_aware_code_contains_no_hardcoded_dataset_slug_comparison(self):
        combined_source = "\n".join(inspect.getsource(fn) for fn in self._NEW_FUNCTIONS)
        assert re.search(r'dataset_slug\s*==\s*["\']', combined_source) is None

    def test_currently_supported_capability_profile_id_is_an_architecture_identity_not_a_dataset_slug(self):
        assert DATASET_SLUG not in CURRENTLY_SUPPORTED_CAPABILITY_PROFILE_ID
        assert "telco" not in CURRENTLY_SUPPORTED_CAPABILITY_PROFILE_ID


class TestResolveManifestRoleReference:
    def test_resolves_present_role(self, tmp_path):
        source_input = _build_repo(tmp_path, _binary_classification_profile(), BINARY_CLASSIFICATION_ROLES)
        manifest_path = tmp_path / source_input["authoring_manifest_ref"]["path"]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        entry = resolve_manifest_role_reference(manifest, "model_artifact")

        assert entry is not None
        assert entry["role"] == "model_artifact"

    def test_returns_none_for_absent_role(self, tmp_path):
        source_input = _build_repo(tmp_path, _binary_classification_profile(), BINARY_CLASSIFICATION_ROLES)
        manifest_path = tmp_path / source_input["authoring_manifest_ref"]["path"]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        assert resolve_manifest_role_reference(manifest, "visual_evidence") is None


class TestGovernedReferenceIntegrity:
    def test_authoring_manifest_hash_mismatch_is_rejected(self, tmp_path):
        source_input = _build_repo(tmp_path, _binary_classification_profile(), BINARY_CLASSIFICATION_ROLES)
        source_input["authoring_manifest_ref"]["sha256"] = "0" * 64

        result = project_capability_aware_source_contract(source_input, repo_root=tmp_path)

        assert result.status == "rejected"
        assert result.rejection_phase == "authoring_manifest_read"
        assert "SHA-256 mismatch" in result.rejection_reason

    def test_capability_profile_hash_mismatch_is_rejected(self, tmp_path):
        source_input = _build_repo(tmp_path, _binary_classification_profile(), BINARY_CLASSIFICATION_ROLES)
        source_input["capability_profile_ref"]["sha256"] = "0" * 64

        result = project_capability_aware_source_contract(source_input, repo_root=tmp_path)

        assert result.status == "rejected"
        assert result.rejection_phase == "capability_profile_read"
        assert "SHA-256 mismatch" in result.rejection_reason
