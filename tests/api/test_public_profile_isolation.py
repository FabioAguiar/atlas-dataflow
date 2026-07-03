"""
Public profile isolation tests for M36-02.

Proves that saving a private draft profile (via
registry/dataset_public_profile_store.create_draft) never appears in any
public GET route response in api/main.py. The existing route-registration
test (tests/api/test_admin_profile_drafts.py::
test_profile_draft_route_registered_only_under_admin_and_public_datasets_unchanged)
only confirms the admin route path is registered and that public route
paths are unchanged; it does not call any public route handler or inspect
response payload content. This module closes that gap end-to-end.

The isolated draft is persisted through
registry/dataset_public_profile_store.create_draft's repo_root parameter
pointed at a temporary directory carrying only a copy of the real
contracts/dataset-public-profile.schema.json -- the same minimal isolation
convention tests/api/test_admin_profile_drafts.py uses -- so no test writes
into the real registry/profile-drafts/ directory. The public route handlers
in api/main.py are called directly (no HTTP client, matching this
repository's existing tests/api/ convention) against the real
registry/releases data, since none of them read repo_root for drafts.

Run from the repository root:
    python -m pytest tests/api/test_public_profile_isolation.py -v
or directly:
    python tests/api/test_public_profile_isolation.py
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
API_ROOT = REPO_ROOT / "api"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(API_ROOT))

import main as api_main  # noqa: E402
from registry.dataset_public_profile_store import create_draft, get_draft  # noqa: E402

_MARKER = "PRIVATE-DRAFT-MARKER-should-never-appear-publicly-9f3a1c"

_SEEDED_DATASET_SLUGS = ["telco-customer-churn", "bank-marketing"]


def _build_fake_repo(tmp_root: Path) -> Path:
    """Build a fake repo root carrying only the real profile schema.

    Mirrors tests/api/test_admin_profile_drafts.py's _build_fake_repo: no
    registry/predict-views.json or registry/datasets.json is needed since
    the draft below never sets inference_presentation.bound_predict_view_id
    or home_card.primary_metric_key, so no reference check is exercised.
    """
    schema_src = REPO_ROOT / "contracts" / "dataset-public-profile.schema.json"
    contracts_dir = tmp_root / "contracts"
    contracts_dir.mkdir(parents=True)
    shutil.copy2(schema_src, contracts_dir / "dataset-public-profile.schema.json")
    return tmp_root


def _draft_profile(dataset_slug: str) -> dict:
    return {
        "schema_version": "1.0.0",
        "dataset_slug": dataset_slug,
        "display": {"title": _MARKER},
    }


def _serialize(response) -> str:
    """Serialize either a plain dict (success) or a Response object (error)."""
    if isinstance(response, dict):
        return json.dumps(response, sort_keys=True)
    return response.body.decode("utf-8")


def _assert_marker_absent(response, route_label: str) -> None:
    serialized = _serialize(response)
    assert _MARKER not in serialized, (
        f"Private draft marker leaked into public route response: {route_label}"
    )


def test_saved_draft_never_appears_in_any_public_route_response():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(Path(tmp))

        for dataset_slug in _SEEDED_DATASET_SLUGS:
            create_result = create_draft(
                dataset_slug, _draft_profile(dataset_slug), repo_root=fake_repo
            )
            assert create_result["created"] is True, create_result["errors"]

            # Control: prove the draft was actually persisted with the
            # marker, so the isolation assertions below are not vacuously
            # true because the draft was never really saved.
            persisted = get_draft(dataset_slug, repo_root=fake_repo)
            assert persisted["display"]["title"] == _MARKER

            _assert_marker_absent(
                api_main.list_datasets_endpoint(), "GET /datasets"
            )
            _assert_marker_absent(
                api_main.get_dataset(dataset_slug),
                f"GET /datasets/{dataset_slug}",
            )
            _assert_marker_absent(
                api_main.get_public_contract(dataset_slug),
                f"GET /datasets/{dataset_slug}/contract",
            )
            _assert_marker_absent(
                api_main.get_public_metrics(dataset_slug),
                f"GET /datasets/{dataset_slug}/metrics",
            )
            _assert_marker_absent(
                api_main.get_public_context(dataset_slug),
                f"GET /datasets/{dataset_slug}/context",
            )
            _assert_marker_absent(
                api_main.get_public_model_card(dataset_slug),
                f"GET /datasets/{dataset_slug}/model-card",
            )
            _assert_marker_absent(
                api_main.get_public_visualizations(dataset_slug),
                f"GET /datasets/{dataset_slug}/visualizations",
            )


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
