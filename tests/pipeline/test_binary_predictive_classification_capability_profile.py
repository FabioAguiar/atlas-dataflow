"""
Project Spec S0183: Binary Predictive Classification Capability Profile
Concrete Instance Materialization Contract.

Proves the real, committed capability profile document at
pipeline/capabilities/binary-predictive-classification.v1.json is the
current, operationally supported binary predictive-classification
capability instance, and that it is consumable as such by the real
downstream consumers (pipeline.contract_derivation,
pipeline.assemble_candidate, pipeline.authoring_contracts).

Uses only the real repository profile file, the real capability-profile
schema, and synthetic inert fixture bytes under a temporary directory --
never a real model, never notebook execution, never a real release
candidate, publisher call, or registry mutation.
"""

import hashlib
import json
import sys
from pathlib import Path

import jsonschema

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pipeline.assemble_candidate import CURRENTLY_SUPPORTED_RELEASE_CAPABILITY_PROFILE_ID
from pipeline.authoring_contracts import validate_authoring_contracts
from pipeline.contract_derivation import CURRENTLY_SUPPORTED_CAPABILITY_PROFILE_ID

REPO_ROOT = Path(__file__).parent.parent.parent
PROFILE_PATH = REPO_ROOT / "pipeline" / "capabilities" / "binary-predictive-classification.v1.json"
CAPABILITY_PROFILE_SCHEMA_PATH = REPO_ROOT / "pipeline" / "capability-profile.schema.json"

DATASET_SLUG = "sample-binary-classification-dataset"

DISCOVERY_EVIDENCE_BYTES = b'{"schema_version": "dataset-discovery-evidence.v1"}'
SEMANTIC_INTENT_BYTES = b'{"schema_version": "dataset-semantic-intent.v1"}'
PREPARATION_RECIPE_BYTES = b'{"schema_version": "candidate-preparation-recipe.v1"}'
MODEL_ARTIFACT_BYTES = b"synthetic-inert-opaque-model-bytes-not-a-real-joblib-file"

REQUIRED_ROLES = {
    "discovery_evidence",
    "semantic_intent",
    "preparation_recipe",
    "model_artifact",
}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_profile_text() -> str:
    return PROFILE_PATH.read_text(encoding="utf-8")


def _load_profile() -> dict:
    return json.loads(_load_profile_text())


def _load_schema() -> dict:
    return json.loads(CAPABILITY_PROFILE_SCHEMA_PATH.read_text(encoding="utf-8"))


class TestProfileFileExistsAndParses:
    def test_profile_file_exists(self):
        assert PROFILE_PATH.is_file()

    def test_profile_is_valid_json(self):
        profile = _load_profile()
        assert isinstance(profile, dict)


class TestProfileValidatesUnderDraft202012Schema:
    def test_capability_profile_schema_itself_is_valid_draft_2020_12(self):
        schema = _load_schema()
        jsonschema.Draft202012Validator.check_schema(schema)

    def test_real_profile_validates_against_schema(self):
        profile = _load_profile()
        schema = _load_schema()
        validator = jsonschema.Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(profile), key=lambda e: list(e.path))
        assert errors == [], [e.message for e in errors]


class TestIdentityVersionSupportStatus:
    def test_schema_version(self):
        assert _load_profile()["schema_version"] == "capability-profile.v1"

    def test_artifact_type(self):
        assert _load_profile()["artifact_type"] == "capability_profile"

    def test_capability_profile_id(self):
        assert _load_profile()["capability_profile_id"] == "binary-predictive-classification"

    def test_capability_profile_version(self):
        assert _load_profile()["capability_profile_version"] == "v1"

    def test_support_status_is_current_supported(self):
        assert _load_profile()["support_status"] == "current_supported"


class TestSemanticRuntimePublicationPolicy:
    def test_target_semantics_applicability_required(self):
        profile = _load_profile()
        assert profile["semantic_requirements"]["target_semantics_applicability"] == "required"

    def test_prediction_runtime_applicable_true(self):
        assert _load_profile()["prediction_runtime"]["applicable"] is True

    def test_prediction_runtime_mode(self):
        profile = _load_profile()
        assert profile["prediction_runtime"]["mode"] == "single_model_binary_classification"

    def test_public_prediction_capability_applicability_optional(self):
        profile = _load_profile()
        assert profile["publication"]["public_prediction_capability_applicability"] == "optional"


class TestRoleApplicability:
    def _applicability(self, profile, role_name):
        matches = [
            entry["applicability"]
            for entry in profile["artifact_roles"]
            if entry["role_name"] == role_name
        ]
        assert len(matches) == 1, f"expected exactly one entry for role {role_name!r}, got {matches}"
        return matches[0]

    def test_discovery_evidence_required(self):
        assert self._applicability(_load_profile(), "discovery_evidence") == "required"

    def test_semantic_intent_required(self):
        assert self._applicability(_load_profile(), "semantic_intent") == "required"

    def test_preparation_recipe_required(self):
        assert self._applicability(_load_profile(), "preparation_recipe") == "required"

    def test_model_artifact_required(self):
        assert self._applicability(_load_profile(), "model_artifact") == "required"

    def test_visual_evidence_optional(self):
        assert self._applicability(_load_profile(), "visual_evidence") == "optional"

    def test_no_model_analysis_summary_forbidden(self):
        assert self._applicability(_load_profile(), "no_model_analysis_summary") == "forbidden"

    def test_no_duplicate_role_names(self):
        profile = _load_profile()
        role_names = [entry["role_name"] for entry in profile["artifact_roles"]]
        assert len(role_names) == len(set(role_names))

    def _authoring_boundary_applicability(self, profile, role_name):
        matches = [
            entry.get("authoring_boundary_applicability")
            for entry in profile["artifact_roles"]
            if entry["role_name"] == role_name
        ]
        assert len(matches) == 1, f"expected exactly one entry for role {role_name!r}, got {matches}"
        return matches[0]

    def test_model_artifact_authoring_boundary_applicability_optional(self):
        assert self._authoring_boundary_applicability(_load_profile(), "model_artifact") == "optional"

    def test_model_artifact_global_applicability_remains_required_despite_override(self):
        assert self._applicability(_load_profile(), "model_artifact") == "required"

    def test_only_model_artifact_declares_an_authoring_boundary_override(self):
        profile = _load_profile()
        overridden = {
            entry["role_name"] for entry in profile["artifact_roles"] if "authoring_boundary_applicability" in entry
        }
        assert overridden == {"model_artifact"}


class TestBoundaryConfirmationsAllFalse:
    def test_all_capability_boundary_confirmations_are_false(self):
        profile = _load_profile()
        confirmations = profile["capability_boundary_confirmations"]
        expected_keys = {
            "dataset_specific_selector_used",
            "dataset_specific_feature_names_present",
            "concrete_model_hashes_present",
            "model_bytes_embedded",
            "release_instance_metadata_embedded",
            "absolute_external_path_present",
            "training_result_values_embedded",
        }
        assert set(confirmations.keys()) == expected_keys
        for key, value in confirmations.items():
            assert value is False, f"{key} must be False, got {value!r}"


class TestNoDatasetOrTelcoSpecificCoupling:
    def test_no_dataset_slug_or_dataset_name_in_profile_text(self):
        text = _load_profile_text().lower()
        assert "sample-binary-classification-dataset" not in text
        assert "dataset_slug" not in text

    def test_no_telco_specific_identity_in_profile_text(self):
        text = _load_profile_text().lower()
        assert "telco" not in text
        assert "churn" not in text
        assert "tenure" not in text

    def test_no_model_hash_bytes_release_or_absolute_path_in_profile_text(self):
        text = _load_profile_text()
        assert "sha256" not in text.lower()
        assert "/home/" not in text
        assert "/workspace/" not in text
        assert "release_id" not in text
        assert "release-" not in text.lower()


class TestAgreementWithCurrentlySupportedConstants:
    def test_agrees_with_contract_derivation_currently_supported_capability_profile_id(self):
        profile = _load_profile()
        assert profile["capability_profile_id"] == CURRENTLY_SUPPORTED_CAPABILITY_PROFILE_ID

    def test_agrees_with_assemble_candidate_currently_supported_release_capability_profile_id(self):
        profile = _load_profile()
        assert profile["capability_profile_id"] == CURRENTLY_SUPPORTED_RELEASE_CAPABILITY_PROFILE_ID


class TestAuthoringBoundaryCompatibility:
    """Proves the real profile file participates in a synthetic S0166
    authoring-boundary validation (pipeline.authoring_contracts) using only
    inert fixture bytes under tmp_path -- never a real model, notebook, or
    release artifact."""

    def _manifest_for(self, profile: dict, *, roles: dict[str, bytes]) -> dict:
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
                "generated_at": "2026-08-11T00:00:00+00:00",
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
            "generated_at": "2026-08-11T00:00:00+00:00",
        }

    def _semantic_intent_for(self, profile: dict) -> dict:
        return {
            "schema_version": "dataset-semantic-intent.v1",
            "artifact_type": "dataset_semantic_intent",
            "dataset_identity": {"dataset_slug": DATASET_SLUG},
            "authoring_generation_id": "authoring-gen-0001",
            "governing_capability_profile": {
                "capability_profile_id": profile["capability_profile_id"],
                "capability_profile_version": profile["capability_profile_version"],
            },
            "field_role_decisions": [
                {"field_name": "identifier_field", "role": "identifier", "include_in_features": False},
                {"field_name": "numeric_feature", "role": "feature", "include_in_features": True},
            ],
            "target_semantics": {
                "target_field_name": "outcome",
                "task_type": "binary_classification",
                "positive_class": {"class_id": "positive", "event_label": "event"},
                "is_final_training_configuration": False,
            },
            "semantic_boundary_confirmations": {
                "observed_source_statistics_embedded": False,
                "scientific_conclusions_embedded": False,
                "training_outcome_embedded": False,
                "release_state_embedded": False,
                "model_bytes_embedded": False,
            },
            "generated_at": "2026-08-11T00:00:00+00:00",
        }

    def test_real_profile_passes_pre_materialization_authoring_validation_without_model_artifact(self, tmp_path):
        """S0185: the real profile's model_artifact.authoring_boundary_applicability
        override means a pre-materialization manifest -- discovery evidence,
        semantic intent, and preparation recipe present, model_artifact absent
        -- must validate successfully at the authoring boundary. No model is
        ever deserialized to prove this."""
        profile = _load_profile()
        roles = {
            "discovery_evidence": DISCOVERY_EVIDENCE_BYTES,
            "semantic_intent": SEMANTIC_INTENT_BYTES,
            "preparation_recipe": PREPARATION_RECIPE_BYTES,
        }
        manifest = self._manifest_for(profile, roles=roles)
        semantic_intent = self._semantic_intent_for(profile)

        for role_name, data in roles.items():
            artifact_path = tmp_path / "pipeline" / "evidence" / DATASET_SLUG / f"{role_name}.json"
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_bytes(data)

        result = validate_authoring_contracts(
            manifest,
            profile,
            semantic_intent=semantic_intent,
            artifact_root=tmp_path,
            expected_dataset_slug=DATASET_SLUG,
        )

        assert result.capability_profile_schema_valid is True
        assert result.valid is True, result.failures
        assert result.failures == ()
        assert result.capability_profile_id == "binary-predictive-classification"
        assert result.capability_profile_version == "v1"

    def test_real_profile_also_accepts_model_artifact_present_at_authoring_boundary(self, tmp_path):
        """An 'optional' authoring-boundary override means presence or
        absence is both valid -- this is the one test in this module that
        exercises downstream/global semantics with synthetic model bytes,
        never a requirement for pre-materialization validation."""
        profile = _load_profile()
        roles = {
            "discovery_evidence": DISCOVERY_EVIDENCE_BYTES,
            "semantic_intent": SEMANTIC_INTENT_BYTES,
            "preparation_recipe": PREPARATION_RECIPE_BYTES,
            "model_artifact": MODEL_ARTIFACT_BYTES,
        }
        manifest = self._manifest_for(profile, roles=roles)
        semantic_intent = self._semantic_intent_for(profile)

        for role_name, data in roles.items():
            artifact_path = tmp_path / "pipeline" / "evidence" / DATASET_SLUG / f"{role_name}.json"
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_bytes(data)

        result = validate_authoring_contracts(
            manifest,
            profile,
            semantic_intent=semantic_intent,
            artifact_root=tmp_path,
            expected_dataset_slug=DATASET_SLUG,
        )

        assert result.valid is True, result.failures

    def test_real_profile_rejects_missing_preparation_recipe(self, tmp_path):
        """preparation_recipe carries no authoring-boundary override, so it
        remains required at the authoring boundary exactly as before."""
        profile = _load_profile()
        roles = {
            "discovery_evidence": DISCOVERY_EVIDENCE_BYTES,
            "semantic_intent": SEMANTIC_INTENT_BYTES,
        }
        manifest = self._manifest_for(profile, roles=roles)

        result = validate_authoring_contracts(manifest, profile)

        assert result.valid is False
        assert any(
            failure.code == "required_role_missing" and failure.role == "preparation_recipe"
            for failure in result.failures
        )

    def test_real_profile_does_not_require_model_artifact_at_authoring_boundary(self, tmp_path):
        profile = _load_profile()
        roles = {
            "discovery_evidence": DISCOVERY_EVIDENCE_BYTES,
            "semantic_intent": SEMANTIC_INTENT_BYTES,
            "preparation_recipe": PREPARATION_RECIPE_BYTES,
        }
        manifest = self._manifest_for(profile, roles=roles)

        result = validate_authoring_contracts(manifest, profile)

        assert not any(failure.role == "model_artifact" for failure in result.failures)

    def test_real_profile_rejects_forbidden_role_present(self, tmp_path):
        profile = _load_profile()
        roles = {
            "discovery_evidence": DISCOVERY_EVIDENCE_BYTES,
            "semantic_intent": SEMANTIC_INTENT_BYTES,
            "preparation_recipe": PREPARATION_RECIPE_BYTES,
            "no_model_analysis_summary": b"forbidden-role-payload",
        }
        manifest = self._manifest_for(profile, roles=roles)

        result = validate_authoring_contracts(manifest, profile)

        assert result.valid is False
        assert any(
            failure.code == "forbidden_role_present" and failure.role == "no_model_analysis_summary"
            for failure in result.failures
        )
