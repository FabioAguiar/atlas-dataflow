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


SEMANTIC_INTENT_V2_SCHEMA_PATH = REPO_ROOT / "pipeline" / "dataset-semantic-intent.v2.schema.json"

MULTICLASS_CLASSIFICATION_ROLES = {
    "discovery_evidence": DISCOVERY_EVIDENCE_BYTES,
    "semantic_intent": SEMANTIC_INTENT_BYTES,
    "preparation_recipe": PREPARATION_RECIPE_BYTES,
    "model_artifact": MODEL_ARTIFACT_BYTES,
}

DEFAULT_MULTICLASS_CLASSES = [
    {"class_id": "class-a", "display_label": "Class A"},
    {"class_id": "class-b", "display_label": "Class B"},
    {"class_id": "class-c", "display_label": "Class C"},
]


def _multiclass_classification_profile() -> dict:
    """Project Spec S0206: an additive, non-operational multiclass capability
    profile, in-memory mirror of pipeline/capabilities/multiclass-predictive-
    classification.v1.json, used the same way _binary_classification_profile
    is used above -- as a synthetic, dataset-neutral fixture, not the real
    committed file."""
    return {
        "schema_version": "capability-profile.v1",
        "artifact_type": "capability_profile",
        "capability_profile_id": "multiclass-predictive-classification",
        "capability_profile_version": "v1",
        "support_status": "requires_future_contract_evolution",
        "semantic_requirements": {
            "target_semantics_applicability": "required",
        },
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
        "generated_at": "2026-08-16T00:00:00+00:00",
    }


def _multiclass_semantic_intent_for(
    profile: dict,
    *,
    classes: list[dict] | None = None,
    include_positive_class: bool = False,
    omit_classes: bool = False,
) -> dict:
    document = {
        "schema_version": "dataset-semantic-intent.v2",
        "artifact_type": "dataset_semantic_intent",
        "dataset_identity": {"dataset_slug": DATASET_SLUG},
        "authoring_generation_id": "authoring-gen-0001",
        "governing_capability_profile": {
            "capability_profile_id": profile["capability_profile_id"],
            "capability_profile_version": profile["capability_profile_version"],
        },
        "field_role_decisions": [
            {"field_name": "record_id", "role": "identifier", "include_in_features": False},
            {"field_name": "numeric_feature", "role": "feature", "include_in_features": True},
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
    target_semantics = {
        "target_field_name": "category",
        "task_type": "multiclass_classification",
        "is_final_training_configuration": False,
    }
    if not omit_classes:
        target_semantics["classes"] = classes if classes is not None else list(DEFAULT_MULTICLASS_CLASSES)
    if include_positive_class:
        target_semantics["positive_class"] = {"class_id": "class-a"}
    document["target_semantics"] = target_semantics
    return document


class TestSemanticIntentSchemaVersionDispatch:
    """Project Spec S0206: authoring_contracts dispatches semantic-intent
    schema selection by the artifact's own declared schema_version against a
    closed local registry, never by dataset slug/name, filesystem path
    naming, feature names, or model family."""

    def test_v2_schema_is_valid_json_schema(self):
        schema = _load_schema(SEMANTIC_INTENT_V2_SCHEMA_PATH)
        jsonschema.Draft202012Validator.check_schema(schema)

    def test_v1_schema_dispatch_still_works(self):
        profile = _binary_classification_profile()
        manifest = _manifest_for(profile, roles=BINARY_CLASSIFICATION_ROLES)
        semantic_intent = _semantic_intent_for(profile, include_target=True)
        assert semantic_intent["schema_version"] == "dataset-semantic-intent.v1"

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.semantic_intent_schema_valid is True
        assert result.valid is True

    def test_v2_schema_dispatch_works(self):
        profile = _multiclass_classification_profile()
        manifest = _manifest_for(profile, roles=MULTICLASS_CLASSIFICATION_ROLES)
        semantic_intent = _multiclass_semantic_intent_for(profile)
        assert semantic_intent["schema_version"] == "dataset-semantic-intent.v2"

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.semantic_intent_schema_valid is True
        assert result.valid is True

    def test_unknown_semantic_intent_schema_version_fails_closed(self):
        profile = _multiclass_classification_profile()
        manifest = _manifest_for(profile, roles=MULTICLASS_CLASSIFICATION_ROLES)
        semantic_intent = _multiclass_semantic_intent_for(profile)
        semantic_intent["schema_version"] = "dataset-semantic-intent.v99"

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.semantic_intent_schema_valid is False
        assert result.valid is False
        assert any(failure.code == "unknown_semantic_intent_schema_version" for failure in result.failures)

    def test_missing_semantic_intent_schema_version_fails_closed(self):
        profile = _multiclass_classification_profile()
        manifest = _manifest_for(profile, roles=MULTICLASS_CLASSIFICATION_ROLES)
        semantic_intent = _multiclass_semantic_intent_for(profile)
        del semantic_intent["schema_version"]

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.semantic_intent_schema_valid is False
        assert result.valid is False
        assert any(failure.code == "unknown_semantic_intent_schema_version" for failure in result.failures)


class TestValidGenericMulticlassAuthoringContract:
    def test_valid_multiclass_manifest_profile_and_semantic_intent_pass(self):
        profile = _multiclass_classification_profile()
        manifest = _manifest_for(profile, roles=MULTICLASS_CLASSIFICATION_ROLES)
        semantic_intent = _multiclass_semantic_intent_for(profile)

        result = validate_authoring_contracts(
            manifest, profile, semantic_intent=semantic_intent, expected_dataset_slug=DATASET_SLUG
        )

        assert result.manifest_schema_valid is True
        assert result.semantic_intent_schema_valid is True
        assert result.capability_profile_schema_valid is True
        assert result.valid is True
        assert result.failures == ()
        assert result.capability_profile_id == "multiclass-predictive-classification"
        assert result.capability_profile_version == "v1"

    def test_class_order_is_preserved_as_authored(self):
        profile = _multiclass_classification_profile()
        manifest = _manifest_for(profile, roles=MULTICLASS_CLASSIFICATION_ROLES)
        non_alphabetical_classes = [
            {"class_id": "class-c", "display_label": "Class C"},
            {"class_id": "class-a", "display_label": "Class A"},
            {"class_id": "class-b", "display_label": "Class B"},
        ]
        semantic_intent = _multiclass_semantic_intent_for(profile, classes=non_alphabetical_classes)

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.valid is True, result.failures
        assert semantic_intent["target_semantics"]["classes"] == non_alphabetical_classes


class TestMulticlassTargetSemanticsPositiveClassRejection:
    def test_positive_class_on_multiclass_target_semantics_is_rejected(self):
        profile = _multiclass_classification_profile()
        manifest = _manifest_for(profile, roles=MULTICLASS_CLASSIFICATION_ROLES)
        semantic_intent = _multiclass_semantic_intent_for(profile, include_positive_class=True)

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.semantic_intent_schema_valid is False
        assert result.valid is False


class TestMulticlassClassCountAndUniqueness:
    def test_fewer_than_three_classes_is_rejected(self):
        profile = _multiclass_classification_profile()
        manifest = _manifest_for(profile, roles=MULTICLASS_CLASSIFICATION_ROLES)
        semantic_intent = _multiclass_semantic_intent_for(
            profile,
            classes=[
                {"class_id": "class-a", "display_label": "Class A"},
                {"class_id": "class-b", "display_label": "Class B"},
            ],
        )

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.semantic_intent_schema_valid is False
        assert result.valid is False

    def test_duplicate_class_id_is_rejected(self):
        profile = _multiclass_classification_profile()
        manifest = _manifest_for(profile, roles=MULTICLASS_CLASSIFICATION_ROLES)
        semantic_intent = _multiclass_semantic_intent_for(
            profile,
            classes=[
                {"class_id": "class-a", "display_label": "Class A"},
                {"class_id": "class-a", "display_label": "Also labeled class A"},
                {"class_id": "class-c", "display_label": "Class C"},
            ],
        )

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.semantic_intent_schema_valid is True
        assert result.valid is False
        assert any(failure.code == "duplicate_class_id" for failure in result.failures)


class TestTaskRuntimeModeConsistency:
    """Project Spec S0206: semantic task type and capability prediction
    runtime mode must agree; a targetless capability's behavior is
    unaffected (checked only when target_semantics is present)."""

    def test_binary_task_with_multiclass_runtime_mode_is_rejected(self):
        profile = _multiclass_classification_profile()
        manifest = _manifest_for(profile, roles=MULTICLASS_CLASSIFICATION_ROLES)
        semantic_intent = _semantic_intent_for(profile, include_target=True)
        assert semantic_intent["target_semantics"]["task_type"] == "binary_classification"

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.semantic_intent_schema_valid is True
        assert result.valid is False
        assert any(failure.code == "task_runtime_mode_mismatch" for failure in result.failures)

    def test_multiclass_task_with_binary_runtime_mode_is_rejected(self):
        profile = _binary_classification_profile()
        manifest = _manifest_for(profile, roles=BINARY_CLASSIFICATION_ROLES)
        semantic_intent = _multiclass_semantic_intent_for(profile)
        assert semantic_intent["target_semantics"]["task_type"] == "multiclass_classification"

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.semantic_intent_schema_valid is True
        assert result.valid is False
        assert any(failure.code == "task_runtime_mode_mismatch" for failure in result.failures)

    def test_binary_task_with_binary_runtime_mode_agrees(self):
        profile = _binary_classification_profile()
        manifest = _manifest_for(profile, roles=BINARY_CLASSIFICATION_ROLES)
        semantic_intent = _semantic_intent_for(profile, include_target=True)

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert not any(failure.code == "task_runtime_mode_mismatch" for failure in result.failures)

    def test_multiclass_task_with_multiclass_runtime_mode_agrees(self):
        profile = _multiclass_classification_profile()
        manifest = _manifest_for(profile, roles=MULTICLASS_CLASSIFICATION_ROLES)
        semantic_intent = _multiclass_semantic_intent_for(profile)

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert not any(failure.code == "task_runtime_mode_mismatch" for failure in result.failures)

    def test_targetless_capability_behavior_is_unaffected(self):
        profile = _no_model_analysis_profile()
        manifest = _manifest_for(
            profile,
            roles={"discovery_evidence": DISCOVERY_EVIDENCE_BYTES, "semantic_intent": SEMANTIC_INTENT_BYTES},
        )
        semantic_intent = _semantic_intent_for(profile, include_target=False)
        assert "target_semantics" not in semantic_intent

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.valid is True
        assert not any(failure.code == "task_runtime_mode_mismatch" for failure in result.failures)


class TestNoDatasetOrTelcoOrDryBeanConditionInMulticlassPath:
    def test_validate_authoring_contracts_contains_no_dataset_conditional(self):
        source = inspect.getsource(authoring_contracts.validate_authoring_contracts)
        for forbidden in ("telco", "dry bean", "dry_bean", "drybean"):
            assert forbidden not in source.lower()

    def test_resolve_semantic_intent_schema_contains_no_dataset_conditional(self):
        source = inspect.getsource(authoring_contracts._resolve_semantic_intent_schema)
        for forbidden in ("telco", "dry bean", "dry_bean", "drybean", "dataset_slug"):
            assert forbidden not in source.lower()


SEMANTIC_INTENT_V3_SCHEMA_PATH = REPO_ROOT / "pipeline" / "dataset-semantic-intent.v3.schema.json"

CONTINUOUS_REGRESSION_ROLES = {
    "discovery_evidence": DISCOVERY_EVIDENCE_BYTES,
    "semantic_intent": SEMANTIC_INTENT_BYTES,
    "preparation_recipe": PREPARATION_RECIPE_BYTES,
    "model_artifact": MODEL_ARTIFACT_BYTES,
}


def _continuous_regression_profile() -> dict:
    """Project Spec S0222: an additive, non-operational continuous-regression
    capability profile, in-memory mirror of pipeline/capabilities/continuous-
    predictive-regression.v1.json, used the same way
    _multiclass_classification_profile is used above -- as a synthetic,
    dataset-neutral fixture, not the real committed file."""
    return {
        "schema_version": "capability-profile.v1",
        "artifact_type": "capability_profile",
        "capability_profile_id": "continuous-predictive-regression",
        "capability_profile_version": "v1",
        "support_status": "requires_future_contract_evolution",
        "semantic_requirements": {
            "target_semantics_applicability": "required",
        },
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
            "mode": "single_model_continuous_regression",
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
        "generated_at": "2026-08-19T00:00:00+00:00",
    }


def _continuous_regression_semantic_intent_for(
    profile: dict,
    *,
    target_field_name: str = "measured_outcome",
    extra_target_fields: dict | None = None,
) -> dict:
    document = {
        "schema_version": "dataset-semantic-intent.v3",
        "artifact_type": "dataset_semantic_intent",
        "dataset_identity": {"dataset_slug": DATASET_SLUG},
        "authoring_generation_id": "authoring-gen-0001",
        "governing_capability_profile": {
            "capability_profile_id": profile["capability_profile_id"],
            "capability_profile_version": profile["capability_profile_version"],
        },
        "field_role_decisions": [
            {"field_name": "record_id", "role": "identifier", "include_in_features": False},
            {"field_name": "numeric_feature", "role": "feature", "include_in_features": True},
        ],
        "semantic_boundary_confirmations": {
            "observed_source_statistics_embedded": False,
            "scientific_conclusions_embedded": False,
            "training_outcome_embedded": False,
            "release_state_embedded": False,
            "model_bytes_embedded": False,
        },
        "generated_at": "2026-08-19T00:00:00+00:00",
    }
    target_semantics = {
        "target_field_name": target_field_name,
        "task_type": "continuous_regression",
        "target_value_kind": "continuous_numeric",
        "is_final_training_configuration": False,
    }
    if extra_target_fields:
        target_semantics.update(extra_target_fields)
    document["target_semantics"] = target_semantics
    return document


class TestSemanticIntentV3SchemaDispatch:
    """Project Spec S0222: authoring_contracts dispatches dataset-semantic-
    intent.v3 through the same closed local registry used for v1/v2, by the
    artifact's own declared schema_version only."""

    def test_v3_schema_is_valid_json_schema(self):
        schema = _load_schema(SEMANTIC_INTENT_V3_SCHEMA_PATH)
        jsonschema.Draft202012Validator.check_schema(schema)

    def test_v3_schema_dispatch_works(self):
        profile = _continuous_regression_profile()
        manifest = _manifest_for(profile, roles=CONTINUOUS_REGRESSION_ROLES)
        semantic_intent = _continuous_regression_semantic_intent_for(profile)
        assert semantic_intent["schema_version"] == "dataset-semantic-intent.v3"

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.semantic_intent_schema_valid is True
        assert result.valid is True, result.failures


class TestValidGenericContinuousRegressionAuthoringContract:
    def test_valid_continuous_regression_manifest_profile_and_semantic_intent_pass(self):
        profile = _continuous_regression_profile()
        manifest = _manifest_for(profile, roles=CONTINUOUS_REGRESSION_ROLES)
        semantic_intent = _continuous_regression_semantic_intent_for(profile)

        result = validate_authoring_contracts(
            manifest, profile, semantic_intent=semantic_intent, expected_dataset_slug=DATASET_SLUG
        )

        assert result.manifest_schema_valid is True
        assert result.semantic_intent_schema_valid is True
        assert result.capability_profile_schema_valid is True
        assert result.valid is True, result.failures
        assert result.failures == ()
        assert result.capability_profile_id == "continuous-predictive-regression"
        assert result.capability_profile_version == "v1"

    def test_task_type_is_exactly_continuous_regression(self):
        profile = _continuous_regression_profile()
        semantic_intent = _continuous_regression_semantic_intent_for(profile)
        assert semantic_intent["target_semantics"]["task_type"] == "continuous_regression"

    def test_target_value_kind_is_exactly_continuous_numeric(self):
        profile = _continuous_regression_profile()
        semantic_intent = _continuous_regression_semantic_intent_for(profile)
        assert semantic_intent["target_semantics"]["target_value_kind"] == "continuous_numeric"

    def test_target_field_name_identifies_exactly_one_target_field(self):
        profile = _continuous_regression_profile()
        semantic_intent = _continuous_regression_semantic_intent_for(profile)
        assert isinstance(semantic_intent["target_semantics"]["target_field_name"], str)
        assert semantic_intent["target_semantics"]["target_field_name"] == "measured_outcome"


class TestContinuousRegressionV3RejectsClassificationOwnedFields:
    def test_positive_class_is_rejected_by_v3(self):
        profile = _continuous_regression_profile()
        manifest = _manifest_for(profile, roles=CONTINUOUS_REGRESSION_ROLES)
        semantic_intent = _continuous_regression_semantic_intent_for(
            profile, extra_target_fields={"positive_class": {"class_id": "yes"}}
        )

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.semantic_intent_schema_valid is False
        assert result.valid is False

    def test_classes_is_rejected_by_v3(self):
        profile = _continuous_regression_profile()
        manifest = _manifest_for(profile, roles=CONTINUOUS_REGRESSION_ROLES)
        semantic_intent = _continuous_regression_semantic_intent_for(
            profile,
            extra_target_fields={
                "classes": [
                    {"class_id": "class-a", "display_label": "Class A"},
                    {"class_id": "class-b", "display_label": "Class B"},
                ]
            },
        )

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.semantic_intent_schema_valid is False
        assert result.valid is False

    def test_threshold_probability_and_risk_band_fields_are_rejected_by_v3(self):
        profile = _continuous_regression_profile()
        manifest = _manifest_for(profile, roles=CONTINUOUS_REGRESSION_ROLES)
        for forbidden_field, forbidden_value in (
            ("threshold", 0.5),
            ("probability_output", True),
            ("risk_bands", ["low", "high"]),
            ("negative_class", {"class_id": "no"}),
            ("class_order", ["a", "b"]),
        ):
            semantic_intent = _continuous_regression_semantic_intent_for(
                profile, extra_target_fields={forbidden_field: forbidden_value}
            )

            result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

            assert result.semantic_intent_schema_valid is False, forbidden_field
            assert result.valid is False, forbidden_field

    def test_count_and_multi_output_placeholders_are_rejected_by_v3(self):
        profile = _continuous_regression_profile()
        manifest = _manifest_for(profile, roles=CONTINUOUS_REGRESSION_ROLES)
        for forbidden_field, forbidden_value in (
            ("count_semantics", {"kind": "poisson"}),
            ("exposure", "days"),
            ("offset", "log_exposure"),
            ("output_targets", ["a", "b"]),
            ("target_fields", ["a", "b"]),
        ):
            semantic_intent = _continuous_regression_semantic_intent_for(
                profile, extra_target_fields={forbidden_field: forbidden_value}
            )

            result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

            assert result.semantic_intent_schema_valid is False, forbidden_field
            assert result.valid is False, forbidden_field


class TestContinuousRegressionTaskRuntimeModeConsistency:
    """Project Spec S0222: continuous_regression must agree only with
    single_model_continuous_regression; every classification/regression
    cross-combination must be rejected."""

    def test_continuous_regression_task_with_continuous_regression_runtime_mode_agrees(self):
        profile = _continuous_regression_profile()
        manifest = _manifest_for(profile, roles=CONTINUOUS_REGRESSION_ROLES)
        semantic_intent = _continuous_regression_semantic_intent_for(profile)

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert not any(failure.code == "task_runtime_mode_mismatch" for failure in result.failures)
        assert result.valid is True, result.failures

    def test_continuous_regression_task_with_binary_runtime_mode_is_rejected(self):
        profile = _binary_classification_profile()
        manifest = _manifest_for(profile, roles=BINARY_CLASSIFICATION_ROLES)
        semantic_intent = _continuous_regression_semantic_intent_for(profile)

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.semantic_intent_schema_valid is True
        assert result.valid is False
        assert any(failure.code == "task_runtime_mode_mismatch" for failure in result.failures)

    def test_continuous_regression_task_with_multiclass_runtime_mode_is_rejected(self):
        profile = _multiclass_classification_profile()
        manifest = _manifest_for(profile, roles=MULTICLASS_CLASSIFICATION_ROLES)
        semantic_intent = _continuous_regression_semantic_intent_for(profile)

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.semantic_intent_schema_valid is True
        assert result.valid is False
        assert any(failure.code == "task_runtime_mode_mismatch" for failure in result.failures)

    def test_binary_task_with_continuous_regression_runtime_mode_is_rejected(self):
        profile = _continuous_regression_profile()
        manifest = _manifest_for(profile, roles=CONTINUOUS_REGRESSION_ROLES)
        semantic_intent = _semantic_intent_for(profile, include_target=True)
        assert semantic_intent["target_semantics"]["task_type"] == "binary_classification"

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.semantic_intent_schema_valid is True
        assert result.valid is False
        assert any(failure.code == "task_runtime_mode_mismatch" for failure in result.failures)

    def test_multiclass_task_with_continuous_regression_runtime_mode_is_rejected(self):
        profile = _continuous_regression_profile()
        manifest = _manifest_for(profile, roles=CONTINUOUS_REGRESSION_ROLES)
        semantic_intent = _multiclass_semantic_intent_for(profile)
        assert semantic_intent["target_semantics"]["task_type"] == "multiclass_classification"

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.semantic_intent_schema_valid is True
        assert result.valid is False
        assert any(failure.code == "task_runtime_mode_mismatch" for failure in result.failures)


class TestNoDatasetOrConcreteConditionInContinuousRegressionPath:
    def test_validate_authoring_contracts_contains_no_concrete_dataset_conditional(self):
        source = inspect.getsource(authoring_contracts.validate_authoring_contracts)
        for forbidden in ("concrete compressive", "cement", "blast furnace slag", "fly ash", "superplasticizer"):
            assert forbidden not in source.lower()

    def test_resolve_semantic_intent_schema_contains_no_concrete_dataset_conditional(self):
        source = inspect.getsource(authoring_contracts._resolve_semantic_intent_schema)
        for forbidden in ("concrete compressive", "cement", "blast furnace slag", "fly ash", "superplasticizer"):
            assert forbidden not in source.lower()


# ---------------------------------------------------------------------------
# Project Spec S0241: Univariate Forecasting Capability and Temporal
# Semantic Intent Contract.
# ---------------------------------------------------------------------------

SEMANTIC_INTENT_V4_SCHEMA_PATH = REPO_ROOT / "pipeline" / "dataset-semantic-intent.v4.schema.json"

UNIVARIATE_FORECASTING_ROLES = {
    "discovery_evidence": DISCOVERY_EVIDENCE_BYTES,
    "semantic_intent": SEMANTIC_INTENT_BYTES,
    "preparation_recipe": PREPARATION_RECIPE_BYTES,
    "model_artifact": MODEL_ARTIFACT_BYTES,
}


def _univariate_forecasting_profile() -> dict:
    """Project Spec S0241: an additive, non-operational univariate-
    forecasting capability profile, in-memory mirror of pipeline/
    capabilities/univariate-predictive-forecasting.v1.json -- a synthetic,
    dataset-neutral fixture, not the real committed file."""
    return {
        "schema_version": "capability-profile.v1",
        "artifact_type": "capability_profile",
        "capability_profile_id": "univariate-predictive-forecasting",
        "capability_profile_version": "v1",
        "support_status": "requires_future_contract_evolution",
        "semantic_requirements": {
            "target_semantics_applicability": "required",
            "split_semantics_applicability": "required",
        },
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
            "mode": "single_model_univariate_forecasting",
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
        "generated_at": "2026-08-22T00:00:00+00:00",
    }


def _univariate_forecasting_semantic_intent_for(
    profile: dict,
    *,
    time_index_field_name: str = "period_index",
    target_field_name: str = "series_value",
    temporal_index_role: str = "temporal_index",
    target_role: str = "target",
    extra_field_role_decisions: list[dict] | None = None,
    extra_temporal_fields: dict | None = None,
    extra_target_fields: dict | None = None,
) -> dict:
    field_role_decisions = [
        {"field_name": time_index_field_name, "role": temporal_index_role, "include_in_features": False},
        {"field_name": target_field_name, "role": target_role, "include_in_features": False},
    ]
    if extra_field_role_decisions:
        field_role_decisions.extend(extra_field_role_decisions)
    document = {
        "schema_version": "dataset-semantic-intent.v4",
        "artifact_type": "dataset_semantic_intent",
        "dataset_identity": {"dataset_slug": DATASET_SLUG},
        "authoring_generation_id": "authoring-gen-0001",
        "governing_capability_profile": {
            "capability_profile_id": profile["capability_profile_id"],
            "capability_profile_version": profile["capability_profile_version"],
        },
        "field_role_decisions": field_role_decisions,
        "semantic_boundary_confirmations": {
            "observed_source_statistics_embedded": False,
            "scientific_conclusions_embedded": False,
            "training_outcome_embedded": False,
            "release_state_embedded": False,
            "model_bytes_embedded": False,
        },
        "generated_at": "2026-08-22T00:00:00+00:00",
    }
    temporal_semantics = {
        "time_index_field_name": time_index_field_name,
        "index_value_kind": "calendar_period",
        "frequency": "monthly",
        "source_exogenous_predictors": "forbidden",
    }
    if extra_temporal_fields:
        temporal_semantics.update(extra_temporal_fields)
    document["temporal_semantics"] = temporal_semantics
    target_semantics = {
        "target_field_name": target_field_name,
        "task_type": "univariate_forecasting",
        "target_value_kind": "numeric",
        "forecasting_mode": "univariate",
        "is_final_training_configuration": False,
    }
    if extra_target_fields:
        target_semantics.update(extra_target_fields)
    document["target_semantics"] = target_semantics
    return document


class TestSemanticIntentV4SchemaDispatch:
    """Project Spec S0241: authoring_contracts dispatches dataset-semantic-
    intent.v4 through the same closed local registry used for v1/v2/v3, by
    the artifact's own declared schema_version only."""

    def test_v4_schema_is_valid_json_schema(self):
        schema = _load_schema(SEMANTIC_INTENT_V4_SCHEMA_PATH)
        jsonschema.Draft202012Validator.check_schema(schema)

    def test_v4_schema_dispatch_works(self):
        profile = _univariate_forecasting_profile()
        manifest = _manifest_for(profile, roles=UNIVARIATE_FORECASTING_ROLES)
        semantic_intent = _univariate_forecasting_semantic_intent_for(profile)
        assert semantic_intent["schema_version"] == "dataset-semantic-intent.v4"

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.semantic_intent_schema_valid is True
        assert result.valid is True, result.failures

    def test_unknown_v5_schema_version_is_rejected(self):
        profile = _univariate_forecasting_profile()
        manifest = _manifest_for(profile, roles=UNIVARIATE_FORECASTING_ROLES)
        semantic_intent = _univariate_forecasting_semantic_intent_for(profile)
        semantic_intent["schema_version"] = "dataset-semantic-intent.v5"

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.semantic_intent_schema_valid is False
        assert result.valid is False
        assert any(failure.code == "unknown_semantic_intent_schema_version" for failure in result.failures)


class TestValidGenericUnivariateForecastingAuthoringContract:
    def test_valid_univariate_forecasting_manifest_profile_and_semantic_intent_pass(self):
        profile = _univariate_forecasting_profile()
        manifest = _manifest_for(profile, roles=UNIVARIATE_FORECASTING_ROLES)
        semantic_intent = _univariate_forecasting_semantic_intent_for(profile)

        result = validate_authoring_contracts(
            manifest, profile, semantic_intent=semantic_intent, expected_dataset_slug=DATASET_SLUG
        )

        assert result.manifest_schema_valid is True
        assert result.semantic_intent_schema_valid is True
        assert result.capability_profile_schema_valid is True
        assert result.valid is True, result.failures
        assert result.failures == ()
        assert result.capability_profile_id == "univariate-predictive-forecasting"
        assert result.capability_profile_version == "v1"

    def test_task_type_is_exactly_univariate_forecasting(self):
        profile = _univariate_forecasting_profile()
        semantic_intent = _univariate_forecasting_semantic_intent_for(profile)
        assert semantic_intent["target_semantics"]["task_type"] == "univariate_forecasting"

    def test_target_value_kind_is_exactly_numeric(self):
        profile = _univariate_forecasting_profile()
        semantic_intent = _univariate_forecasting_semantic_intent_for(profile)
        assert semantic_intent["target_semantics"]["target_value_kind"] == "numeric"

    def test_forecasting_mode_is_exactly_univariate(self):
        profile = _univariate_forecasting_profile()
        semantic_intent = _univariate_forecasting_semantic_intent_for(profile)
        assert semantic_intent["target_semantics"]["forecasting_mode"] == "univariate"

    def test_target_field_name_identifies_exactly_one_target_field(self):
        profile = _univariate_forecasting_profile()
        semantic_intent = _univariate_forecasting_semantic_intent_for(profile)
        assert isinstance(semantic_intent["target_semantics"]["target_field_name"], str)
        assert semantic_intent["target_semantics"]["target_field_name"] == "series_value"

    def test_temporal_semantics_present_with_governed_fields(self):
        profile = _univariate_forecasting_profile()
        semantic_intent = _univariate_forecasting_semantic_intent_for(profile)
        temporal_semantics = semantic_intent["temporal_semantics"]
        assert temporal_semantics["time_index_field_name"] == "period_index"
        assert temporal_semantics["index_value_kind"] == "calendar_period"
        assert temporal_semantics["frequency"] == "monthly"
        assert temporal_semantics["source_exogenous_predictors"] == "forbidden"


class TestForecastingV4RejectsClassificationAndRegressionOwnedFields:
    def test_classification_and_regression_owned_target_fields_are_rejected(self):
        profile = _univariate_forecasting_profile()
        manifest = _manifest_for(profile, roles=UNIVARIATE_FORECASTING_ROLES)
        for forbidden_field, forbidden_value in (
            ("positive_class", {"class_id": "yes"}),
            ("negative_class", {"class_id": "no"}),
            ("classes", [{"class_id": "a", "display_label": "A"}]),
            ("class_order", ["a", "b"]),
            ("threshold", 0.5),
            ("probability_output", True),
            ("risk_bands", ["low", "high"]),
            ("continuous_numeric_target_value_kind", True),
            ("count_semantics", {"kind": "poisson"}),
            ("exposure", "days"),
            ("offset", "log_exposure"),
            ("output_targets", ["a", "b"]),
            ("target_fields", ["a", "b"]),
            ("forecast_horizon", 12),
            ("model_family", "arima"),
            ("training_metrics", {"mae": 1.0}),
        ):
            semantic_intent = _univariate_forecasting_semantic_intent_for(
                profile, extra_target_fields={forbidden_field: forbidden_value}
            )

            result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

            assert result.semantic_intent_schema_valid is False, forbidden_field
            assert result.valid is False, forbidden_field


class TestForecastingV4TemporalSemanticsRejectsLaterContractFields:
    def test_temporal_semantics_forbids_split_and_horizon_owned_fields(self):
        profile = _univariate_forecasting_profile()
        manifest = _manifest_for(profile, roles=UNIVARIATE_FORECASTING_ROLES)
        for forbidden_field, forbidden_value in (
            ("forecast_horizon", 12),
            ("seasonal_period", 12),
            ("backtesting_folds", 5),
            ("holdout_boundaries", {"start": "2020-01", "end": "2020-12"}),
            ("training_window_lengths", [24, 36]),
            ("model_coefficients", [0.1, 0.2]),
            ("runtime_history_length", 24),
            ("future_result_rows", 12),
        ):
            semantic_intent = _univariate_forecasting_semantic_intent_for(
                profile, extra_temporal_fields={forbidden_field: forbidden_value}
            )

            result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

            assert result.semantic_intent_schema_valid is False, forbidden_field
            assert result.valid is False, forbidden_field

    def test_source_exogenous_predictors_must_be_exactly_forbidden(self):
        profile = _univariate_forecasting_profile()
        manifest = _manifest_for(profile, roles=UNIVARIATE_FORECASTING_ROLES)
        semantic_intent = _univariate_forecasting_semantic_intent_for(
            profile, extra_temporal_fields={"source_exogenous_predictors": "optional"}
        )

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.semantic_intent_schema_valid is False
        assert result.valid is False

    def test_frequency_must_be_non_empty(self):
        profile = _univariate_forecasting_profile()
        manifest = _manifest_for(profile, roles=UNIVARIATE_FORECASTING_ROLES)
        semantic_intent = _univariate_forecasting_semantic_intent_for(
            profile, extra_temporal_fields={"frequency": ""}
        )

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.semantic_intent_schema_valid is False
        assert result.valid is False

    def test_frequency_is_not_restricted_to_a_single_dataset_cadence(self):
        profile = _univariate_forecasting_profile()
        manifest = _manifest_for(profile, roles=UNIVARIATE_FORECASTING_ROLES)
        for frequency in ("monthly", "daily", "quarterly", "irregular_business_days", "custom-5min"):
            semantic_intent = _univariate_forecasting_semantic_intent_for(
                profile, extra_temporal_fields={"frequency": frequency}
            )

            result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

            assert result.semantic_intent_schema_valid is True, frequency
            assert result.valid is True, (frequency, result.failures)

    def test_index_value_kind_accepts_only_governed_values(self):
        profile = _univariate_forecasting_profile()
        manifest = _manifest_for(profile, roles=UNIVARIATE_FORECASTING_ROLES)
        semantic_intent = _univariate_forecasting_semantic_intent_for(
            profile, extra_temporal_fields={"index_value_kind": "row_number"}
        )

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.semantic_intent_schema_valid is False
        assert result.valid is False


class TestForecastingFieldRoleVocabularyIncludeInFeatures:
    def test_temporal_index_include_in_features_true_is_rejected(self):
        schema = _load_schema(SEMANTIC_INTENT_V4_SCHEMA_PATH)
        profile = _univariate_forecasting_profile()
        semantic_intent = _univariate_forecasting_semantic_intent_for(profile)
        semantic_intent["field_role_decisions"][0]["include_in_features"] = True

        validator = jsonschema.Draft202012Validator(schema)
        errors = list(validator.iter_errors(semantic_intent))
        assert errors != []

    def test_target_include_in_features_true_is_rejected(self):
        schema = _load_schema(SEMANTIC_INTENT_V4_SCHEMA_PATH)
        profile = _univariate_forecasting_profile()
        semantic_intent = _univariate_forecasting_semantic_intent_for(profile)
        semantic_intent["field_role_decisions"][1]["include_in_features"] = True

        validator = jsonschema.Draft202012Validator(schema)
        errors = list(validator.iter_errors(semantic_intent))
        assert errors != []

    def test_identifier_include_in_features_true_is_rejected(self):
        schema = _load_schema(SEMANTIC_INTENT_V4_SCHEMA_PATH)
        profile = _univariate_forecasting_profile()
        semantic_intent = _univariate_forecasting_semantic_intent_for(
            profile,
            extra_field_role_decisions=[
                {"field_name": "series_id", "role": "identifier", "include_in_features": True}
            ],
        )

        validator = jsonschema.Draft202012Validator(schema)
        errors = list(validator.iter_errors(semantic_intent))
        assert errors != []

    def test_ignored_include_in_features_true_is_rejected(self):
        schema = _load_schema(SEMANTIC_INTENT_V4_SCHEMA_PATH)
        profile = _univariate_forecasting_profile()
        semantic_intent = _univariate_forecasting_semantic_intent_for(
            profile,
            extra_field_role_decisions=[
                {"field_name": "source_notes", "role": "ignored", "include_in_features": True}
            ],
        )

        validator = jsonschema.Draft202012Validator(schema)
        errors = list(validator.iter_errors(semantic_intent))
        assert errors != []

    def test_v1_v2_v3_role_vocabularies_do_not_accept_temporal_index(self):
        for schema_path in (
            SEMANTIC_INTENT_SCHEMA_PATH,
            REPO_ROOT / "pipeline" / "dataset-semantic-intent.v2.schema.json",
            REPO_ROOT / "pipeline" / "dataset-semantic-intent.v3.schema.json",
        ):
            schema = _load_schema(schema_path)
            field_role_decisions_schema = schema["properties"]["field_role_decisions"]["items"]
            validator = jsonschema.Draft202012Validator(field_role_decisions_schema)
            errors = list(
                validator.iter_errors(
                    {"field_name": "period_index", "role": "temporal_index", "include_in_features": False}
                )
            )
            assert errors != [], schema_path


class TestForecastingTemporalTargetFieldIdentityConsistency:
    """Project Spec S0241: authoring validation proves authored-meaning-only
    cross-field agreement between temporal_semantics/target_semantics and
    field_role_decisions -- never inspects source data, timestamp gaps,
    frequency conformance, or a derived split."""

    def test_temporal_index_field_name_role_agreement_required(self):
        profile = _univariate_forecasting_profile()
        manifest = _manifest_for(profile, roles=UNIVARIATE_FORECASTING_ROLES)
        semantic_intent = _univariate_forecasting_semantic_intent_for(profile, temporal_index_role="feature")

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.semantic_intent_schema_valid is True
        assert result.valid is False
        assert any(failure.code == "temporal_index_field_role_mismatch" for failure in result.failures)

    def test_target_field_name_role_agreement_required(self):
        profile = _univariate_forecasting_profile()
        manifest = _manifest_for(profile, roles=UNIVARIATE_FORECASTING_ROLES)
        semantic_intent = _univariate_forecasting_semantic_intent_for(profile, target_role="ignored")

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.semantic_intent_schema_valid is True
        assert result.valid is False
        assert any(failure.code == "forecasting_target_field_role_mismatch" for failure in result.failures)

    def test_temporal_index_and_target_must_differ(self):
        profile = _univariate_forecasting_profile()
        manifest = _manifest_for(profile, roles=UNIVARIATE_FORECASTING_ROLES)
        semantic_intent = _univariate_forecasting_semantic_intent_for(
            profile, time_index_field_name="same_field", target_field_name="same_field"
        )
        semantic_intent["field_role_decisions"] = [
            {"field_name": "same_field", "role": "target", "include_in_features": False}
        ]

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.valid is False
        assert any(failure.code == "temporal_index_equals_target_field" for failure in result.failures)

    def test_source_predictive_feature_is_rejected(self):
        profile = _univariate_forecasting_profile()
        manifest = _manifest_for(profile, roles=UNIVARIATE_FORECASTING_ROLES)
        semantic_intent = _univariate_forecasting_semantic_intent_for(
            profile,
            extra_field_role_decisions=[
                {"field_name": "external_regressor", "role": "feature", "include_in_features": True}
            ],
        )

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.semantic_intent_schema_valid is True
        assert result.valid is False
        assert any(failure.code == "forecasting_source_feature_forbidden" for failure in result.failures)

    def test_non_feature_ignored_or_identifier_fields_remain_permitted(self):
        profile = _univariate_forecasting_profile()
        manifest = _manifest_for(profile, roles=UNIVARIATE_FORECASTING_ROLES)
        semantic_intent = _univariate_forecasting_semantic_intent_for(
            profile,
            extra_field_role_decisions=[
                {"field_name": "series_id", "role": "identifier", "include_in_features": False},
                {"field_name": "source_notes", "role": "ignored", "include_in_features": False},
            ],
        )

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.valid is True, result.failures


class TestForecastingTaskRuntimeModeConsistency:
    """Project Spec S0241: univariate_forecasting must agree only with
    single_model_univariate_forecasting; every classification/regression
    cross-combination must be rejected."""

    def test_forecasting_task_with_forecasting_runtime_mode_agrees(self):
        profile = _univariate_forecasting_profile()
        manifest = _manifest_for(profile, roles=UNIVARIATE_FORECASTING_ROLES)
        semantic_intent = _univariate_forecasting_semantic_intent_for(profile)

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert not any(failure.code == "task_runtime_mode_mismatch" for failure in result.failures)
        assert result.valid is True, result.failures

    def test_forecasting_task_with_binary_runtime_mode_is_rejected(self):
        profile = _binary_classification_profile()
        manifest = _manifest_for(profile, roles=BINARY_CLASSIFICATION_ROLES)
        semantic_intent = _univariate_forecasting_semantic_intent_for(profile)

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.semantic_intent_schema_valid is True
        assert result.valid is False
        assert any(failure.code == "task_runtime_mode_mismatch" for failure in result.failures)

    def test_forecasting_task_with_multiclass_runtime_mode_is_rejected(self):
        profile = _multiclass_classification_profile()
        manifest = _manifest_for(profile, roles=MULTICLASS_CLASSIFICATION_ROLES)
        semantic_intent = _univariate_forecasting_semantic_intent_for(profile)

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.semantic_intent_schema_valid is True
        assert result.valid is False
        assert any(failure.code == "task_runtime_mode_mismatch" for failure in result.failures)

    def test_forecasting_task_with_continuous_regression_runtime_mode_is_rejected(self):
        profile = _continuous_regression_profile()
        manifest = _manifest_for(profile, roles=CONTINUOUS_REGRESSION_ROLES)
        semantic_intent = _univariate_forecasting_semantic_intent_for(profile)

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.semantic_intent_schema_valid is True
        assert result.valid is False
        assert any(failure.code == "task_runtime_mode_mismatch" for failure in result.failures)

    def test_binary_task_with_forecasting_runtime_mode_is_rejected(self):
        profile = _univariate_forecasting_profile()
        manifest = _manifest_for(profile, roles=UNIVARIATE_FORECASTING_ROLES)
        semantic_intent = _semantic_intent_for(profile, include_target=True)
        assert semantic_intent["target_semantics"]["task_type"] == "binary_classification"

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.semantic_intent_schema_valid is True
        assert result.valid is False
        assert any(failure.code == "task_runtime_mode_mismatch" for failure in result.failures)

    def test_multiclass_task_with_forecasting_runtime_mode_is_rejected(self):
        profile = _univariate_forecasting_profile()
        manifest = _manifest_for(profile, roles=UNIVARIATE_FORECASTING_ROLES)
        semantic_intent = _multiclass_semantic_intent_for(profile)
        assert semantic_intent["target_semantics"]["task_type"] == "multiclass_classification"

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.semantic_intent_schema_valid is True
        assert result.valid is False
        assert any(failure.code == "task_runtime_mode_mismatch" for failure in result.failures)

    def test_continuous_regression_task_with_forecasting_runtime_mode_is_rejected(self):
        profile = _univariate_forecasting_profile()
        manifest = _manifest_for(profile, roles=UNIVARIATE_FORECASTING_ROLES)
        semantic_intent = _continuous_regression_semantic_intent_for(profile)

        result = validate_authoring_contracts(manifest, profile, semantic_intent=semantic_intent)

        assert result.semantic_intent_schema_valid is True
        assert result.valid is False
        assert any(failure.code == "task_runtime_mode_mismatch" for failure in result.failures)


class TestNoDatasetOrConditionInForecastingPath:
    def test_validate_authoring_contracts_contains_no_nottingham_specific_conditional(self):
        source = inspect.getsource(authoring_contracts.validate_authoring_contracts)
        for forbidden in ("nottingham", "nottem", "airline passenger"):
            assert forbidden not in source.lower()

    def test_resolve_semantic_intent_schema_contains_no_nottingham_specific_conditional(self):
        source = inspect.getsource(authoring_contracts._resolve_semantic_intent_schema)
        for forbidden in ("nottingham", "nottem", "airline passenger"):
            assert forbidden not in source.lower()
