"""Dataset-integration notebook entrypoint convention.

Every registered dataset owns exactly one integration notebook at the
conventional path ``notebooks/datasets/<dataset_slug>/dataset_integration.ipynb``.
No single dataset's notebook is a globally canonical entrypoint: the generic
discovery module receives ``authoring_notebook_ref`` from its caller and never
declares a dataset-specific notebook itself.
"""

import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pipeline.discovery_evidence as discovery_evidence  # noqa: E402


NOTEBOOK_RELATIVE_TEMPLATE = "notebooks/datasets/{dataset_slug}/dataset_integration.ipynb"
_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _registered_dataset_slugs() -> list[str]:
    registry = json.loads((REPO_ROOT / "registry" / "datasets.json").read_text(encoding="utf-8"))
    return sorted(entry["dataset_slug"] for entry in registry["datasets"])


REGISTERED_DATASET_SLUGS = _registered_dataset_slugs()


def _notebook_path(dataset_slug: str) -> Path:
    return REPO_ROOT / NOTEBOOK_RELATIVE_TEMPLATE.format(dataset_slug=dataset_slug)


def _source(dataset_slug: str, cell_type: str | None = None) -> str:
    notebook = json.loads(_notebook_path(dataset_slug).read_text(encoding="utf-8"))
    return "\n".join(
        "".join(cell["source"])
        for cell in notebook["cells"]
        if cell_type is None or cell["cell_type"] == cell_type
    )


def test_registry_is_not_empty():
    assert REGISTERED_DATASET_SLUGS


def test_generic_discovery_module_declares_no_canonical_dataset_notebook():
    assert not hasattr(discovery_evidence, "CANONICAL_DATASET_INTEGRATION_AUTHORING_NOTEBOOK")
    assert not hasattr(discovery_evidence, "canonical_dataset_integration_authoring_notebook_ref")
    module_source = Path(discovery_evidence.__file__).read_text(encoding="utf-8")
    for dataset_slug in REGISTERED_DATASET_SLUGS:
        assert f"notebooks/datasets/{dataset_slug}/" not in module_source


@pytest.mark.parametrize("dataset_slug", REGISTERED_DATASET_SLUGS)
def test_registered_dataset_has_conventional_integration_notebook(dataset_slug):
    assert _SLUG_PATTERN.fullmatch(dataset_slug)
    notebook_path = _notebook_path(dataset_slug)
    assert notebook_path.is_file()
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    assert notebook["nbformat"] == 4
    assert notebook["cells"]
    # One integration entrypoint per dataset -- no parallel historical
    # notebook competes with the conventional one.
    assert sorted(path.name for path in notebook_path.parent.glob("*.ipynb")) == [
        "dataset_integration.ipynb"
    ]


@pytest.mark.parametrize("dataset_slug", REGISTERED_DATASET_SLUGS)
def test_entrypoint_uses_atlas_discovery_helpers(dataset_slug):
    code = _source(dataset_slug, "code")
    for helper in (
        "load_dataset_csv",
        "resolve_repository_path",
        "summarize_structure",
        "summarize_target_column",
    ):
        assert helper in code


@pytest.mark.parametrize("dataset_slug", REGISTERED_DATASET_SLUGS)
def test_entrypoint_declares_orchestration_boundary(dataset_slug):
    source = _source(dataset_slug)
    assert "ORCHESTRATION_BOUNDARY" in source
    assert "publisher_promotion" in source
    assert "registry_active_release_mutation" in source


@pytest.mark.parametrize("dataset_slug", REGISTERED_DATASET_SLUGS)
def test_entrypoint_does_not_use_cwd_as_repository_root(dataset_slug):
    code = _source(dataset_slug, "code")
    assert "Path.cwd()" not in code
    assert "repo_root = resolve_repository_root()" in code


@pytest.mark.parametrize("dataset_slug", REGISTERED_DATASET_SLUGS)
def test_entrypoint_has_no_public_service_dependency(dataset_slug):
    code = _source(dataset_slug, "code")
    for dependency in ("requests", "urllib.request", "boto3", "google.cloud", "azure"):
        assert dependency not in code
