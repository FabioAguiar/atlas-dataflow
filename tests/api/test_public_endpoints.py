"""
Public endpoint tests for M3-04.

Exercises the public API response shape for dataset listing and single-dataset
metadata. Tests use direct function calls (registry/list.py and registry/resolve.py)
because httpx is not a declared dependency. Tests confirm safe-field projection,
predictable error codes, and the absence of internal fields in responses.

Run from the repository root:
    python -m pytest tests/api/test_public_endpoints.py -v
or directly:
    python tests/api/test_public_endpoints.py
"""

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).parent.parent.parent
API_ROOT = REPO_ROOT / "api"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(API_ROOT))

import main as api_main  # noqa: E402
from registry.list import ListedDataset, list_datasets  # noqa: E402
from registry.resolve import (  # noqa: E402
    DatasetUnavailableError,
    RegistryInvalidError,
    ReleaseUnavailableError,
    resolve_dataset,
)

_VALID_ENTRY = {
    "dataset_slug": "example-dataset",
    "active_release": "release-20260616-001",
    "public_metadata": {
        "title": "Example Dataset",
        "summary": "Fixture for public endpoint tests.",
        "domain": "example",
        "visibility": "public",
        "tags": ["example", "fixture"],
    },
}

_BASE_REGISTRY = {
    "schema_version": "atlas.dataflow.registry.v1",
    "conventions": {
        "dataset_slug": {"pattern": "x", "description": "x"},
        "release_id": {"pattern": "x", "description": "x"},
        "active_release": {"description": "x"},
    },
    "datasets": [_VALID_ENTRY],
}


def _write_registry(tmp_dir: Path, content: dict) -> Path:
    path = tmp_dir / "datasets.json"
    path.write_text(json.dumps(content), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# list_datasets: safe field projection
# ---------------------------------------------------------------------------

def test_list_datasets_returns_list():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), _BASE_REGISTRY)
        result = list_datasets(registry_path=path)
        assert isinstance(result, list)
        assert len(result) == 1


def test_list_datasets_returns_named_tuples():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), _BASE_REGISTRY)
        result = list_datasets(registry_path=path)
        assert all(isinstance(d, ListedDataset) for d in result)


def test_list_datasets_safe_fields_present():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), _BASE_REGISTRY)
        result = list_datasets(registry_path=path)
        d = result[0]
        assert d.dataset_slug == "example-dataset"
        assert d.title == "Example Dataset"
        assert d.summary == "Fixture for public endpoint tests."
        assert d.domain == "example"
        assert d.visibility == "public"
        assert d.tags == ["example", "fixture"]


def test_list_datasets_no_active_release_in_result():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), _BASE_REGISTRY)
        result = list_datasets(registry_path=path)
        as_dict = result[0]._asdict()
        assert "active_release" not in as_dict


def test_list_datasets_no_conventions_in_result():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), _BASE_REGISTRY)
        result = list_datasets(registry_path=path)
        as_dict = result[0]._asdict()
        assert "conventions" not in as_dict
        assert "$schema" not in as_dict
        assert "schema_version" not in as_dict


def test_list_datasets_asdict_safe_fields_only():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), _BASE_REGISTRY)
        result = list_datasets(registry_path=path)
        as_dict = result[0]._asdict()
        assert set(as_dict.keys()) == {
            "dataset_slug", "title", "summary", "domain", "visibility", "tags"
        }


# ---------------------------------------------------------------------------
# list_datasets: registry unavailable
# ---------------------------------------------------------------------------

def test_list_datasets_raises_registry_invalid_on_bad_registry():
    invalid = {**_BASE_REGISTRY, "schema_version": "bad-version"}
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), invalid)
        raised = False
        try:
            list_datasets(registry_path=path)
        except RegistryInvalidError:
            raised = True
        assert raised, "Expected RegistryInvalidError for invalid registry"


def test_list_datasets_raises_registry_invalid_on_missing_file():
    path = Path("/nonexistent/path/datasets.json")
    raised = False
    try:
        list_datasets(registry_path=path)
    except RegistryInvalidError:
        raised = True
    assert raised, "Expected RegistryInvalidError for missing registry file"


# ---------------------------------------------------------------------------
# resolve_dataset: used by single-dataset endpoint
# ---------------------------------------------------------------------------

def test_resolve_dataset_confirms_slug_exists():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), _BASE_REGISTRY)
        resolved = resolve_dataset("example-dataset", registry_path=path)
        assert resolved.dataset_slug == "example-dataset"


def test_resolve_dataset_unknown_slug_raises_dataset_unavailable():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), _BASE_REGISTRY)
        raised = False
        try:
            resolve_dataset("unknown-slug", registry_path=path)
        except DatasetUnavailableError:
            raised = True
        assert raised, "Expected DatasetUnavailableError for unknown slug"


def test_resolve_dataset_does_not_return_active_release_in_public_flow():
    """
    After resolve_dataset confirms the slug, list_datasets extracts safe fields.
    Confirm no active_release appears in the projected fields.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), _BASE_REGISTRY)
        resolve_dataset("example-dataset", registry_path=path)
        all_listed = list_datasets(registry_path=path)
        for listed in all_listed:
            if listed.dataset_slug == "example-dataset":
                as_dict = listed._asdict()
                assert "active_release" not in as_dict
                return
        assert False, "example-dataset not found in list_datasets result"


# ---------------------------------------------------------------------------
# Combined: single-dataset safe field projection via resolve + list
# ---------------------------------------------------------------------------

def test_single_dataset_response_safe_fields_only():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), _BASE_REGISTRY)
        resolve_dataset("example-dataset", registry_path=path)
        all_listed = list_datasets(registry_path=path)
        matched = next((d for d in all_listed if d.dataset_slug == "example-dataset"), None)
        assert matched is not None
        response = matched._asdict()
        assert set(response.keys()) == {
            "dataset_slug", "title", "summary", "domain", "visibility", "tags"
        }
        assert "active_release" not in response
        assert "conventions" not in response
        assert "$schema" not in response


def test_listing_response_datasets_key():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), _BASE_REGISTRY)
        datasets = list_datasets(registry_path=path)
        response = {"datasets": [d._asdict() for d in datasets]}
        assert "datasets" in response
        assert isinstance(response["datasets"], list)
        assert len(response["datasets"]) == 1


def test_listing_each_item_safe_fields_only():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), _BASE_REGISTRY)
        datasets = list_datasets(registry_path=path)
        for item in [d._asdict() for d in datasets]:
            assert set(item.keys()) == {
                "dataset_slug", "title", "summary", "domain", "visibility", "tags"
            }
            assert "active_release" not in item
            assert "conventions" not in item
            assert "$schema" not in item


# ---------------------------------------------------------------------------
# Context endpoint: safe public runtime projection
# ---------------------------------------------------------------------------

def _response_json(response):
    return json.loads(response.body.decode("utf-8"))


def test_context_endpoint_returns_public_context_response():
    original_resolve_dataset = api_main.resolve_dataset
    original_load_public_context = api_main.load_public_context
    context = {
        "schema_version": "public-context.v1",
        "dataset_slug": "example-dataset",
        "release_id": "release-20260616-001",
        "title": "Example Dataset",
        "summary": "Fixture for public context endpoint tests.",
        "domain": "example",
        "problem_type": "classification",
        "prediction_target_description": "Example target.",
        "use_case": "Example use case.",
        "visibility": "public",
        "tags": ["example", "fixture"],
    }
    try:
        api_main.resolve_dataset = lambda dataset_slug: SimpleNamespace(
            dataset_slug=dataset_slug,
            active_release="release-20260616-001",
        )
        api_main.load_public_context = lambda active_release: context
        response = api_main.get_public_context("example-dataset")
        assert response == {
            "dataset_slug": "example-dataset",
            "context": context,
        }
        assert "run_id" not in response["context"]
        assert "raw_metrics" not in response["context"]
        assert all(not key.startswith("_") for key in response["context"])
    finally:
        api_main.resolve_dataset = original_resolve_dataset
        api_main.load_public_context = original_load_public_context


def test_context_endpoint_unknown_dataset_returns_dataset_not_found():
    original_resolve_dataset = api_main.resolve_dataset
    try:
        def raise_dataset_unavailable(_dataset_slug):
            raise DatasetUnavailableError("missing")

        api_main.resolve_dataset = raise_dataset_unavailable
        response = api_main.get_public_context("unknown-slug")
        assert response.status_code == 404
        assert _response_json(response)["error_code"] == "DATASET_NOT_FOUND"
    finally:
        api_main.resolve_dataset = original_resolve_dataset


def test_context_endpoint_release_unavailable_returns_release_unavailable():
    original_resolve_dataset = api_main.resolve_dataset
    try:
        def raise_release_unavailable(_dataset_slug):
            raise ReleaseUnavailableError("missing release")

        api_main.resolve_dataset = raise_release_unavailable
        response = api_main.get_public_context("example-dataset")
        assert response.status_code == 503
        assert _response_json(response)["error_code"] == "RELEASE_UNAVAILABLE"
    finally:
        api_main.resolve_dataset = original_resolve_dataset


def test_context_endpoint_context_unavailable_returns_context_unavailable():
    original_resolve_dataset = api_main.resolve_dataset
    original_load_public_context = api_main.load_public_context
    try:
        api_main.resolve_dataset = lambda dataset_slug: SimpleNamespace(
            dataset_slug=dataset_slug,
            active_release="release-20260616-001",
        )

        def raise_context_unavailable(_active_release):
            raise api_main.PublicContextUnavailableError("missing context")

        api_main.load_public_context = raise_context_unavailable
        response = api_main.get_public_context("example-dataset")
        assert response.status_code == 503
        payload = _response_json(response)
        assert payload["error_type"] == "context_unavailable"
        assert payload["error_code"] == "CONTEXT_UNAVAILABLE"
    finally:
        api_main.resolve_dataset = original_resolve_dataset
        api_main.load_public_context = original_load_public_context


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_list_datasets_returns_list,
        test_list_datasets_returns_named_tuples,
        test_list_datasets_safe_fields_present,
        test_list_datasets_no_active_release_in_result,
        test_list_datasets_no_conventions_in_result,
        test_list_datasets_asdict_safe_fields_only,
        test_list_datasets_raises_registry_invalid_on_bad_registry,
        test_list_datasets_raises_registry_invalid_on_missing_file,
        test_resolve_dataset_confirms_slug_exists,
        test_resolve_dataset_unknown_slug_raises_dataset_unavailable,
        test_resolve_dataset_does_not_return_active_release_in_public_flow,
        test_single_dataset_response_safe_fields_only,
        test_listing_response_datasets_key,
        test_listing_each_item_safe_fields_only,
        test_context_endpoint_returns_public_context_response,
        test_context_endpoint_unknown_dataset_returns_dataset_not_found,
        test_context_endpoint_release_unavailable_returns_release_unavailable,
        test_context_endpoint_context_unavailable_returns_context_unavailable,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except Exception as exc:
            print(f"FAIL  {t.__name__}: {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
