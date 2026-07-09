import json
from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent
NOTEBOOK_PATH = REPO_ROOT / "notebooks" / "datasets" / "telco-customer-churn" / "01_dataset_authoring.ipynb"


def _load_notebook() -> dict:
    return json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))


def _all_code_source(nb: dict) -> str:
    return "\n".join(
        "".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"
    )


def _all_source(nb: dict) -> str:
    return "\n".join("".join(c["source"]) for c in nb["cells"])


def _parameter_cells(nb: dict) -> list:
    return [
        c for c in nb["cells"]
        if "parameters" in c.get("metadata", {}).get("tags", [])
    ]


def test_notebook_exists():
    assert NOTEBOOK_PATH.exists(), f"Notebook not found: {NOTEBOOK_PATH}"


def test_notebook_is_valid_json():
    nb = _load_notebook()
    assert isinstance(nb, dict)
    assert "cells" in nb
    assert "nbformat" in nb


def test_notebook_has_parameters_cell():
    nb = _load_notebook()
    cells = _parameter_cells(nb)
    assert cells, "Notebook must have a cell tagged 'parameters'."
    source = "".join(cells[0]["source"])
    assert "dataset_relative_path" in source, (
        "Parameters cell must declare dataset_relative_path."
    )


def test_notebook_requires_explicit_repository_relative_dataset_path():
    nb = _load_notebook()
    source = _all_code_source(nb)
    assert "dataset_relative_path" in source, (
        "Notebook must reference dataset_relative_path."
    )
    assert "raise FileNotFoundError" in source, (
        "Notebook must guard against a missing dataset file."
    )


def test_dataset_relative_path_default_is_repository_relative():
    nb = _load_notebook()
    cells = _parameter_cells(nb)
    assert cells, "Notebook must have a parameters cell."
    param_source = "".join(cells[0]["source"])
    assert "dataset_relative_path = \"data/raw/telco-customer-churn.csv\"" in param_source, (
        "dataset_relative_path default must be the repository-relative Telco CSV path."
    )
    assert "repo_root = None" in param_source, (
        "repo_root default must be None; an explicit override, not a hardcoded absolute path."
    )


def test_notebook_resolves_dataset_path_from_repository_root_not_notebook_directory():
    nb = _load_notebook()
    source = _all_code_source(nb)
    assert "repo_root" in source and "dataset_relative_path" in source, (
        "Notebook must combine an explicit or default repo_root with the "
        "repository-relative dataset path."
    )
    assert "__file__" not in source, (
        "Notebook must not derive its dataset path from its own nested "
        "notebook file location."
    )
    assert "../" not in source, (
        "Notebook must not rely on fragile relative traversal tied to its "
        "old, less-nested location."
    )


def test_notebook_calls_reusable_helper_behavior():
    nb = _load_notebook()
    source = _all_code_source(nb)
    assert "from pipeline.discovery_evidence import" in source, (
        "Notebook must call the reusable helper behavior from "
        "pipeline/discovery_evidence.py instead of duplicating common "
        "loading and inspection logic inline."
    )
    for helper in [
        "resolve_repository_path",
        "load_dataset_csv",
        "summarize_structure",
        "observe_authoring_fields",
        "summarize_target_column",
        "summarize_identifier_columns",
        "derive_feature_candidates",
        "authoring_helper_evidence_policy",
    ]:
        assert helper in source, f"Notebook must call helper: {helper}"


def test_notebook_records_authoring_observations():
    nb = _load_notebook()
    source = _all_code_source(nb)
    assert "authoring_observations" in source, (
        "Notebook must record authoring_observations."
    )


def test_notebook_declares_forbidden_side_effects():
    nb = _load_notebook()
    source = _all_code_source(nb)
    assert "FORBIDDEN_SIDE_EFFECTS" in source, (
        "Notebook must declare FORBIDDEN_SIDE_EFFECTS boundary."
    )
    for forbidden in [
        "model_training",
        "release_candidate_creation",
        "release_promotion",
        "registry_state_mutation",
        "api_behavior_change",
        "ui_behavior_change",
    ]:
        assert forbidden in source, (
            f"Notebook must declare '{forbidden}' as a forbidden side effect."
        )


def test_notebook_declares_output_is_not_final_operational_truth():
    nb = _load_notebook()
    source = _all_source(nb)
    assert "not_final_operational_truth" in source or "not the final" in source, (
        "Notebook must declare that its output is not the final operational source of truth."
    )


def test_notebook_does_not_depend_on_public_services():
    nb = _load_notebook()
    source = _all_code_source(nb)
    forbidden_imports = ["requests", "urllib.request", "boto3", "google.cloud", "azure"]
    for imp in forbidden_imports:
        assert imp not in source, (
            f"Notebook must not import public service client '{imp}'; "
            "the entrypoint must run locally without public services."
        )


def test_old_root_level_notebook_path_is_not_the_active_path():
    old_path = REPO_ROOT / "notebooks" / "m22_discovery_entrypoint.ipynb"
    assert not old_path.exists(), (
        "The old root-level notebook path must not be required as the "
        "active notebook path for this spec."
    )
