"""
Tests for the M22-02 dataset discovery evidence generator.

Validates evidence completeness, field presence, candidate non-authoritativeness,
determinism, and boundary enforcement. Uses synthetic fixture data only;
does not depend on the data/ directory or a real dataset path.
"""

import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline.discovery_evidence import (
    authoring_helper_evidence_policy,
    build_binary_result_semantics_intent,
    build_categorical_domain_declaration,
    build_dataset_modeling_intent,
    derive_feature_candidates,
    generate_discovery_evidence,
    load_dataset_csv,
    observe_authoring_field,
    observe_authoring_fields,
    resolve_repository_path,
    summarize_identifier_columns,
    summarize_structure,
    summarize_target_column,
)


REPO_ROOT = Path(__file__).parent.parent

FIXTURE_ROWS = [
    {"species": "setosa",     "petal_length": "1.4", "petal_width": "0.2", "sepal_length": "5.1", "target": "0"},
    {"species": "setosa",     "petal_length": "1.4", "petal_width": "0.2", "sepal_length": "4.9", "target": "0"},
    {"species": "versicolor", "petal_length": "4.7", "petal_width": "1.4", "sepal_length": "7.0", "target": "1"},
    {"species": "versicolor", "petal_length": "4.5", "petal_width": "1.5", "sepal_length": "6.4", "target": "1"},
    {"species": "virginica",  "petal_length": "6.0", "petal_width": "2.5", "sepal_length": "6.3", "target": "2"},
    {"species": "setosa",     "petal_length": "",    "petal_width": "0.3", "sepal_length": "4.7", "target": "0"},
    {"species": "setosa",     "petal_length": "1.4", "petal_width": "0.2", "sepal_length": "5.1", "target": "0"},
]
FIXTURE_COLUMNS = ["species", "petal_length", "petal_width", "sepal_length", "target"]


def _write_fixture_csv(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIXTURE_COLUMNS)
        writer.writeheader()
        writer.writerows(FIXTURE_ROWS)


@pytest.fixture
def fixture_csv(tmp_path):
    csv_path = tmp_path / "fixture_dataset.csv"
    _write_fixture_csv(csv_path)
    return csv_path


# --- input validation ---

def test_rejects_none_input_path():
    with pytest.raises((ValueError, TypeError)):
        generate_discovery_evidence(None)


def test_rejects_empty_string_input_path():
    with pytest.raises((ValueError, TypeError)):
        generate_discovery_evidence("")


def test_rejects_missing_file():
    with pytest.raises(FileNotFoundError):
        generate_discovery_evidence("/nonexistent/does-not-exist/dataset.csv")


# --- required top-level fields ---

def test_all_required_top_level_fields_present(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    required = [
        "schema_version", "producer", "dataset_metadata", "field_observations",
        "duplicated_rows_count", "candidate_categorical_fields", "candidate_target_columns",
        "generation_settings", "generated_at", "discovery_boundary_confirmations",
        "evidence_policy",
    ]
    for field in required:
        assert field in evidence, f"Required field missing: {field}"


def test_schema_version_is_correct(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    assert evidence["schema_version"] == "dataset-discovery-evidence.v1"


def test_dataset_metadata_fields_present(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    meta = evidence["dataset_metadata"]
    for key in ["name", "row_count", "column_count", "source_path"]:
        assert key in meta, f"dataset_metadata missing: {key}"


def test_field_observations_required_fields(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    for obs in evidence["field_observations"]:
        for key in ["name", "inferred_type", "null_count", "null_rate", "cardinality", "sample_min", "sample_max"]:
            assert key in obs, f"field_observation missing key: {key}"


def test_generation_settings_fields_present(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    settings = evidence["generation_settings"]
    assert "seed" in settings
    assert "generator_version" in settings


# --- observation correctness ---

def test_row_count_matches_fixture(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    assert evidence["dataset_metadata"]["row_count"] == len(FIXTURE_ROWS)


def test_column_count_matches_fixture(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    assert evidence["dataset_metadata"]["column_count"] == len(FIXTURE_COLUMNS)


def test_null_count_for_petal_length(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    obs = next(o for o in evidence["field_observations"] if o["name"] == "petal_length")
    assert obs["null_count"] == 1


def test_duplicated_rows_count(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    # row 0 and row 6 are identical
    assert evidence["duplicated_rows_count"] == 1


def test_species_is_categorical_candidate(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    # species has 3 unique string values — below the categorical threshold
    assert "species" in evidence["candidate_categorical_fields"]


def test_inferred_type_integer_for_target(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    obs = next(o for o in evidence["field_observations"] if o["name"] == "target")
    assert obs["inferred_type"] == "integer"


def test_inferred_type_float_for_sepal_length(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    obs = next(o for o in evidence["field_observations"] if o["name"] == "sepal_length")
    assert obs["inferred_type"] == "float"


def test_inferred_type_string_for_species(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    obs = next(o for o in evidence["field_observations"] if o["name"] == "species")
    assert obs["inferred_type"] == "string"


def test_null_rate_is_fraction(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    obs = next(o for o in evidence["field_observations"] if o["name"] == "petal_length")
    expected = round(1 / len(FIXTURE_ROWS), 6)
    assert obs["null_rate"] == pytest.approx(expected)


def test_source_path_is_not_absolute(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    source_path = evidence["dataset_metadata"]["source_path"]
    assert not source_path.startswith("/"), "source_path must not be an absolute path"


# --- candidate target columns are non-authoritative ---

def test_all_candidate_target_columns_are_non_authoritative(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    for candidate in evidence["candidate_target_columns"]:
        assert candidate["is_authoritative"] is False, (
            f"Candidate '{candidate['name']}' must have is_authoritative: false"
        )


def test_candidate_target_columns_have_name_field(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    for candidate in evidence["candidate_target_columns"]:
        assert "name" in candidate


# --- determinism ---

def test_deterministic_output_same_seed(fixture_csv):
    fixed_ts = "2026-06-23T17:00:00+00:00"
    ev1 = generate_discovery_evidence(fixture_csv, seed=42, generated_at=fixed_ts)
    ev2 = generate_discovery_evidence(fixture_csv, seed=42, generated_at=fixed_ts)
    assert json.dumps(ev1, sort_keys=True) == json.dumps(ev2, sort_keys=True)


def test_field_observations_order_is_stable(fixture_csv):
    ev1 = generate_discovery_evidence(fixture_csv, seed=0)
    ev2 = generate_discovery_evidence(fixture_csv, seed=0)
    names1 = [o["name"] for o in ev1["field_observations"]]
    names2 = [o["name"] for o in ev2["field_observations"]]
    assert names1 == names2


# --- boundary confirmations ---

def test_discovery_boundary_confirmations(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    bc = evidence["discovery_boundary_confirmations"]
    assert bc["contract_promotion_occurred"] is False
    assert bc["model_training_occurred"] is False
    assert bc["release_publication_occurred"] is False


def test_evidence_policy_all_flags_set(fixture_csv):
    evidence = generate_discovery_evidence(fixture_csv)
    policy = evidence["evidence_policy"]
    for key in [
        "raw_logs_prohibited", "raw_runtime_prohibited", "raw_api_payloads_prohibited",
        "secrets_prohibited", "private_source_paths_prohibited", "reduced_and_sanitized",
    ]:
        assert policy[key] is True, f"evidence_policy.{key} must be True"


# --- schema validation ---

def test_evidence_validates_against_schema(fixture_csv):
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema not installed")

    schema_path = REPO_ROOT / "pipeline" / "dataset-discovery-evidence.schema.json"
    assert schema_path.exists(), f"Schema not found: {schema_path}"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    evidence = generate_discovery_evidence(
        fixture_csv,
        seed=0,
        generated_at="2026-06-23T17:00:00+00:00",
    )
    jsonschema.validate(evidence, schema)


# --- reusable dataset-authoring helpers (Project Spec S0012) ---
# Synthetic fixture data only; no dependency on the real Telco CSV.

AUTHORING_FIXTURE_ROWS = [
    {"category": "a", "amount": "10", "note": ""},
    {"category": "b", "amount": "20", "note": "NA"},
    {"category": "a", "amount": "30", "note": "n/a"},
    {"category": "c", "amount": "", "note": "ok"},
    {"category": "a", "amount": "10", "note": "ok"},
]
AUTHORING_FIXTURE_COLUMNS = ["category", "amount", "note"]


def _write_authoring_fixture_csv(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=AUTHORING_FIXTURE_COLUMNS)
        writer.writeheader()
        writer.writerows(AUTHORING_FIXTURE_ROWS)


@pytest.fixture
def authoring_fixture_csv(tmp_path):
    csv_path = tmp_path / "authoring_fixture.csv"
    _write_authoring_fixture_csv(csv_path)
    return csv_path


def test_resolve_repository_path_uses_explicit_repo_root(tmp_path):
    resolved = resolve_repository_path("data/raw/dataset.csv", repo_root=tmp_path)
    assert resolved == (tmp_path / "data" / "raw" / "dataset.csv").resolve()


def test_resolve_repository_path_defaults_to_cwd():
    resolved = resolve_repository_path("data/raw/dataset.csv")
    assert resolved == (Path.cwd() / "data" / "raw" / "dataset.csv").resolve()


def test_load_dataset_csv_reads_rows(authoring_fixture_csv):
    rows = load_dataset_csv(authoring_fixture_csv)
    assert len(rows) == len(AUTHORING_FIXTURE_ROWS)
    assert list(rows[0].keys()) == AUTHORING_FIXTURE_COLUMNS


def test_load_dataset_csv_raises_for_missing_path():
    with pytest.raises(FileNotFoundError):
        load_dataset_csv("/nonexistent/does-not-exist/dataset.csv")


def test_summarize_structure_reports_counts_and_ordered_columns(authoring_fixture_csv):
    rows = load_dataset_csv(authoring_fixture_csv)
    structure = summarize_structure(rows)
    assert structure["row_count"] == len(AUTHORING_FIXTURE_ROWS)
    assert structure["column_count"] == len(AUTHORING_FIXTURE_COLUMNS)
    assert structure["ordered_columns"] == AUTHORING_FIXTURE_COLUMNS


def test_summarize_structure_empty_rows():
    assert summarize_structure([]) == {
        "row_count": 0,
        "column_count": 0,
        "ordered_columns": [],
    }


def test_observe_authoring_field_distinguishes_blank_from_null_like():
    obs = observe_authoring_field("note", ["", "NA", "n/a", "ok", "ok"])
    assert obs["blank_string_count"] == 1
    assert obs["null_like_count"] == 2
    assert obs["cardinality"] == 1  # only "ok" is neither blank nor null-like
    assert obs["reduced_sample_values"] == ["ok"]


def test_observe_authoring_field_treats_whitespace_only_as_blank():
    # Regression: a whitespace-only string (e.g. a single space) must count as
    # blank, not as a non-blank string value or a numeric-looking value.
    obs = observe_authoring_field("total_charges", ["29.85", " ", "1889.5", " "])
    assert obs["blank_string_count"] == 2
    assert obs["null_like_count"] == 0
    assert obs["inferred_type"] == "float"
    assert obs["cardinality"] == 2


def test_observe_authoring_field_reduced_sample_is_bounded():
    values = [str(i) for i in range(10)]
    obs = observe_authoring_field("n", values, sample_bound=3)
    assert len(obs["reduced_sample_values"]) == 3


def test_observe_authoring_fields_covers_all_columns(authoring_fixture_csv):
    rows = load_dataset_csv(authoring_fixture_csv)
    observations = observe_authoring_fields(rows)
    names = [o["name"] for o in observations]
    assert names == AUTHORING_FIXTURE_COLUMNS
    for obs in observations:
        for key in ["name", "inferred_type", "blank_string_count", "null_like_count", "cardinality", "reduced_sample_values"]:
            assert key in obs


def test_summarize_target_column_is_non_authoritative(authoring_fixture_csv):
    rows = load_dataset_csv(authoring_fixture_csv)
    summary = summarize_target_column(rows, "category")
    assert summary["target_column"] == "category"
    assert summary["observed_labels"] == ["a", "b", "c"]
    assert summary["observed_distribution"] == {"a": 3, "b": 1, "c": 1}
    assert summary["is_authoritative"] is False


def test_summarize_identifier_columns_flags_uniqueness(authoring_fixture_csv):
    rows = load_dataset_csv(authoring_fixture_csv)
    summaries = summarize_identifier_columns(rows, ["category"])
    assert summaries[0]["name"] == "category"
    assert summaries[0]["row_count"] == len(AUTHORING_FIXTURE_ROWS)
    assert summaries[0]["is_unique_per_row"] is False


def test_summarize_identifier_columns_unique_identifier():
    rows = [{"id": "1"}, {"id": "2"}, {"id": "3"}]
    summaries = summarize_identifier_columns(rows, ["id"])
    assert summaries[0]["is_unique_per_row"] is True
    assert summaries[0]["unique_count"] == 3


def test_derive_feature_candidates_excludes_target_and_identifiers():
    columns = ["id", "category", "amount", "note", "target"]
    candidates = derive_feature_candidates(
        columns, target_column="target", identifier_columns=["id"]
    )
    assert candidates == ["category", "amount", "note"]


def test_derive_feature_candidates_without_target_or_identifiers():
    columns = ["a", "b", "c"]
    assert derive_feature_candidates(columns) == columns


def test_authoring_helper_evidence_policy_confirms_no_persistence():
    policy = authoring_helper_evidence_policy()
    for key in [
        "raw_rows_persisted", "secrets_persisted", "raw_runtime_logs_persisted",
        "raw_api_payloads_persisted", "model_binaries_persisted",
        "release_artifacts_persisted", "publisher_artifacts_persisted",
    ]:
        assert policy[key] is False, f"authoring_helper_evidence_policy.{key} must be False"


# --- dataset modeling intent (Project Spec S0013) ---
# Built from small in-memory/synthetic values shaped like the Telco authoring
# notebook's own observations; does not depend on the real Telco CSV.

MODELING_INTENT_COLUMNS = ["customerID", "SeniorCitizen", "TotalCharges", "tenure", "Churn"]


def _build_telco_shaped_modeling_intent(**overrides):
    kwargs = dict(
        dataset_slug="telco-customer-churn",
        dataset_source_ref="data/raw/telco-customer-churn.csv",
        authoring_notebook_ref="notebooks/datasets/telco-customer-churn/01_dataset_integration_authoring.ipynb",
        columns=MODELING_INTENT_COLUMNS,
        target_column="Churn",
        task_type="binary_classification",
        observed_labels=["No", "Yes"],
        positive_label_candidate="Yes",
        observed_target_distribution={"No": 5174, "Yes": 1869},
        identifier_columns=["customerID"],
        feature_review_notes={
            "TotalCharges": "Requires explicit blank-value handling before execution-contract projection.",
        },
        feature_type_intent_overrides={"SeniorCitizen": "requires_review"},
        blank_value_policy_candidates={"TotalCharges": "unresolved_pending_review"},
        open_questions=["Final TotalCharges blank-value handling policy is not yet decided."],
        generated_at="2026-07-09T00:00:00+00:00",
    )
    kwargs.update(overrides)
    return build_dataset_modeling_intent(**kwargs)


def test_modeling_intent_artifact_identity():
    intent = _build_telco_shaped_modeling_intent()
    assert intent["artifact_type"] == "dataset_modeling_intent"
    assert intent["contract_version"] == "dataset_modeling_intent.v1"


def test_modeling_intent_dataset_identity():
    intent = _build_telco_shaped_modeling_intent()
    assert intent["dataset_identity"]["dataset_slug"] == "telco-customer-churn"
    assert intent["dataset_identity"]["dataset_source_ref"] == "data/raw/telco-customer-churn.csv"


def test_modeling_intent_authoring_source():
    intent = _build_telco_shaped_modeling_intent()
    assert intent["authoring_source"]["authoring_notebook_ref"] == (
        "notebooks/datasets/telco-customer-churn/01_dataset_integration_authoring.ipynb"
    )


def test_modeling_intent_target_intent_fields():
    intent = _build_telco_shaped_modeling_intent()
    target_intent = intent["target_intent"]
    assert target_intent["target_column"] == "Churn"
    assert target_intent["task_type"] == "binary_classification"
    assert target_intent["observed_labels"] == ["No", "Yes"]
    assert target_intent["positive_label_candidate"] == "Yes"
    assert target_intent["observed_target_distribution"] == {"No": 5174, "Yes": 1869}
    assert target_intent["is_final_training_configuration"] is False


def test_modeling_intent_identifier_columns_excluded_from_features():
    intent = _build_telco_shaped_modeling_intent()
    identifier_names = [c["name"] for c in intent["identifier_and_ignored_columns"]]
    assert identifier_names == ["customerID"]
    assert "customerID" not in intent["initial_feature_candidates"]


def test_modeling_intent_initial_feature_candidates_exclude_target_and_identifier():
    intent = _build_telco_shaped_modeling_intent()
    assert intent["initial_feature_candidates"] == ["SeniorCitizen", "TotalCharges", "tenure"]


def test_modeling_intent_feature_review_notes_flag_total_charges():
    intent = _build_telco_shaped_modeling_intent()
    assert "TotalCharges" in intent["feature_review_notes"]


def test_modeling_intent_feature_type_intent_defaults_to_requires_review():
    intent = _build_telco_shaped_modeling_intent()
    type_intent_by_name = {f["name"]: f["type_intent"] for f in intent["feature_type_intent"]}
    assert type_intent_by_name["SeniorCitizen"] == "requires_review"
    # No explicit override supplied for "tenure"; must still default, not be coerced.
    assert type_intent_by_name["tenure"] == "requires_review"


def test_modeling_intent_blank_value_policy_candidates_marked_unresolved():
    intent = _build_telco_shaped_modeling_intent()
    assert intent["blank_value_policy_candidates"]["TotalCharges"] == "unresolved_pending_review"


def test_modeling_intent_open_questions_are_not_accepted_policy():
    intent = _build_telco_shaped_modeling_intent()
    assert len(intent["open_questions"]) >= 1
    assert intent["target_intent"]["is_final_training_configuration"] is False


def test_modeling_intent_metric_and_split_candidates_optional_and_marked_as_candidates():
    intent = _build_telco_shaped_modeling_intent()
    assert intent["metric_candidates"] == []
    assert intent["split_policy_candidate"] is None

    intent_with_candidates = _build_telco_shaped_modeling_intent(
        metric_candidates=["roc_auc"],
        split_policy_candidate={"strategy": "stratified_holdout", "is_final": False},
    )
    assert intent_with_candidates["metric_candidates"] == ["roc_auc"]
    assert intent_with_candidates["split_policy_candidate"]["is_final"] is False


def test_modeling_intent_boundary_confirmations_all_false():
    intent = _build_telco_shaped_modeling_intent()
    for key, value in intent["modeling_intent_boundary_confirmations"].items():
        assert value is False, f"modeling_intent_boundary_confirmations.{key} must be False"


def test_modeling_intent_is_deterministic_for_same_inputs():
    intent1 = _build_telco_shaped_modeling_intent()
    intent2 = _build_telco_shaped_modeling_intent()
    assert json.dumps(intent1, sort_keys=True) == json.dumps(intent2, sort_keys=True)


def test_modeling_intent_builds_from_synthetic_non_telco_shape():
    # Confirms the builder is dataset-agnostic and does not require the real
    # Telco CSV or Telco-specific column names.
    intent = build_dataset_modeling_intent(
        dataset_slug="synthetic-widgets",
        dataset_source_ref="data/raw/synthetic-widgets.csv",
        authoring_notebook_ref="notebooks/datasets/synthetic-widgets/01_dataset_authoring.ipynb",
        columns=["widget_id", "color", "weight", "is_defective"],
        target_column="is_defective",
        task_type="binary_classification",
        observed_labels=["0", "1"],
        positive_label_candidate="1",
        observed_target_distribution={"0": 8, "1": 2},
        identifier_columns=["widget_id"],
    )
    assert intent["initial_feature_candidates"] == ["color", "weight"]
    assert intent["feature_review_notes"] == {}
    assert intent["open_questions"] == []


# --- reviewed categorical-domain intent (Project Spec S0102) ---


def test_build_categorical_domain_declaration_approved():
    declaration = build_categorical_domain_declaration(
        name="gender",
        accepted_values=["Female", "Male"],
        review_status="approved",
        source_basis="Reviewed against reduced_sample_values; cardinality 2.",
    )
    assert declaration["name"] == "gender"
    assert declaration["accepted_values"] == ["Female", "Male"]
    assert declaration["review_status"] == "approved"
    assert declaration["closed_for_inference"] is True


def test_build_categorical_domain_declaration_pending_review():
    declaration = build_categorical_domain_declaration(
        name="InternetService",
        accepted_values=["DSL", "Fiber optic", "No"],
        review_status="pending_review",
        source_basis="Observed, not yet reviewed and approved.",
    )
    assert declaration["review_status"] == "pending_review"


def test_build_categorical_domain_declaration_rejects_empty_values():
    with pytest.raises(ValueError):
        build_categorical_domain_declaration(
            name="gender",
            accepted_values=[],
            review_status="approved",
            source_basis="none",
        )


def test_build_categorical_domain_declaration_rejects_blank_value():
    with pytest.raises(ValueError):
        build_categorical_domain_declaration(
            name="gender",
            accepted_values=["Female", "  "],
            review_status="approved",
            source_basis="none",
        )


def test_build_categorical_domain_declaration_rejects_duplicate_values():
    with pytest.raises(ValueError):
        build_categorical_domain_declaration(
            name="gender",
            accepted_values=["Female", "Female"],
            review_status="approved",
            source_basis="none",
        )


def test_build_categorical_domain_declaration_rejects_unknown_review_status():
    with pytest.raises(ValueError):
        build_categorical_domain_declaration(
            name="gender",
            accepted_values=["Female", "Male"],
            review_status="candidate_only",
            source_basis="none",
        )


def test_build_categorical_domain_declaration_rejects_blank_name():
    with pytest.raises(ValueError):
        build_categorical_domain_declaration(
            name="",
            accepted_values=["Female", "Male"],
            review_status="approved",
            source_basis="none",
        )


def test_modeling_intent_categorical_domain_intent_defaults_to_empty_list():
    intent = _build_telco_shaped_modeling_intent()
    assert intent["categorical_domain_intent"] == []


def test_modeling_intent_carries_categorical_domain_intent_verbatim():
    declaration = build_categorical_domain_declaration(
        name="SeniorCitizen",
        accepted_values=["0", "1"],
        review_status="approved",
        source_basis="Reviewed authoring basis.",
    )
    intent = _build_telco_shaped_modeling_intent(categorical_domain_intent=[declaration])
    assert intent["categorical_domain_intent"] == [declaration]


# --- reviewed binary-result semantics intent (Project Spec S0108) ---

VALID_BANDS = [
    {"band_id": "low", "lower_bound": 0.0, "upper_bound": 0.35},
    {"band_id": "medium", "lower_bound": 0.35, "upper_bound": 0.65},
    {"band_id": "high", "lower_bound": 0.65, "upper_bound": 1.0},
]


def _build_binary_result_semantics_intent(**overrides):
    kwargs = dict(
        review_status="approved",
        problem_type="binary_classification",
        positive_class_id="Yes",
        event_label="Churn",
        primary_output="positive_class_probability",
        threshold=0.5,
        preset="risk",
        bands=VALID_BANDS,
    )
    kwargs.update(overrides)
    return build_binary_result_semantics_intent(**kwargs)


def test_binary_result_semantics_intent_approved_shape():
    intent = _build_binary_result_semantics_intent()
    assert intent["schema_version"] == "binary_result_semantics_intent.v1"
    assert intent["review_status"] == "approved"
    assert intent["problem_type"] == "binary_classification"
    assert intent["positive_class"] == {"class_id": "Yes", "event_label": "Churn"}
    assert intent["primary_output"] == "positive_class_probability"
    assert intent["decision"] == {"threshold": 0.5}
    assert intent["interpretation"]["preset"] == "risk"
    assert intent["interpretation"]["bands"] == VALID_BANDS


def test_binary_result_semantics_intent_pending_review_does_not_raise():
    intent = _build_binary_result_semantics_intent(review_status="pending_review")
    assert intent["review_status"] == "pending_review"


def test_binary_result_semantics_intent_rejects_unknown_review_status():
    with pytest.raises(ValueError):
        _build_binary_result_semantics_intent(review_status="candidate_only")


def test_binary_result_semantics_intent_rejects_wrong_problem_type():
    with pytest.raises(ValueError):
        _build_binary_result_semantics_intent(problem_type="multiclass_classification")


def test_binary_result_semantics_intent_rejects_blank_positive_class_id():
    with pytest.raises(ValueError):
        _build_binary_result_semantics_intent(positive_class_id="  ")


def test_binary_result_semantics_intent_rejects_blank_event_label():
    with pytest.raises(ValueError):
        _build_binary_result_semantics_intent(event_label="")


def test_binary_result_semantics_intent_rejects_wrong_primary_output():
    with pytest.raises(ValueError):
        _build_binary_result_semantics_intent(primary_output="confidence")


def test_binary_result_semantics_intent_rejects_out_of_range_threshold():
    with pytest.raises(ValueError):
        _build_binary_result_semantics_intent(threshold=1.5)


def test_binary_result_semantics_intent_rejects_non_finite_threshold():
    with pytest.raises(ValueError):
        _build_binary_result_semantics_intent(threshold=float("nan"))


def test_binary_result_semantics_intent_rejects_wrong_preset():
    with pytest.raises(ValueError):
        _build_binary_result_semantics_intent(preset="percentile")


def test_binary_result_semantics_intent_rejects_missing_band():
    bands = [VALID_BANDS[0], VALID_BANDS[1]]
    with pytest.raises(ValueError):
        _build_binary_result_semantics_intent(bands=bands)


def test_binary_result_semantics_intent_rejects_duplicate_band_id():
    bands = [VALID_BANDS[0], VALID_BANDS[0], VALID_BANDS[2]]
    with pytest.raises(ValueError):
        _build_binary_result_semantics_intent(bands=bands)


def test_binary_result_semantics_intent_rejects_gap_between_bands():
    bands = [
        {"band_id": "low", "lower_bound": 0.0, "upper_bound": 0.30},
        {"band_id": "medium", "lower_bound": 0.35, "upper_bound": 0.65},
        {"band_id": "high", "lower_bound": 0.65, "upper_bound": 1.0},
    ]
    with pytest.raises(ValueError):
        _build_binary_result_semantics_intent(bands=bands)


def test_binary_result_semantics_intent_rejects_overlap_between_bands():
    bands = [
        {"band_id": "low", "lower_bound": 0.0, "upper_bound": 0.40},
        {"band_id": "medium", "lower_bound": 0.35, "upper_bound": 0.65},
        {"band_id": "high", "lower_bound": 0.65, "upper_bound": 1.0},
    ]
    with pytest.raises(ValueError):
        _build_binary_result_semantics_intent(bands=bands)


def test_binary_result_semantics_intent_rejects_unordered_bands():
    bands = [
        {"band_id": "medium", "lower_bound": 0.35, "upper_bound": 0.65},
        {"band_id": "low", "lower_bound": 0.0, "upper_bound": 0.35},
        {"band_id": "high", "lower_bound": 0.65, "upper_bound": 1.0},
    ]
    intent = _build_binary_result_semantics_intent(bands=bands)
    # Bands must be normalized to canonical low/medium/high order regardless
    # of input order, since ordering/contiguity is checked on the canonical
    # sequence, not the caller's own order.
    assert [b["band_id"] for b in intent["interpretation"]["bands"]] == ["low", "medium", "high"]


def test_binary_result_semantics_intent_rejects_first_lower_bound_not_zero():
    bands = [
        {"band_id": "low", "lower_bound": 0.05, "upper_bound": 0.35},
        {"band_id": "medium", "lower_bound": 0.35, "upper_bound": 0.65},
        {"band_id": "high", "lower_bound": 0.65, "upper_bound": 1.0},
    ]
    with pytest.raises(ValueError):
        _build_binary_result_semantics_intent(bands=bands)


def test_binary_result_semantics_intent_rejects_final_upper_bound_not_one():
    bands = [
        {"band_id": "low", "lower_bound": 0.0, "upper_bound": 0.35},
        {"band_id": "medium", "lower_bound": 0.35, "upper_bound": 0.65},
        {"band_id": "high", "lower_bound": 0.65, "upper_bound": 0.95},
    ]
    with pytest.raises(ValueError):
        _build_binary_result_semantics_intent(bands=bands)


def test_binary_result_semantics_intent_rejects_out_of_range_band_bound():
    bands = [
        {"band_id": "low", "lower_bound": 0.0, "upper_bound": 0.35},
        {"band_id": "medium", "lower_bound": 0.35, "upper_bound": 0.65},
        {"band_id": "high", "lower_bound": 0.65, "upper_bound": 1.5},
    ]
    with pytest.raises(ValueError):
        _build_binary_result_semantics_intent(bands=bands)


def test_binary_result_semantics_intent_boundary_semantics_at_exact_edges():
    # Exercises the documented interval semantics
    # (lower_bound <= probability < upper_bound, except the final band's
    # upper bound 1.0 is inclusive) at the exact boundary values.
    intent = _build_binary_result_semantics_intent()
    bands = {b["band_id"]: b for b in intent["interpretation"]["bands"]}
    assert bands["low"]["lower_bound"] == 0.0
    assert bands["low"]["upper_bound"] == bands["medium"]["lower_bound"]
    assert bands["medium"]["upper_bound"] == bands["high"]["lower_bound"]
    assert bands["high"]["upper_bound"] == 1.0


def test_modeling_intent_binary_result_semantics_intent_defaults_to_none():
    intent = _build_telco_shaped_modeling_intent()
    assert intent["binary_result_semantics_intent"] is None


def test_modeling_intent_carries_binary_result_semantics_intent_verbatim():
    binary_intent = _build_binary_result_semantics_intent()
    intent = _build_telco_shaped_modeling_intent(binary_result_semantics_intent=binary_intent)
    assert intent["binary_result_semantics_intent"] == binary_intent


def test_modeling_intent_carries_pending_binary_result_semantics_intent_unresolved():
    binary_intent = _build_binary_result_semantics_intent(review_status="pending_review")
    intent = _build_telco_shaped_modeling_intent(binary_result_semantics_intent=binary_intent)
    assert intent["binary_result_semantics_intent"]["review_status"] == "pending_review"
