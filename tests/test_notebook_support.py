"""Shared dataset-integration notebook infrastructure (pipeline/notebook_support.py)
and the guarantee that the four real notebooks use it instead of
copy-pasted helper definitions."""

import ast
import hashlib
import json
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pipeline.discovery_evidence as discovery_evidence  # noqa: E402
from pipeline import notebook_support  # noqa: E402

NOTEBOOK_SLUGS = ["telco-customer-churn", "dry-bean", "concrete-compressive-strength", "nottem"]
EXTRACTED_HELPERS = (
    "record_block",
    "sha256_file",
    "write_governed_json",
    "_durable_ref",
    "durable_ref",
    "resolve_imported_module_repo_root",
    "assert_repository_import_root_coherence",
    "period_label",
)


def _notebook(slug: str) -> dict:
    return json.loads(
        (REPO_ROOT / "notebooks" / "datasets" / slug / "dataset_integration.ipynb").read_text(encoding="utf-8")
    )


def _code(slug: str) -> str:
    return "\n".join("".join(c["source"]) for c in _notebook(slug)["cells"] if c["cell_type"] == "code")


def test_record_block_accumulates_reasons_in_the_shared_run_state(tmp_path):
    workspace = notebook_support.IntegrationWorkspace(tmp_path)
    assert workspace.run_state == {"blocked": False, "reasons": []}
    reason = workspace.record_block("some_code", "some message", "some_field")
    workspace.record_block("other_code", "other message")
    assert reason == {"code": "some_code", "message": "some message", "field": "some_field"}
    assert workspace.run_state["blocked"] is True
    assert workspace.run_state["reasons"][1] == {"code": "other_code", "message": "other message"}


def test_write_governed_json_is_deterministic_and_returns_sha256_ref(tmp_path):
    workspace = notebook_support.IntegrationWorkspace(tmp_path)
    ref = workspace.write_governed_json("a/b/artifact.json", {"z": 1, "a": [2]})
    path = tmp_path / "a" / "b" / "artifact.json"
    assert path.read_text(encoding="utf-8") == json.dumps({"a": [2], "z": 1}, indent=2) + "\n"
    assert ref == {"path": "a/b/artifact.json", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    assert notebook_support.sha256_file(path) == ref["sha256"]


def test_durable_ref(tmp_path):
    workspace = notebook_support.IntegrationWorkspace(tmp_path)
    workspace.write_governed_json("x.json", {})
    assert workspace.durable_ref(None) is None
    assert workspace.durable_ref("x.json") == {
        "path": "x.json",
        "sha256": notebook_support.sha256_file(tmp_path / "x.json"),
    }


def test_import_root_coherence_accepts_this_checkout_and_rejects_another(tmp_path):
    repo_root = discovery_evidence.resolve_repository_root()
    assert notebook_support.assert_repository_import_root_coherence(discovery_evidence, repo_root) == repo_root

    foreign_root = tmp_path / "other-checkout"
    (foreign_root / "pipeline").mkdir(parents=True)
    (foreign_root / "README.md").write_text("", encoding="utf-8")
    (foreign_root / "pipeline" / "discovery_evidence.py").write_text("", encoding="utf-8")
    foreign_module = types.ModuleType("pipeline.discovery_evidence")
    foreign_module.__file__ = str(foreign_root / "pipeline" / "discovery_evidence.py")
    with pytest.raises(RuntimeError, match="import-root coherence check failed"):
        notebook_support.assert_repository_import_root_coherence(foreign_module, repo_root)


@pytest.mark.parametrize("slug", NOTEBOOK_SLUGS)
def test_notebook_uses_shared_helpers_instead_of_local_copies(slug):
    code = _code(slug)
    for helper in EXTRACTED_HELPERS:
        assert f"def {helper}(" not in code, helper
    assert "from pipeline.notebook_support import" in code
    assert "workspace = IntegrationWorkspace(repo_root)" in code
    assert "record_block = workspace.record_block" in code
    assert "write_governed_json = workspace.write_governed_json" in code
    assert "durable_ref = workspace.durable_ref" in code
    # Dataset-specific identity stays in the notebook.
    assert f'dataset_slug = "{slug}"' in code


# Some governed notebooks carry a deliberately committed execution record
# (e.g. "record post-refactor notebook execution artifacts"), so "static" means
# the committed record is safe to read without executing anything -- not that
# every notebook is unexecuted.
_SAFE_OUTPUT_TYPES = {"execute_result", "display_data", "stream"}
_SAFE_OUTPUT_MIME_TYPES = {"text/plain", "text/html"}
_LOCAL_PATH_MARKERS = ("/home/", "/Users/", "/workspace/", "/root/", "C:\\")


@pytest.mark.parametrize("slug", NOTEBOOK_SLUGS)
def test_notebook_is_static(slug):
    for index, cell in enumerate(_notebook(slug)["cells"]):
        if cell["cell_type"] != "code":
            continue
        ast.parse("".join(cell["source"]))
        assert isinstance(cell["outputs"], list), index
        if cell["execution_count"] is None:
            assert cell["outputs"] == [], f"cell {index}: outputs without an execution record"
        for output in cell["outputs"]:
            assert output["output_type"] in _SAFE_OUTPUT_TYPES, f"cell {index}: {output['output_type']}"
            assert set(output.get("data", {})) <= _SAFE_OUTPUT_MIME_TYPES, f"cell {index}: binary output"
            rendered = json.dumps(output)
            assert not any(marker in rendered for marker in _LOCAL_PATH_MARKERS), f"cell {index}: local path"
