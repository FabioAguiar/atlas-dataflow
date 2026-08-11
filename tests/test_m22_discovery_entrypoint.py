import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.discovery_evidence import (
    CANONICAL_DATASET_INTEGRATION_AUTHORING_NOTEBOOK,
    canonical_dataset_integration_authoring_notebook_ref,
)


NOTEBOOK_PATH = REPO_ROOT / CANONICAL_DATASET_INTEGRATION_AUTHORING_NOTEBOOK
HISTORICAL_NOTEBOOK_PATH = (
    REPO_ROOT
    / "notebooks/datasets/telco-customer-churn/01_dataset_authoring.ipynb"
)


def _load_notebook() -> dict:
    return json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))


def _source(cell_type: str | None = None) -> str:
    notebook = _load_notebook()
    return "\n".join(
        "".join(cell["source"])
        for cell in notebook["cells"]
        if cell_type is None or cell["cell_type"] == cell_type
    )


def test_canonical_discovery_entrypoint_exists_and_is_valid_notebook():
    assert canonical_dataset_integration_authoring_notebook_ref() == (
        "notebooks/datasets/telco-customer-churn/"
        "dataset_integration.ipynb"
    )
    assert NOTEBOOK_PATH.is_file()
    notebook = _load_notebook()
    assert notebook["nbformat"] == 4
    assert notebook["cells"]


def test_historical_notebook_remains_available_but_is_not_canonical():
    assert HISTORICAL_NOTEBOOK_PATH.is_file()
    assert NOTEBOOK_PATH != HISTORICAL_NOTEBOOK_PATH


def test_entrypoint_uses_atlas_discovery_helpers_for_current_source():
    code = _source("code")
    for helper in (
        "load_dataset_csv",
        "observe_authoring_fields",
        "resolve_repository_path",
        "summarize_structure",
        "summarize_target_column",
        "summarize_identifier_columns",
    ):
        assert helper in code
    assert 'dataset_relative_path = "data/raw/telco-customer-churn.csv"' in code


def test_entrypoint_declares_extended_orchestration_boundary():
    source = _source()
    assert "ORCHESTRATION_BOUNDARY" in source
    assert "external_evidence_is_authoring_time_only" in source
    assert "stops_before_promotion_registry_activation_and_runtime_prediction" in source
    assert "external_fitted_model_governed_materialization" in source
    assert "publisher_promotion" in source and "registry_active_release_mutation" in source


def test_entrypoint_does_not_use_cwd_as_repository_root():
    code = _source("code")
    assert "Path.cwd()" not in code
    assert "repo_root = resolve_repository_root()" in code


def test_entrypoint_has_no_public_service_dependency():
    code = _source("code")
    for dependency in ("requests", "urllib.request", "boto3", "google.cloud", "azure"):
        assert dependency not in code
