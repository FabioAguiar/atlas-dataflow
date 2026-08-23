"""
Project Spec S0241: Univariate Forecasting Capability and Temporal Semantic
Intent Contract.

Proves the real, committed capability profile document at
pipeline/capabilities/univariate-predictive-forecasting.v1.json is a
governed capability profile, free of any dataset-specific coupling.

Project Spec S0250 flips support_status to current_supported once the
forecasting interaction implementation (frontend history-series form,
predict-view customization compatibility, capability activation) is
complete and its focused tests pass -- Atlas authoring can now derive and
execute a forecasting contract, train/materialize a forecasting model, emit
a forecasting inference bundle, and publish/serve forecasting through the
release-layer identity already recognized since S0247.

Uses only the real repository profile files and the real capability-profile
schema -- never a real model, never notebook execution, never a real
release candidate, publisher call, or registry mutation.
"""

import json
import sys
from pathlib import Path

import jsonschema

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pipeline.assemble_candidate import RELEASE_LAYER_SUPPORTED_CAPABILITY_PROFILE_IDS
from pipeline.contract_derivation import CONTRACT_PROJECTION_SUPPORTED_CAPABILITY_PROFILE_IDS

REPO_ROOT = Path(__file__).parent.parent.parent
FORECASTING_PROFILE_PATH = REPO_ROOT / "pipeline" / "capabilities" / "univariate-predictive-forecasting.v1.json"
BINARY_PROFILE_PATH = REPO_ROOT / "pipeline" / "capabilities" / "binary-predictive-classification.v1.json"
MULTICLASS_PROFILE_PATH = REPO_ROOT / "pipeline" / "capabilities" / "multiclass-predictive-classification.v1.json"
REGRESSION_PROFILE_PATH = REPO_ROOT / "pipeline" / "capabilities" / "continuous-predictive-regression.v1.json"
CAPABILITY_PROFILE_SCHEMA_PATH = REPO_ROOT / "pipeline" / "capability-profile.schema.json"


def _load_profile_text() -> str:
    return FORECASTING_PROFILE_PATH.read_text(encoding="utf-8")


def _load_profile() -> dict:
    return json.loads(_load_profile_text())


def _load_binary_profile() -> dict:
    return json.loads(BINARY_PROFILE_PATH.read_text(encoding="utf-8"))


def _load_multiclass_profile() -> dict:
    return json.loads(MULTICLASS_PROFILE_PATH.read_text(encoding="utf-8"))


def _load_regression_profile() -> dict:
    return json.loads(REGRESSION_PROFILE_PATH.read_text(encoding="utf-8"))


def _load_schema() -> dict:
    return json.loads(CAPABILITY_PROFILE_SCHEMA_PATH.read_text(encoding="utf-8"))


class TestProfileFileExistsAndParses:
    def test_profile_file_exists(self):
        assert FORECASTING_PROFILE_PATH.is_file()

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
        assert _load_profile()["capability_profile_id"] == "univariate-predictive-forecasting"

    def test_capability_profile_version(self):
        assert _load_profile()["capability_profile_version"] == "v1"

    def test_support_status_is_current_supported(self):
        assert _load_profile()["support_status"] == "current_supported"


class TestSemanticRuntimePublicationPolicy:
    def test_target_semantics_applicability_required(self):
        profile = _load_profile()
        assert profile["semantic_requirements"]["target_semantics_applicability"] == "required"

    def test_split_semantics_applicability_required(self):
        profile = _load_profile()
        assert profile["semantic_requirements"]["split_semantics_applicability"] == "required"

    def test_prediction_runtime_applicable_true(self):
        assert _load_profile()["prediction_runtime"]["applicable"] is True

    def test_prediction_runtime_mode(self):
        profile = _load_profile()
        assert profile["prediction_runtime"]["mode"] == "single_model_univariate_forecasting"

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


class TestNoDatasetSpecificOrNottinghamCoupling:
    def test_no_dataset_slug_in_profile_text(self):
        text = _load_profile_text().lower()
        assert "dataset_slug" not in text

    def test_no_nottingham_field_names_or_domain_terms_in_profile_text(self):
        text = _load_profile_text().lower()
        for forbidden in (
            "nottingham",
            "nottem",
            "airline",
            "passenger",
            "temperature",
            "sales",
        ):
            assert forbidden not in text, forbidden

    def test_no_model_hash_bytes_release_or_absolute_path_in_profile_text(self):
        text = _load_profile_text()
        assert "sha256" not in text.lower()
        assert "/home/" not in text
        assert "/workspace/" not in text
        assert "release_id" not in text
        assert "release-" not in text.lower()

    def test_no_training_result_values_in_profile_text(self):
        text = _load_profile_text().lower()
        for forbidden in ("mae", "rmse", "mape", "aic", "bic", "training_metrics"):
            assert forbidden not in text, forbidden


class TestExistingCapabilityProfilesRemainValidUnderSchemaExtension:
    def test_binary_profile_still_validates(self):
        schema = _load_schema()
        validator = jsonschema.Draft202012Validator(schema)
        errors = list(validator.iter_errors(_load_binary_profile()))
        assert errors == [], [e.message for e in errors]

    def test_multiclass_profile_still_validates(self):
        schema = _load_schema()
        validator = jsonschema.Draft202012Validator(schema)
        errors = list(validator.iter_errors(_load_multiclass_profile()))
        assert errors == [], [e.message for e in errors]

    def test_regression_profile_still_validates(self):
        schema = _load_schema()
        validator = jsonschema.Draft202012Validator(schema)
        errors = list(validator.iter_errors(_load_regression_profile()))
        assert errors == [], [e.message for e in errors]

    def test_binary_profile_runtime_mode_is_unchanged(self):
        assert _load_binary_profile()["prediction_runtime"]["mode"] == "single_model_binary_classification"

    def test_multiclass_profile_runtime_mode_is_unchanged(self):
        assert _load_multiclass_profile()["prediction_runtime"]["mode"] == "single_model_multiclass_classification"

    def test_regression_profile_runtime_mode_is_unchanged(self):
        assert _load_regression_profile()["prediction_runtime"]["mode"] == "single_model_continuous_regression"


class TestForecastingDownstreamOperationalStatus:
    """Project Spec S0250: the release-layer identity was already recognized
    since S0247 (independent of the real profile's own support_status); the
    real profile itself now flips to current_supported, activating that
    already-recognized identity end to end. The legacy source-contract
    projection route remains architecturally unsupported for forecasting and
    is untouched by S0250 -- univariate_forecasting is a history-series input
    family, not a source-contract scalar-feature projection."""

    def test_absent_from_contract_projection_supported_capability_profile_ids(self):
        assert "univariate-predictive-forecasting" not in CONTRACT_PROJECTION_SUPPORTED_CAPABILITY_PROFILE_IDS

    def test_present_in_release_layer_supported_capability_profile_ids(self):
        assert "univariate-predictive-forecasting" in RELEASE_LAYER_SUPPORTED_CAPABILITY_PROFILE_IDS

    def test_profile_declares_current_supported_not_requires_future_contract_evolution(self):
        profile = _load_profile()
        assert profile["support_status"] == "current_supported"
        assert profile["support_status"] != "requires_future_contract_evolution"
