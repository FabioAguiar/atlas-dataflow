"""
Tests for Project Spec S0155: External Analysis Handoff Schema, Trust, and
Read-Only Import Boundary Contract.

Uses only synthetic temporary packages and small inert byte fixtures. Never
uses the real Telco joblib artifact, executes notebooks, accesses
train/validation/test partitions, installs dependencies, calls a network
service, or mutates repository artifacts. No current Telco notebook-output
hash is hardcoded here as production truth.
"""

import copy
import hashlib
import json
import sys
from pathlib import Path

import jsonschema
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pipeline.external_analysis_handoff import (
    ValidationFailure,
    ValidationResult,
    validate_external_analysis_handoff,
)

REPO_ROOT = Path(__file__).parent.parent.parent
SCHEMA_PATH = REPO_ROOT / "pipeline" / "external-analysis-handoff.schema.json"
SOURCE_CONTRACT_INPUT_SCHEMA_PATH = REPO_ROOT / "pipeline" / "source-contract-input.schema.json"


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_sha256(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


MODEL_BYTES = b"synthetic-inert-opaque-model-bytes-not-a-real-joblib-file"
MANIFEST_PAYLOAD = {"role": "synthetic_manifest", "note": "inert fixture, not production truth"}


@pytest.fixture
def synthetic_package(tmp_path):
    """A minimal synthetic package with one opaque artifact and one JSON
    manifest artifact, modeling the two broad content-kind categories."""
    root = tmp_path / "package"
    root.mkdir()
    (root / "model.bin").write_bytes(MODEL_BYTES)
    manifest_text = json.dumps(MANIFEST_PAYLOAD, sort_keys=True, separators=(",", ":"))
    (root / "manifest.json").write_text(manifest_text, encoding="utf-8")
    return root


def _handoff(**overrides) -> dict:
    base = {
        "schema_version": "external-analysis-handoff.v1",
        "artifact_type": "external_analysis_handoff",
        "handoff_id": "handoff-20260803-001",
        "producer": {
            "producer_name": "Synthetic Study",
            "producer_project_id": "dataset-study-synthetic-fixture",
        },
        "consumer": {
            "consumer_system": "atlas-dataflow",
            "consumer_component": "pipeline.external_analysis_handoff",
        },
        "dataset_identity": {"dataset_slug": "synthetic-fixture"},
        "source_identity": {
            "source_dataset_ref": "datasets/synthetic-fixture/v1",
            "source_fingerprint": {"value": "a" * 64, "profile": "sha256-source-package.v1"},
        },
        "artifact_inventory": [
            {
                "role": "model_artifact",
                "path": "model.bin",
                "required": True,
                "content_kind": "opaque_model_artifact",
                "sha256": _sha256_bytes(MODEL_BYTES),
            },
            {
                "role": "model_manifest",
                "path": "manifest.json",
                "required": True,
                "content_kind": "json_manifest",
                "sha256": _sha256_bytes(
                    json.dumps(MANIFEST_PAYLOAD, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ),
            },
        ],
        "trusted_source_declaration": {
            "producer_asserts_trusted": True,
            "basis": "internal producer review",
        },
        "readiness": {
            "educational": {
                "educational_modeling_complete": True,
                "educational_threshold": {"metric": "roc_auc", "value": 0.81},
                "basis": "educational evaluation only",
            },
            "operational": {
                "operational_modeling_ready": False,
                "operational_prediction_available": False,
                "operational_validity": "unresolved",
                "operational_threshold": None,
            },
        },
        "operational_limitations": ["No operational threshold has been defined."],
        "immutability_declaration": {
            "package_is_immutable": True,
            "basis": "every inventoried artifact is content-addressed by SHA-256",
        },
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Schema shape (Acceptance Criteria 1-14, 27-30)
# ---------------------------------------------------------------------------


def test_schema_is_valid_draft_2020_12():
    schema = _load_schema()
    jsonschema.Draft202012Validator.check_schema(schema)


def test_schema_has_stable_id_version_and_artifact_type():
    schema = _load_schema()
    assert schema["$id"] == "https://atlas-dataflow.local/schemas/pipeline/external-analysis-handoff.schema.json"
    assert schema["properties"]["schema_version"]["const"] == "external-analysis-handoff.v1"
    assert schema["properties"]["artifact_type"]["const"] == "external_analysis_handoff"


def test_schema_rejects_undeclared_top_level_properties():
    schema = _load_schema()
    doc = _handoff()
    doc["unexpected_extra_field"] = "not allowed"
    validator = jsonschema.Draft202012Validator(schema)
    errors = [e for e in validator.iter_errors(doc)]
    assert any("additional" in e.message.lower() for e in errors)


def test_schema_rejects_undeclared_artifact_entry_properties():
    schema = _load_schema()
    doc = _handoff()
    doc["artifact_inventory"][0]["unexpected"] = "nope"
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(doc))


def test_valid_synthetic_handoff_passes_schema():
    schema = _load_schema()
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(_handoff())) == []


@pytest.mark.parametrize(
    "bad_path",
    [
        "/etc/passwd",
        "..\\windows\\system32",
        "..\\..\\secret.json",
        "C:\\Windows\\system.ini",
        "\\\\server\\share\\file.json",
        "../escape.json",
        "a/../../escape.json",
        "",
        ".",
        "..",
        "a//b.json",
    ],
)
def test_schema_rejects_unsafe_artifact_paths(bad_path):
    schema = _load_schema()
    doc = _handoff()
    doc["artifact_inventory"][0]["path"] = bad_path
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(doc)), f"expected schema rejection for path {bad_path!r}"


def test_schema_requires_sha256_lowercase_64_hex():
    schema = _load_schema()
    doc = _handoff()
    doc["artifact_inventory"][0]["sha256"] = "NOTHEX"
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(doc))


def test_schema_fixes_operational_readiness_to_safe_defaults():
    schema = _load_schema()
    doc = _handoff()
    doc["readiness"]["operational"]["operational_modeling_ready"] = True
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(doc))


def test_schema_rejects_operational_threshold_promotion():
    schema = _load_schema()
    doc = _handoff()
    doc["readiness"]["operational"]["operational_threshold"] = {"metric": "roc_auc", "value": 0.9}
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(doc))


def test_schema_rejects_operational_validity_promotion():
    schema = _load_schema()
    doc = _handoff()
    doc["readiness"]["operational"]["operational_validity"] = "valid"
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(doc))


def test_schema_preserves_educational_threshold_as_declared_evidence():
    schema = _load_schema()
    doc = _handoff()
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(doc)) == []
    assert doc["readiness"]["educational"]["educational_threshold"] == {"metric": "roc_auc", "value": 0.81}


def test_schema_requires_immutability_declaration_true():
    schema = _load_schema()
    doc = _handoff()
    doc["immutability_declaration"]["package_is_immutable"] = False
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(doc))


def test_schema_requires_dataset_identity_as_explicit_field_not_inferred():
    schema = _load_schema()
    doc = _handoff()
    del doc["dataset_identity"]["dataset_slug"]
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(doc))


# ---------------------------------------------------------------------------
# Validator: happy path (Acceptance Criteria 16, 17, 25, 26)
# ---------------------------------------------------------------------------


def test_validator_accepts_valid_synthetic_package(synthetic_package):
    result = validate_external_analysis_handoff(
        _handoff(), synthetic_package, trusted_source_confirmed=True
    )
    assert isinstance(result, ValidationResult)
    assert result.valid is True
    assert result.schema_valid is True
    assert result.load_eligible is True
    assert result.failures == ()
    assert result.validated_identities["dataset_slug"] == "synthetic-fixture"


def test_validator_accepts_handoff_path_argument(tmp_path, synthetic_package):
    handoff_path = tmp_path / "handoff.json"
    handoff_path.write_text(json.dumps(_handoff()), encoding="utf-8")
    result = validate_external_analysis_handoff(
        handoff_path, synthetic_package, trusted_source_confirmed=True
    )
    assert result.valid is True


def test_validator_reports_json_parsed_only_for_json_content_kinds(synthetic_package):
    result = validate_external_analysis_handoff(
        _handoff(), synthetic_package, trusted_source_confirmed=True
    )
    by_role = {r.role: r for r in result.artifact_results}
    assert by_role["model_artifact"].json_parsed is False
    assert by_role["model_manifest"].json_parsed is True


def test_validator_recomputes_hash_by_reading_bytes(synthetic_package):
    result = validate_external_analysis_handoff(
        _handoff(), synthetic_package, trusted_source_confirmed=True
    )
    by_role = {r.role: r for r in result.artifact_results}
    assert by_role["model_artifact"].observed_sha256 == _sha256_bytes(MODEL_BYTES)
    assert by_role["model_artifact"].sha256_matches is True


# ---------------------------------------------------------------------------
# Missing required file (Acceptance Criteria 13, 14)
# ---------------------------------------------------------------------------


def test_missing_required_artifact_fails_with_role_and_path(synthetic_package):
    (synthetic_package / "model.bin").unlink()
    result = validate_external_analysis_handoff(
        _handoff(), synthetic_package, trusted_source_confirmed=True
    )
    assert result.valid is False
    missing = [f for f in result.failures if f.code == "required_artifact_missing"]
    assert len(missing) == 1
    assert missing[0].role == "model_artifact"
    assert missing[0].path == "model.bin"


def test_missing_optional_artifact_is_not_fabricated_and_does_not_fail(synthetic_package):
    doc = _handoff()
    doc["artifact_inventory"].append(
        {
            "role": "optional_documentation",
            "path": "readme.md",
            "required": False,
            "content_kind": "documentation",
            "sha256": "b" * 64,
        }
    )
    result = validate_external_analysis_handoff(doc, synthetic_package, trusted_source_confirmed=True)
    assert result.valid is True
    optional_result = next(r for r in result.artifact_results if r.role == "optional_documentation")
    assert optional_result.present is False
    assert optional_result.observed_sha256 is None
    assert not any(f.role == "optional_documentation" for f in result.failures)


# ---------------------------------------------------------------------------
# Hash divergence (Acceptance Criterion 16)
# ---------------------------------------------------------------------------


def test_hash_divergence_fails_validation(synthetic_package):
    (synthetic_package / "model.bin").write_bytes(MODEL_BYTES + b"-tampered")
    result = validate_external_analysis_handoff(
        _handoff(), synthetic_package, trusted_source_confirmed=True
    )
    assert result.valid is False
    mismatches = [f for f in result.failures if f.code == "artifact_hash_mismatch"]
    assert len(mismatches) == 1
    assert mismatches[0].role == "model_artifact"


# ---------------------------------------------------------------------------
# Unsafe / escaping paths rejected by the validator itself (Acceptance
# Criteria 8, 9, 10), independent of schema-level rejection.
# ---------------------------------------------------------------------------


def test_validator_rejects_path_traversal_before_file_access(synthetic_package):
    doc = _handoff()
    # Bypass schema-level pattern rejection by constructing the payload
    # directly as a Python dict passed to the validator (not re-validated by
    # jsonschema's own pattern until the schema step, which happens first
    # and will already reject it -- this test asserts the validator's own
    # independent safety check would also reject it if ever reached).
    doc["artifact_inventory"][0]["path"] = "a/../../outside.bin"
    result = validate_external_analysis_handoff(doc, synthetic_package, trusted_source_confirmed=True)
    assert result.valid is False


def test_validator_rejects_symlink_escape_before_content_is_trusted(tmp_path, synthetic_package):
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.bin"
    secret.write_bytes(b"outside-the-package-root")

    escape_link = synthetic_package / "escape.bin"
    escape_link.symlink_to(secret)

    doc = _handoff()
    doc["artifact_inventory"][0]["path"] = "escape.bin"
    doc["artifact_inventory"][0]["sha256"] = _sha256_bytes(b"outside-the-package-root")

    result = validate_external_analysis_handoff(doc, synthetic_package, trusted_source_confirmed=True)
    assert result.valid is False
    escapes = [f for f in result.failures if f.code == "artifact_path_escapes_package_root"]
    assert len(escapes) == 1
    assert escapes[0].role == "model_artifact"


def test_duplicate_normalized_artifact_paths_rejected(synthetic_package):
    doc = _handoff()
    doc["artifact_inventory"].append(
        {
            "role": "model_artifact_duplicate",
            "path": "model.bin",
            "required": False,
            "content_kind": "opaque_model_artifact",
            "sha256": _sha256_bytes(MODEL_BYTES),
        }
    )
    result = validate_external_analysis_handoff(doc, synthetic_package, trusted_source_confirmed=True)
    assert result.valid is False
    assert any(f.code == "duplicate_artifact_path" for f in result.failures)


def test_duplicate_conflicting_role_declarations_rejected(synthetic_package):
    doc = _handoff()
    doc["artifact_inventory"].append(
        {
            "role": "model_artifact",
            "path": "manifest.json",
            "required": False,
            "content_kind": "json_manifest",
            "sha256": _sha256_bytes(
                json.dumps(MANIFEST_PAYLOAD, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ),
        }
    )
    result = validate_external_analysis_handoff(doc, synthetic_package, trusted_source_confirmed=True)
    assert result.valid is False
    assert any(f.code == "duplicate_role_declaration" for f in result.failures)


# ---------------------------------------------------------------------------
# Identity mismatch (Acceptance Criterion 22)
# ---------------------------------------------------------------------------


def test_dataset_slug_mismatch_fails(synthetic_package):
    result = validate_external_analysis_handoff(
        _handoff(),
        synthetic_package,
        trusted_source_confirmed=True,
        expected_dataset_slug="a-different-dataset",
    )
    assert result.valid is False
    assert any(f.code == "dataset_slug_mismatch" for f in result.failures)


def test_producer_project_id_mismatch_fails(synthetic_package):
    result = validate_external_analysis_handoff(
        _handoff(),
        synthetic_package,
        trusted_source_confirmed=True,
        expected_producer_project_id="a-different-producer",
    )
    assert result.valid is False
    assert any(f.code == "producer_project_id_mismatch" for f in result.failures)


def test_consumer_component_mismatch_fails(synthetic_package):
    result = validate_external_analysis_handoff(
        _handoff(),
        synthetic_package,
        trusted_source_confirmed=True,
        expected_consumer_component="a-different-component",
    )
    assert result.valid is False
    assert any(f.code == "consumer_component_mismatch" for f in result.failures)


def test_matching_expected_identities_pass(synthetic_package):
    result = validate_external_analysis_handoff(
        _handoff(),
        synthetic_package,
        trusted_source_confirmed=True,
        expected_dataset_slug="synthetic-fixture",
        expected_producer_project_id="dataset-study-synthetic-fixture",
        expected_consumer_component="pipeline.external_analysis_handoff",
    )
    assert result.valid is True


# ---------------------------------------------------------------------------
# Semantic fingerprint validation (Acceptance Criteria 20, 21, 22)
# ---------------------------------------------------------------------------


def test_json_canonical_fingerprint_verified_when_correct(synthetic_package):
    doc = _handoff()
    doc["artifact_inventory"][1]["semantic_fingerprint"] = {
        "value": _canonical_json_sha256(MANIFEST_PAYLOAD),
        "profile": "json-canonical-sha256.v1",
    }
    result = validate_external_analysis_handoff(doc, synthetic_package, trusted_source_confirmed=True)
    assert result.valid is True
    manifest_result = next(r for r in result.artifact_results if r.role == "model_manifest")
    assert manifest_result.semantic_fingerprint_status == "verified"


def test_json_canonical_fingerprint_mismatch_fails(synthetic_package):
    doc = _handoff()
    doc["artifact_inventory"][1]["semantic_fingerprint"] = {
        "value": "0" * 64,
        "profile": "json-canonical-sha256.v1",
    }
    result = validate_external_analysis_handoff(doc, synthetic_package, trusted_source_confirmed=True)
    assert result.valid is False
    assert any(f.code == "semantic_fingerprint_mismatch" for f in result.failures)


def test_unsupported_semantic_fingerprint_profile_fails_closed(synthetic_package):
    doc = _handoff()
    doc["artifact_inventory"][1]["semantic_fingerprint"] = {
        "value": "0" * 64,
        "profile": "some-unregistered-profile.v1",
    }
    result = validate_external_analysis_handoff(doc, synthetic_package, trusted_source_confirmed=True)
    assert result.valid is False
    assert any(f.code == "semantic_fingerprint_profile_unsupported" for f in result.failures)


def test_cross_artifact_model_state_fingerprint_consistent_passes(synthetic_package):
    doc = _handoff()
    doc["artifact_inventory"][0]["semantic_fingerprint"] = {
        "value": "shared-model-state-value",
        "profile": "cross-artifact-reference.v1",
    }
    doc["artifact_inventory"][1]["semantic_fingerprint"] = {
        "value": "shared-model-state-value",
        "profile": "cross-artifact-reference.v1",
    }
    result = validate_external_analysis_handoff(doc, synthetic_package, trusted_source_confirmed=True)
    assert result.valid is True
    by_role = {r.role: r for r in result.artifact_results}
    assert by_role["model_artifact"].semantic_fingerprint_status == "verified"
    assert by_role["model_manifest"].semantic_fingerprint_status == "verified"


def test_cross_artifact_model_state_fingerprint_conflict_fails(synthetic_package):
    doc = _handoff()
    doc["artifact_inventory"][0]["semantic_fingerprint"] = {
        "value": "model-state-a",
        "profile": "cross-artifact-reference.v1",
    }
    doc["artifact_inventory"][1]["semantic_fingerprint"] = {
        "value": "model-state-b",
        "profile": "cross-artifact-reference.v1",
    }
    result = validate_external_analysis_handoff(doc, synthetic_package, trusted_source_confirmed=True)
    assert result.valid is False
    assert any(f.code == "semantic_fingerprint_cross_reference_mismatch" for f in result.failures)


def test_cross_artifact_fingerprint_with_no_peer_is_not_a_failure(synthetic_package):
    doc = _handoff()
    doc["artifact_inventory"][0]["semantic_fingerprint"] = {
        "value": "only-one-declared-value",
        "profile": "cross-artifact-reference.v1",
    }
    result = validate_external_analysis_handoff(doc, synthetic_package, trusted_source_confirmed=True)
    assert result.valid is True
    model_result = next(r for r in result.artifact_results if r.role == "model_artifact")
    assert model_result.semantic_fingerprint_status == "no_cross_reference_peer"


# ---------------------------------------------------------------------------
# Trusted-source confirmation (Acceptance Criteria 23, 24)
# ---------------------------------------------------------------------------


def test_missing_trust_confirmation_fails_before_load_eligibility(synthetic_package):
    result = validate_external_analysis_handoff(
        _handoff(), synthetic_package, trusted_source_confirmed=False
    )
    assert result.valid is False
    assert result.load_eligible is False
    assert any(f.code == "trusted_source_confirmation_missing" for f in result.failures)


def test_producer_asserting_trust_does_not_substitute_for_caller_confirmation(synthetic_package):
    doc = _handoff()
    doc["trusted_source_declaration"]["producer_asserts_trusted"] = True
    result = validate_external_analysis_handoff(doc, synthetic_package, trusted_source_confirmed=False)
    assert result.load_eligible is False


def test_confirmed_trust_with_other_failures_is_still_not_load_eligible(synthetic_package):
    (synthetic_package / "model.bin").unlink()
    result = validate_external_analysis_handoff(
        _handoff(), synthetic_package, trusted_source_confirmed=True
    )
    assert result.valid is False
    assert result.load_eligible is False


# ---------------------------------------------------------------------------
# Zero deserialization (Acceptance Criteria 18, 19)
# ---------------------------------------------------------------------------


def test_no_joblib_or_pickle_symbols_imported_by_module():
    import ast

    import pipeline.external_analysis_handoff as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module.split(".")[0])
    assert "joblib" not in imported_names
    assert "pickle" not in imported_names
    assert not hasattr(module, "joblib")
    assert not hasattr(module, "pickle")


def test_validator_never_calls_joblib_load_or_pickle_load(monkeypatch, synthetic_package):
    def _forbidden(*_args, **_kwargs):
        raise AssertionError("joblib.load/pickle.load must never be called by this validator")

    try:
        import joblib

        monkeypatch.setattr(joblib, "load", _forbidden)
    except ImportError:
        pass

    import pickle

    monkeypatch.setattr(pickle, "load", _forbidden)
    monkeypatch.setattr(pickle, "loads", _forbidden)

    doc = _handoff()
    doc["artifact_inventory"][0]["semantic_fingerprint"] = {
        "value": "cross-checked-model-state",
        "profile": "cross-artifact-reference.v1",
    }
    result = validate_external_analysis_handoff(doc, synthetic_package, trusted_source_confirmed=True)
    assert result.valid is True


# ---------------------------------------------------------------------------
# No-mutation / no-writes proof (Acceptance Criterion 26)
# ---------------------------------------------------------------------------


def _package_manifest(root: Path) -> dict:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_validation_performs_no_filesystem_mutation(synthetic_package):
    before = _package_manifest(synthetic_package)
    validate_external_analysis_handoff(_handoff(), synthetic_package, trusted_source_confirmed=True)
    after = _package_manifest(synthetic_package)
    assert before == after


def test_validation_result_is_a_frozen_dataclass(synthetic_package):
    result = validate_external_analysis_handoff(
        _handoff(), synthetic_package, trusted_source_confirmed=True
    )
    with pytest.raises(Exception):
        result.valid = False  # type: ignore[misc]
    with pytest.raises(Exception):
        result.failures[0:0] = []  # type: ignore[index]


def test_validation_failure_entries_are_typed():
    result = validate_external_analysis_handoff(
        {"not": "a valid handoff"}, Path("/nonexistent"), trusted_source_confirmed=True
    )
    assert result.valid is False
    assert all(isinstance(f, ValidationFailure) for f in result.failures)


# ---------------------------------------------------------------------------
# Deterministic identity/failure inspection for invalid schema documents
# ---------------------------------------------------------------------------


def test_invalid_schema_document_stops_before_artifact_inspection(synthetic_package):
    doc = _handoff()
    del doc["dataset_identity"]
    result = validate_external_analysis_handoff(doc, synthetic_package, trusted_source_confirmed=True)
    assert result.valid is False
    assert result.schema_valid is False
    assert result.artifact_results == ()


def test_handoff_not_found_path_reports_failure_without_raising(synthetic_package):
    result = validate_external_analysis_handoff(
        Path("/nonexistent/handoff.json"), synthetic_package, trusted_source_confirmed=True
    )
    assert result.valid is False
    assert any(f.code == "handoff_not_found" for f in result.failures)


def test_handoff_not_valid_json_reports_failure(tmp_path, synthetic_package):
    bad_json_path = tmp_path / "bad.json"
    bad_json_path.write_text("{not valid json", encoding="utf-8")
    result = validate_external_analysis_handoff(
        bad_json_path, synthetic_package, trusted_source_confirmed=True
    )
    assert result.valid is False
    assert any(f.code == "handoff_not_valid_json" for f in result.failures)


def test_package_root_not_a_directory_is_a_failure():
    result = validate_external_analysis_handoff(
        _handoff(), Path("/definitely/does/not/exist"), trusted_source_confirmed=True
    )
    assert result.valid is False
    assert any(f.code == "package_root_not_a_directory" for f in result.failures)


def test_handoff_payload_is_not_mutated_by_validation(synthetic_package):
    doc = _handoff()
    before = copy.deepcopy(doc)
    validate_external_analysis_handoff(doc, synthetic_package, trusted_source_confirmed=True)
    assert doc == before


# ---------------------------------------------------------------------------
# source-contract-input.schema.json: bounded external lineage extension
# (Acceptance Criteria 31, 32, 33)
# ---------------------------------------------------------------------------


def _load_source_contract_input_schema() -> dict:
    return json.loads(SOURCE_CONTRACT_INPUT_SCHEMA_PATH.read_text(encoding="utf-8"))


EXISTING_SOURCE_CONTRACT_INPUT_FIXTURE = {
    "schema_version": "source-contract-input.v1",
    "dataset_slug": "fixture-dataset",
    "release_id": "release-20260623-001",
    "source_contract_ref": "contracts/runtime-contract.schema.json",
    "source_data_ref": "datasets/fixture/v1",
}


def test_existing_source_contract_input_fixture_remains_valid():
    schema = _load_source_contract_input_schema()
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(EXISTING_SOURCE_CONTRACT_INPUT_FIXTURE)) == []


def test_source_contract_input_with_safe_external_handoff_ref_is_valid():
    schema = _load_source_contract_input_schema()
    validator = jsonschema.Draft202012Validator(schema)
    doc = dict(
        EXISTING_SOURCE_CONTRACT_INPUT_FIXTURE,
        external_analysis_handoff_ref="handoffs/fixture-dataset/handoff-20260803-001.json",
    )
    assert list(validator.iter_errors(doc)) == []


@pytest.mark.parametrize(
    "bad_ref",
    [
        "/etc/passwd",
        "../escape.json",
        "C:\\Windows\\system.ini",
        "\\\\server\\share\\file.json",
    ],
)
def test_source_contract_input_rejects_unsafe_external_handoff_ref(bad_ref):
    schema = _load_source_contract_input_schema()
    validator = jsonschema.Draft202012Validator(schema)
    doc = dict(EXISTING_SOURCE_CONTRACT_INPUT_FIXTURE, external_analysis_handoff_ref=bad_ref)
    assert list(validator.iter_errors(doc))


def test_external_handoff_ref_does_not_replace_existing_reference_fields():
    schema = _load_source_contract_input_schema()
    required = set(schema["required"])
    assert "external_analysis_handoff_ref" not in required
    assert {"source_contract_ref", "source_data_ref"}.issubset(required)
    assert "source_contract_ref" in schema["properties"]
    assert "source_data_ref" in schema["properties"]
    assert "source_notebook_ref" in schema["properties"]
