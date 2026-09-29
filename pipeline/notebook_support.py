"""Shared infrastructure for dataset-integration notebooks.

Every ``notebooks/datasets/<dataset_slug>/dataset_integration.ipynb`` needs the
same small, dataset-agnostic plumbing: a blocking-reason run state, governed
JSON artifact writing with sha256 references, durable repo-relative
references, and a repository/import-root coherence check. It lives here so a
notebook stays dataset narrative + dataset-specific scientific decisions +
calls to generic pipeline capabilities, instead of copy-pasted infrastructure.

Nothing here knows any dataset: callers pass their own repository root,
relative paths, and payloads.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import ModuleType
from typing import Any

from pipeline.discovery_evidence import resolve_repository_root

_HASH_CHUNK_BYTES = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_imported_module_repo_root(module: ModuleType) -> Path:
    return resolve_repository_root(module.__file__)


def assert_repository_import_root_coherence(module: ModuleType, expected_repo_root: Path) -> Path:
    """Fail loudly when an imported Atlas module belongs to a different
    checkout than the notebook's repository root (typically a stray
    non-editable install of the ``pipeline`` package)."""
    imported_repo_root = resolve_imported_module_repo_root(module)
    if imported_repo_root != expected_repo_root:
        raise RuntimeError(
            "Atlas repository/import-root coherence check failed: this notebook "
            f"resolved repo_root={expected_repo_root}, but the imported "
            f"'{module.__name__}' module belongs to a different Atlas checkout "
            f"({imported_repo_root}). This usually means the active Python "
            "environment has a separate, non-editable install of the "
            "'pipeline' package (for example via `pip install .` instead of "
            "`pip install -e .`) shadowing this checkout. Fix the kernel's "
            "environment (reinstall in editable mode against this checkout, "
            "or remove the stray install) and restart the Jupyter kernel "
            "before re-running this notebook."
        )
    return imported_repo_root


class IntegrationWorkspace:
    """Run state and governed artifact writing for one notebook run.

    ``run_state`` is the shared ``{"blocked": bool, "reasons": [...]}`` object
    every stage consults; ``record_block`` appends a blocking reason to it.
    """

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = Path(repo_root)
        self.run_state: dict[str, Any] = {"blocked": False, "reasons": []}

    def record_block(self, code_: str, message: str, field: str | None = None) -> dict[str, str]:
        reason = {"code": code_, "message": message}
        if field is not None:
            reason["field"] = field
        self.run_state["blocked"] = True
        self.run_state["reasons"].append(reason)
        return reason

    def write_governed_json(self, relative_path: str, payload: Any) -> dict[str, str]:
        """Write a deterministic (sorted-key, indented) JSON artifact under the
        repository root and return its governed ``{"path", "sha256"}`` ref."""
        path = self.repo_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {"path": relative_path, "sha256": sha256_file(path)}

    def durable_ref(self, relative_path: str | None) -> dict[str, str] | None:
        """``{"path", "sha256"}`` for an existing repo-relative artifact, or
        None when no artifact was produced."""
        if relative_path is None:
            return None
        return {"path": relative_path, "sha256": sha256_file(self.repo_root / relative_path)}
