"""
Tests for Project Spec S0166: Dataset Integration Authoring Manifest,
Semantic Intent, Capability Profile, and Provenance Contract.

Uses only synthetic in-memory/temp-path fixtures. Never uses a real model
file, never executes notebook code, and never requires the external Telco
filesystem at runtime. Fixtures use a generic dataset slug to demonstrate
the contracts are capability-driven, not dataset-name-driven.
"""

import hashlib
import inspect
import json
import sys
from pathlib import Path

import jsonschema

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pipeline import authoring_contracts
from pipeline.authoring_contracts import (
    AuthoringContractValidationResult,
    validate_authoring_contracts,
)

REPO_ROOT = Path(__file__).parent.parent.parent
MANIFEST_SCHEMA_PATH = REPO_ROOT / "pipeline" / "dataset-integration-authoring-manifest.schema.json"
SEMANTIC_INTENT_SCHEMA_PATH = REPO_ROOT / "pipeline" / "dataset-semantic-intent.schema.json"
CAPABILITY_PROFILE_SCHEMA_PATH = REPO_ROOT / "pipeline" / "capability-profile.schema.json"


def _load_schema(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


DATASET_SLUG = "sample-binary-classification-dataset"

DISCOVERY_EVIDENCE_BYTES = b'{"schema_version": "dataset-discovery-evidence.v1"}'
SEMANTIC_INTENT_BYTES = b'{"schema_version": "dataset-semantic-intent.v1"}'
PREPARATION_RECIPE_BYTES = b'{"schema_version": "candidate-preparation-recipe.v1"}'
MODEL_ARTIFACT_BYTES = b"synthetic-inert-opaque-model-bytes-not-a-real-joblib-file"


def _binary_classification_profile() -> dict:
    return {
        "schema_version": "capability-profile.v1",
        "artifact_type": "capability_profile",
        "capability_profile_id": "binary-predictive-classification",
        "capability_profile_version": "v1",
        "support_status": "current_supported",
        "semantic_requirements": {
            "target_semantics_applicability": "required",
        },
        "artifact_roles": [
            {"role_name": "discovery_evidence", "applicability": "required"},
            {"role_name": "semantic_intent", "applicability": "required"},
            {"role_name": "preparation_recipe", "applicability": "required"},
            {"role_name": "model_artifact", "applicability": "required"},
            {"role_name": "visual_evidence", "applicability": "optional"},
            {"role_name": "no_model_analysis_summary", "applicability": "forbidden"},
        ],
        "prediction_runtime": {
            "applicable": True,
            "mode": "single_model_binary_classification",
        },
        "publication": {
            "public_prediction_capability_applicability": "optional",
        },
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
    """A future-architecture-probe profile that forbids target semantics
    and forbids model_artifact -- used to prove targetless/forbidden-role
    semantics without ever claiming this probe is currently operational."""
    return {
        "schema_version": "capability-profile.v1",
        "artifact_type": "capability_profile",
        "capability_profile_id": "non-predictive-dataset-analysis",
        "capability_profile_version": "v1",
        "support_status": "future_architecture_probe",
        "semantic_requirements": {
            "target_semantics_applicability": "forbidden",
        },
        "artifact_roles": [
            {"role_name": "discovery_evidence", "applicability": "required"},
            {"role_name": "semantic_intent", "applicability": "required"},
            {"role_name": "model_artifact", "applicability": "forbidden"},
        ],
        "prediction_runtime": {
            "applicable": False,
            "mode": "none",
        },
        "publication": {
            "public_prediction_capability_applicability": "forbidden",
        },
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


def _manifest_for(profile: dict, *, roles: dict[str, bytes]) -> dict:
    artifact_references = [
        {
            "role": role_name,
            "path": f"pipeline/evidence/{DATASET_SLUG}/{role_name}.json",
            "sha256": _sha256_bytes(data),
            "contract_version": f"{role_name}.v1",
        }
        for role_name, data in roles.items()
    ]
    return {
        "schema_version": "dataset-integration-authoring-manifest.v1",
        "artifact_type": "dataset_integration_authoring_manifest",
        "dataset_identity": {"dataset_slug": DATASET_SLUG},
        "authoring_generation": {
            "authoring_generation_id": "authoring-gen-0001",
            "immutable": True,
            "generated_at": "2026-08-07T00:00:00+00:00",
        },
        "capability_profile_selection": {
            "capability_profile_id": profile["capability_profile_id"],
            "capability_profile_version": profile["capability_profile_version"],
        },
        "artifact_references": artifact_references,
        "provenance": [
            {
                "logical_producer_project_id": "atlas-dataflow",
                "artifact_role": role_name,
                "artifact_type": role_name,
                "artifact_version": "v1",
                "relative_path": f"pipeline/evidence/{DATASET_SLUG}/{role_name}.json",
                "sha256": _sha256_bytes(data),
                "producer_revision_known": False,
                "producer_revision": None,
                "input_references": [],
            }
            for role_name, data in roles.items()
        ],
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


def _semantic_intent_for(profile: dict, *, include_target: bool) -> dict:
    document = {
        "schema_version": "dataset-semantic-intent.v1",
        "artifact_type": "dataset_semantic_intent",
        "dataset_identity": {"dataset_slug": DATASET_SLUG},
        "authoring_generation_id": "authoring-gen-0001",
        "governing_capability_profile": {
            "capability_profile_id": profile["capability_profile_id"],
            "capability_profile_version": profile["capability_profile_version"],
        },
        "field_role_decisions": [
            {"field_name": "customer_id", "role": "identifier", "include_in_features": False},
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


BINARY_CLASSIFICATION_ROLES = {
    "discovery_evidence": DISCOVERY_EVIDENCE_BYTES,
    "semantic_intent": SEMANTIC_INTENT_BYTES,
    "preparation_recipe": PREPARATION_RECIPE_BYTES,
    "model_artifact": MODEL_ARTIFACT_BYTES,
}


def _binary_classification_profile_with_authoring_override() -> dict:
    """The same binary-classification profile, with model_artifact's
    authoring-boundary applicability additively overridden to 'optional'
    -- mirrors S0185's real pipeline/capabilities/binary-predictive-
    classification.v1.json reconciliation without touching the shared
    fixture other tests rely on for legacy behavior."""
    profile = _binary_classification_profile()
    for role_entry in profile["artifact_roles"]:
        if role_entry["role_name"] == "model_artifact":
            role_entry["authoring_boundary_applicability"] = "optional"
    return profile


class TestSchemasAreValidJsonSchema:
    def test_manifest_schema_is_valid_json_schema(self):
        schema = _load_schema(MANIFEST_SCHEMA_PATH)
        jsonschema.Draft202012Validator.check_schema(schema)

    def test_semantic_intent_schema_is_valid_json_schema(self):
        schema = _load_schema(SEMANTIC_INTENT_SCHEMA_PATH)
        jsonschema.Draft202012Validator.check_schema(schema)

    def test_capability_profile_schema_is_valid_json_schema(self):
        schema = _load_schema(CAPABILITY_PROFILE_SCHEMA_PATH)
        jsonschema.Draft202012Validator.check_schema(schema)


class TestValidCurrentBinaryClassificationAuthoringContract:
    def test_valid_manifest_profile_and_semantic_intent_pass(self):
        profile = _binary_classification_profile()
        manifest = _manifest_for(profile, roles=BINARY_CLASSIFICATION_ROLES)
        semantic_intent = _semantic_intent_for(profile, include_target=True)

        result = validate_authoring_contracts(
            manifest, profile, semantic_intent=semantic_intent, expected_dataset_slug=DATASET_SLUG
        )

        assert isinstance(result, AuthoringContractValidationResult)
        assert result.manifest_schema_valid is True
        assert result.semantic_intent_schema_valid is True
        assert result.capability_profile_schema_valid is True
        assert result.valid is True
        assert result.failures == ()
        assert result.dataset_slug == DATASET_SLUG
        assert result.capability_profile_id == "binary-predictive-classification"
        assert result.capability_profile_version == "v1"

    def test_valid_manifest_hash_verification_against_real_artifact_root(self, tmp_path):
        profile = _binary_classification_profile()
        manifest = _manifest_for(profile, roles=BINARY_CLASSIFICATION_ROLES)

        for role_name, data in BINARY_CLASSIFICATION_ROLES.items():
            artifact_path = tmp_path / "pipeline" / "evidence" / DATASET_SLUG / f"{role_name}.json"
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_bytes(data)

        result = validate_authoring_contracts(manifest, profile, artifact_root=tmp_path)

        assert result.valid is True
        assert result.failures == ()


class TestMalformedSha256:
    def test_uppercase_sha256_fails_schema_validation(self):
        profile = _binary_classification_profile()
        manifest = _manifest_for(profile, roles=BINARY_CLASSIFICATION_ROLES)
        manifest["artifact_references"][0]["sha256"] = manifest["artifact_references"][0]["sha256"].upper()

        result = validate_authoring_contracts(manifest, profile)

        assert result.manifest_schema_valid is False
        assert result.valid is False
        assert any(failure.code == "schema_validation_failed" for failure in result.failures)

    def test_short_sha256_fails_schema_validation(self):
        profile = _binary_classification_profile()
        manifest = _manifest_for(profile, roles=BINARY_CLASSIFICATION_ROLES)
        manifest["artifact_references"][0]["sha256"] = "abc123"

        result = validate_authoring_contracts(manifest, profile)

        assert result.valid is False
        assert result.manifest_schema_valid is False


class TestAbsolutePathRejection:
    def test_absolute_path_fails_schema_validation(self):
        profile = _binary_classification_profile()
        manifest = _manifest_for(profile, roles=BINARY_CLASSIFICATION_ROLES)
        manifest["artifact_references"][0]["path"] = "/etc/passwd"

        result = validate_authoring_contracts(manifest, profile)

        assert result.manifest_schema_valid is False
        assert result.valid is False


class TestPathTraversalRejection:
    def test_traversal_path_fails_schema_validation(self):
        profile = _binary_classification_profile()
        manifest = _manifest_for(profile, roles=BINARY_CLASSIFICATION_ROLES)
        manifest["artifact_references"][0]["path"] = "../../etc/passwd"

        result = validate_authoring_contracts(manifest, profile)

        assert result.manifest_schema_valid is False
        assert result.valid is False


class TestMissingRequiredRole:
    def test_missing_required_role_is_rejected(self):
        profile = _binary_classification_profile()
        roles = dict(BINARY_CLASSIFICATION_ROLES)
        del roles["model_artifact"]
        manifest = _manifest_for(profile, roles=roles)

        result = validate_authoring_contracts(manifest, profile)

        assert result.manifest_schema_valid is True
        assert result.valid is False
        assert any(
            failure.code == "required_role_missing" and failure.role == "model_artifact"
            for failure in result.failures
        )


class TestForbiddenRolePresence:
    def test_forbidden_role_present_is_rejected(self):
        profile = _binary_classification_profile()
        roles = dict(BINARY_CLASSIFICATION_ROLES)
        roles["no_model_analysis_summary"] = b"forbidden-role-payload"
        manifest = _manifest_for(profile, roles=roles)

        result = validate_authoring_contracts(manifest, profile)

        assert result.manifest_schema_valid is True
        assert result.valid is False
        assert any(
            failure.code == "forbidden_role_present" and failure.role == "no_model_analysis_summary"
            for failure in result.failures
        )


class TestOptionalRoleAbsence:
    def test_optional_role_absent_is_accepted(self):
        profile = _binary_classification_profile()
        manifest = _manifest_for(profile, roles=BINARY_CLASSIFICATION_ROLES)
        assert "visual_evidence" not in {ref["role"] for ref in manifest["artifact_references"]}

        result = validate_authoring_contracts(manifest, profile)

        assert result.valid is True
        assert not any(failure.role == "visual_evidence" for failure in result.failures)


class TestProfileMismatch:
    def test_capability_profile_version_mismatch_is_rejected(self):
        profile = _binary_classification_profile()
        manifest = _manifest_for(profile, roles=BINARY_CLASSIFICATION_ROLES)
        manifest["capability_profile_selection"]["capability_profile_version"] = "v2"

        result = validate_authoring_contracts(manifest, profile)

        assert result.manifest_schema_valid is True
        assert result.capability_profile_schema_valid is True
        assert result.valid is False
        assert any(failure.code == "capability_profile_identity_mismatch" for failure in result.failures)

    def test_capability_profile_id_mismatch_is_rejected(self):
        profile = _binary_classification_profile()
        manifest = _manifest_for(profile, roles=BINARY_CLASSIFICATION_ROLES)
        manifest["capability_profile_selection"]["capability_profile_id"] = "some-other-profile"

        result = validate_authoring_contracts(manifest, profile)

        assert result.valid is False
        assert any(failure.code == "capability_profile_identity_mismatch" for failure in result.failures)


class TestDatasetIdentityMismatch:
    def test_semantic_intent_dataset_slug_mismatch_is_rejected(self):
        profile = _binary_classification_profile()
        manifest = _manifest_for(profile, roles=BINARY_CLASSIFICATION_ROLES)
        semantic_intent = _semantic_intent_for(profile, include_target=True)
        semantic_intent["dataset_identity"]["dataset_slug"] = "a-different-dataset"

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.manifest_schema_valid is True
        assert result.semantic_intent_schema_valid is True
        assert result.valid is False
        assert any(failure.code == "dataset_identity_mismatch" for failure in result.failures)

    def test_expected_dataset_slug_mismatch_is_rejected(self):
        profile = _binary_classification_profile()
        manifest = _manifest_for(profile, roles=BINARY_CLASSIFICATION_ROLES)

        result = validate_authoring_contracts(manifest, profile, expected_dataset_slug="not-the-real-dataset")

        assert result.valid is False
        assert any(failure.code == "dataset_slug_mismatch" for failure in result.failures)


class TestTargetApplicabilityMismatch:
    def test_target_semantics_present_when_profile_forbids_target_is_rejected(self):
        profile = _no_model_analysis_profile()
        manifest = _manifest_for(
            profile,
            roles={"discovery_evidence": DISCOVERY_EVIDENCE_BYTES, "semantic_intent": SEMANTIC_INTENT_BYTES},
        )
        semantic_intent = _semantic_intent_for(profile, include_target=True)

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.manifest_schema_valid is True
        assert result.semantic_intent_schema_valid is True
        assert result.valid is False
        assert any(failure.code == "target_semantics_forbidden_but_present" for failure in result.failures)

    def test_targetless_semantic_intent_requires_no_dummy_target_fields(self):
        profile = _no_model_analysis_profile()
        manifest = _manifest_for(
            profile,
            roles={"discovery_evidence": DISCOVERY_EVIDENCE_BYTES, "semantic_intent": SEMANTIC_INTENT_BYTES},
        )
        semantic_intent = _semantic_intent_for(profile, include_target=False)
        assert "target_semantics" not in semantic_intent

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.valid is True
        assert result.failures == ()
        assert profile["support_status"] == "future_architecture_probe"

    def test_target_semantics_absent_when_profile_requires_target_is_rejected(self):
        profile = _binary_classification_profile()
        manifest = _manifest_for(profile, roles=BINARY_CLASSIFICATION_ROLES)
        semantic_intent = _semantic_intent_for(profile, include_target=False)

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.valid is False
        assert any(failure.code == "target_semantics_required_but_absent" for failure in result.failures)


class TestNoUnsupportedCapabilityLabeledOperational:
    def test_only_binary_classification_profile_is_current_supported(self):
        assert _binary_classification_profile()["support_status"] == "current_supported"
        assert _no_model_analysis_profile()["support_status"] != "current_supported"

    def test_capability_profile_ids_never_encode_dataset_identity(self):
        for profile in (_binary_classification_profile(), _no_model_analysis_profile()):
            assert DATASET_SLUG not in profile["capability_profile_id"]


class TestAuthoringBoundaryApplicabilityOverride:
    """Project Spec S0185: proves validate_authoring_contracts resolves each
    role's authoring-boundary applicability from an additive
    authoring_boundary_applicability override when declared, and falls back
    to the existing global applicability field unchanged otherwise."""

    def test_legacy_profile_without_override_keeps_old_behavior(self):
        profile = _binary_classification_profile()
        assert not any("authoring_boundary_applicability" in entry for entry in profile["artifact_roles"])
        roles = dict(BINARY_CLASSIFICATION_ROLES)
        del roles["model_artifact"]
        manifest = _manifest_for(profile, roles=roles)

        result = validate_authoring_contracts(manifest, profile)

        assert result.valid is False
        assert any(
            failure.code == "required_role_missing" and failure.role == "model_artifact"
            for failure in result.failures
        )

    def test_authoring_boundary_optional_override_allows_role_absence(self):
        profile = _binary_classification_profile_with_authoring_override()
        roles = dict(BINARY_CLASSIFICATION_ROLES)
        del roles["model_artifact"]
        manifest = _manifest_for(profile, roles=roles)

        result = validate_authoring_contracts(manifest, profile)

        assert result.valid is True
        assert result.failures == ()

    def test_required_preparation_recipe_remains_required_under_override(self):
        profile = _binary_classification_profile_with_authoring_override()
        roles = dict(BINARY_CLASSIFICATION_ROLES)
        del roles["model_artifact"]
        del roles["preparation_recipe"]
        manifest = _manifest_for(profile, roles=roles)

        result = validate_authoring_contracts(manifest, profile)

        assert result.valid is False
        assert any(
            failure.code == "required_role_missing" and failure.role == "preparation_recipe"
            for failure in result.failures
        )

    def test_forbidden_authoring_role_remains_rejected_under_override(self):
        profile = _binary_classification_profile_with_authoring_override()
        roles = dict(BINARY_CLASSIFICATION_ROLES)
        del roles["model_artifact"]
        roles["no_model_analysis_summary"] = b"forbidden-role-payload"
        manifest = _manifest_for(profile, roles=roles)

        result = validate_authoring_contracts(manifest, profile)

        assert result.valid is False
        assert any(
            failure.code == "forbidden_role_present" and failure.role == "no_model_analysis_summary"
            for failure in result.failures
        )

    def test_role_applicability_resolution_contains_no_dataset_or_telco_condition(self):
        source = inspect.getsource(authoring_contracts.validate_authoring_contracts)
        assert "telco" not in source.lower()
        assert "dataset_slug ==" not in source
        assert 'dataset_slug == "' not in source
