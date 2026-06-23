import json
from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent
NOTEBOOK_PATH = REPO_ROOT / "notebooks" / "m22_discovery_entrypoint.ipynb"


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
    assert "dataset_input_path" in source, (
        "Parameters cell must declare dataset_input_path."
    )


def test_notebook_requires_explicit_dataset_input_path():
    nb = _load_notebook()
    source = _all_code_source(nb)
    assert "dataset_input_path" in source, (
        "Notebook must reference dataset_input_path."
    )
    assert "if not dataset_input_path" in source or "raise ValueError" in source, (
        "Notebook must guard against absent or implicit dataset_input_path."
    )


def test_dataset_input_path_default_is_none():
    nb = _load_notebook()
    cells = _parameter_cells(nb)
    assert cells, "Notebook must have a parameters cell."
    param_source = "".join(cells[0]["source"])
    assert "dataset_input_path = None" in param_source, (
        "dataset_input_path default must be None; no hardcoded path allowed."
    )


def test_notebook_records_run_parameters():
    nb = _load_notebook()
    source = _all_code_source(nb)
    assert "run_parameters" in source, (
        "Notebook must record run_parameters."
    )


def test_notebook_records_output_locations():
    nb = _load_notebook()
    source = _all_code_source(nb)
    assert "output_locations" in source, (
        "Notebook must record output_locations."
    )


def test_notebook_declares_forbidden_side_effects():
    nb = _load_notebook()
    source = _all_code_source(nb)
    assert "FORBIDDEN_SIDE_EFFECTS" in source, (
        "Notebook must declare FORBIDDEN_SIDE_EFFECTS boundary."
    )
    assert "model_training" in source, (
        "Notebook must declare model_training as a forbidden side effect."
    )
    assert "release_publication" in source, (
        "Notebook must declare release_publication as a forbidden side effect."
    )
    assert "public_runtime_mutation" in source, (
        "Notebook must declare public_runtime_mutation as a forbidden side effect."
    )


def test_notebook_declares_output_is_not_final_truth():
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
