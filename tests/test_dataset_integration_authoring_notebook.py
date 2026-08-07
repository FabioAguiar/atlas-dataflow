import ast
import json
from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent
NOTEBOOK_PATH = (
    REPO_ROOT
    / "notebooks/datasets/telco-customer-churn/01_dataset_integration_authoring.ipynb"
)


def _notebook() -> dict:
    return json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))


def _source(cell_type: str | None = None) -> str:
    return "\n".join(
        "".join(cell["source"])
        for cell in _notebook()["cells"]
        if cell_type is None or cell["cell_type"] == cell_type
    )


def _called_names() -> set[str]:
    names: set[str] = set()
    for cell in _notebook()["cells"]:
        if cell["cell_type"] != "code":
            continue
        tree = ast.parse("".join(cell["source"]))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                names.add(node.func.attr)
    return names


def test_notebook_has_the_twelve_authoring_stages_in_order():
    markdown = _source("markdown")
    stages = [
        "1. Authoring context and boundary declaration",
        "2. Dataset/source input identity",
        "3. Atlas-owned source verification and drift checks",
        "4. Structured external scientific-evidence discovery",
        "5. Evidence integrity/provenance verification",
        "6. Dataset-specific semantic interpretation",
        "7. Capability-profile selection/declaration",
        "8. Deterministic preparation/input policy",
        "9. S0166 authoring artifact materialization",
        "10. Cross-artifact authoring validation",
        "11. S0167 capability-aware source/projection handoff",
        "12. Authoring completion summary",
    ]
    offsets = [markdown.index(stage) for stage in stages]
    assert offsets == sorted(offsets)


def test_notebook_separates_atlas_observation_from_external_conclusions():
    source = _source()
    assert "what Atlas sees" in source
    assert "not imported scientific conclusions" in source
    assert "external_scientific_analysis_root = None  # session input only" in source
    assert "external_analysis_is_not_reexecuted" in source


def test_external_evidence_is_hash_verified_and_only_reduced_provenance_is_durable():
    code = _source("code")
    assert "safe_external_relative_path" in code
    assert "sha256_file(external_root / relative_path)" in code
    assert '"relative_path": relative_path' in code
    assert '"producer_revision_known"' in code
    assert '"absolute_external_project_root_present": False' in code
    manifest_source = code[code.index("manifest = {"):code.index("manifest_ref =")]
    assert "external_scientific_analysis_root" not in manifest_source
    assert '"external_root"' not in manifest_source


def test_notebook_materializes_and_validates_s0166_contracts():
    code = _source("code")
    assert '"dataset-semantic-intent.v1"' in code
    assert '"dataset-integration-authoring-manifest.v1"' in code
    assert '"binary-predictive-classification"' in code
    assert '"current_supported"' in code
    assert "write_governed_json" in code
    assert "validate_authoring_contracts" in code


def test_notebook_constructs_the_s0167_capability_aware_boundary():
    code = _source("code")
    for field in (
        "authoring_generation_id",
        "authoring_manifest_ref",
        "capability_profile_id",
        "capability_profile_version",
        "capability_profile_ref",
    ):
        assert field in code
    assert "project_capability_aware_source_contract" in code


def test_notebook_has_no_active_modeling_or_runtime_calls():
    calls = _called_names()
    forbidden = {
        "fit", "fit_transform", "cross_validate", "cross_val_score", "GridSearchCV",
        "RandomizedSearchCV", "load_model", "predict", "predict_proba",
        "score", "classification_report", "confusion_matrix",
    }
    assert calls.isdisjoint(forbidden), calls & forbidden
    code = _source("code")
    assert "pickle" not in code
    assert "joblib" not in code


def test_notebook_has_no_candidate_publisher_or_activation_calls():
    calls = _called_names()
    forbidden = {
        "assemble_candidate", "prepare_candidate", "promote", "publish", "activate_release",
        "write_registry", "update_registry", "generate_release_manifest",
    }
    assert calls.isdisjoint(forbidden), calls & forbidden


def test_notebook_tests_are_static_and_need_no_external_files_or_model_bytes():
    notebook = _notebook()
    assert all(cell.get("execution_count") is None for cell in notebook["cells"] if cell["cell_type"] == "code")
    assert all(cell.get("outputs") == [] for cell in notebook["cells"] if cell["cell_type"] == "code")
