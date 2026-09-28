"""Scientific Study Contract loading, capability assessment, and source verification.

A scientific study contract (``scientific-study-contract.v1``) pins one
revision of an external Dataset Study: its commit, the hashes of the files the
protocol and reference evidence were read from, the dataset identity, the
scientific environment, the declarative protocol, and the evidence the study
published at that revision. Contracts live under
``pipeline/scientific-studies/<dataset-slug>/<study-revision-label>/`` and are
immutable: a changed study revision gets a new directory.

This module never executes a protocol. It answers three questions:

* is the contract structurally valid (JSON Schema)?
* which protocol elements can Atlas execute (``assess_protocol_support``)?
* does a study checkout still match what the contract pins
  (``verify_against_study_checkout``)?
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from pipeline import model_families


SCHEMA_VERSION = "scientific-study-contract.v1"
CONTRACT_FILENAME = "scientific-study-contract.json"
SCHEMA_PATH = Path(__file__).resolve().parent / "scientific-study-contract.schema.json"
STUDIES_ROOT_RELATIVE = "pipeline/scientific-studies"

# Protocol vocabulary the reproduction engine implements. A contract element
# outside this vocabulary is an Atlas capability gap, never silently skipped.
REPRODUCTION_CAPABILITIES: Mapping[str, Any] = {
    "problem_types": {"binary_classification"},
    "protocol_kinds": {"tabular_holdout_model_selection.v1"},
    "preparation_rule_kinds": {"conditional_blank_numeric_fill"},
    "split_kinds": {"two_stage_stratified_holdout"},
    "preprocessing_kinds": {"column_transformer_onehot_plus_numeric"},
    "cross_validation_kinds": {"stratified_k_fold"},
    "search_kinds": {"grid", "randomized", "none"},
    "selection_kinds": {"leader_anchored_practical_tie"},
    "threshold_policy_kinds": {"max_precision_subject_to_min_recall"},
    "final_evaluation_kinds": {"refit_on_train_plus_validation_single_test_evaluation"},
    "metrics": {
        "average_precision", "roc_auc", "precision", "recall", "f1", "f2",
        "balanced_accuracy", "accuracy", "log_loss", "brier_score",
    },
    "tie_breaker_fields": {
        "validation_brier_score", "validation_log_loss", "validation_roc_auc",
        "validation_average_precision", "cv_average_precision_std", "simplicity_rank", "model_id",
    },
}


class ScientificStudyContractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ScientificStudyContract:
    payload: Mapping[str, Any]
    relative_path: str
    sha256: str

    @property
    def dataset_slug(self) -> str:
        return self.payload["study_identity"]["dataset_slug"]

    @property
    def study_revision(self) -> str:
        return self.payload["source_repository"]["revision"]

    def reference(self) -> dict[str, Any]:
        return {
            "path": self.relative_path,
            "sha256": self.sha256,
            "schema_version": self.payload["schema_version"],
            "study_id": self.payload["study_identity"]["study_id"],
            "study_revision": self.study_revision,
            "study_revision_label": self.payload["study_identity"]["study_revision_label"],
        }


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def validate_contract_schema(payload: Mapping[str, Any]) -> list[str]:
    import jsonschema

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    return sorted(
        f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in validator.iter_errors(payload)
    )


def load_scientific_study_contract(path: Path, *, repo_root: Path) -> ScientificStudyContract:
    """Load, schema-validate, and hash a contract stored inside the repository."""
    resolved = Path(path).resolve()
    root = Path(repo_root).resolve()
    try:
        relative = resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise ScientificStudyContractError(
            "contract_outside_repository", f"contract must live inside the Atlas repository: {path}"
        ) from exc
    content = resolved.read_bytes()
    payload = json.loads(content.decode("utf-8"))
    errors = validate_contract_schema(payload)
    if errors:
        raise ScientificStudyContractError("invalid_contract_schema", "; ".join(errors))
    expected_dir = (
        f"{STUDIES_ROOT_RELATIVE}/{payload['study_identity']['dataset_slug']}/"
        f"{payload['study_identity']['study_revision_label']}/{CONTRACT_FILENAME}"
    )
    if relative != expected_dir:
        raise ScientificStudyContractError(
            "contract_location_mismatch",
            f"contract identity requires location {expected_dir!r}, found {relative!r}",
        )
    if not payload["study_identity"]["study_revision_label"].endswith(payload["source_repository"]["revision"][:12]):
        raise ScientificStudyContractError(
            "revision_label_mismatch",
            "study_revision_label must end with the first 12 characters of the pinned revision",
        )
    return ScientificStudyContract(payload=payload, relative_path=relative, sha256=_sha256_bytes(content))


def assess_protocol_support(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return every contract element the Atlas reproduction engine cannot execute."""
    caps = REPRODUCTION_CAPABILITIES
    gaps: list[dict[str, Any]] = []

    def check(element: str, value: Any, allowed: Any) -> None:
        if value not in allowed:
            gaps.append({
                "element": element,
                "value": value,
                "reason": f"not implemented by the Atlas reproduction engine (supported: {sorted(allowed)})",
            })

    check("problem.problem_type", payload["problem"]["problem_type"], caps["problem_types"])
    check("study_identity.protocol_kind", payload["study_identity"]["protocol_kind"], caps["protocol_kinds"])
    for index, rule in enumerate(payload["preparation"]["rules"]):
        check(f"preparation.rules[{index}].kind", rule["kind"], caps["preparation_rule_kinds"])
    check("split.kind", payload["split"]["kind"], caps["split_kinds"])
    check("preprocessing.kind", payload["preprocessing"]["kind"], caps["preprocessing_kinds"])
    check("cross_validation.kind", payload["cross_validation"]["kind"], caps["cross_validation_kinds"])
    check("selection.kind", payload["selection"]["kind"], caps["selection_kinds"])
    check("threshold_policy.kind", payload["threshold_policy"]["kind"], caps["threshold_policy_kinds"])
    check("final_evaluation.kind", payload["final_evaluation"]["kind"], caps["final_evaluation_kinds"])
    for metric in payload["metrics"]["evaluated"]:
        check("metrics.evaluated", metric, caps["metrics"])
    for breaker in payload["selection"].get("tie_breakers", []):
        check("selection.tie_breakers.field", breaker.get("field"), caps["tie_breaker_fields"])

    task_type = (
        model_families.CLASSIFICATION
        if payload["problem"]["problem_type"].endswith("classification")
        else model_families.REGRESSION
    )
    all_candidates = list(payload["candidates"])
    if payload.get("baseline"):
        all_candidates.append(payload["baseline"])
    for candidate in all_candidates:
        prefix = f"candidates[{candidate['model_id']}]"
        check(f"{prefix}.search.kind", candidate["search"]["kind"], caps["search_kinds"])
        family_id = candidate["family"]
        if family_id not in model_families.MODEL_FAMILIES:
            gaps.append({"element": f"{prefix}.family", "value": family_id,
                         "reason": "model family is not registered in pipeline.model_families"})
            continue
        family = model_families.get_family(family_id)
        if not family.supports(task_type):
            gaps.append({"element": f"{prefix}.family", "value": family_id,
                         "reason": f"model family does not support task type {task_type!r}"})
            continue
        try:
            accepted = model_families.accepted_hyperparameters(family_id, task_type)
        except model_families.ModelFamilyError as exc:
            gaps.append({"element": f"{prefix}.family", "value": family_id, "reason": str(exc)})
            continue
        declared = set(candidate["fixed_params"]) | set(candidate["search"].get("space", {}))
        for name in sorted(declared - accepted):
            gaps.append({"element": f"{prefix}.hyperparameter", "value": name,
                         "reason": "hyperparameter is not accepted by the registered estimator"})
    return gaps


def _notebook_output_text(notebook: Mapping[str, Any], cell_index: int) -> str:
    cells = notebook.get("cells", [])
    if not 0 <= cell_index < len(cells):
        return ""
    chunks: list[str] = []
    for output in cells[cell_index].get("outputs", []):
        if output.get("output_type") == "stream":
            text = output.get("text", "")
        else:
            text = output.get("data", {}).get("text/plain", "")
        chunks.append("".join(text) if isinstance(text, list) else str(text))
    return "\n".join(chunks)


def _resolve_json_pointer(document: Any, pointer: str) -> tuple[bool, Any]:
    if pointer in ("", "/"):
        return True, document
    node = document
    for token in pointer.lstrip("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list) and token.isdigit() and int(token) < len(node):
            node = node[int(token)]
        elif isinstance(node, Mapping) and token in node:
            node = node[token]
        else:
            return False, None
    return True, node


def _locate_rendered_text(checkout: Path, item: Mapping[str, Any], cache: dict[str, Any]) -> bool:
    """Check that an expected value is present at its source locator.

    Locators: ``notebook_cell_output:<index>`` and ``file_text`` search for
    the rendered text; ``json_pointer:<RFC 6901 pointer>`` resolves a value in
    a structured JSON artifact and requires it to equal the expected value.
    """
    source = item["source"]
    path = checkout / source["path"]
    if not path.is_file():
        return False
    locator = source["locator"]
    if locator.startswith("json_pointer:"):
        if source["path"] not in cache:
            cache[source["path"]] = json.loads(path.read_text(encoding="utf-8"))
        found, value = _resolve_json_pointer(cache[source["path"]], locator.split(":", 1)[1])
        return found and value == item["expected"]
    if locator.startswith("notebook_cell_output:"):
        if source["path"] not in cache:
            cache[source["path"]] = json.loads(path.read_text(encoding="utf-8"))
        text = _notebook_output_text(cache[source["path"]], int(locator.split(":", 1)[1]))
    elif locator == "file_text" or locator.startswith("file_text:"):
        text = path.read_text(encoding="utf-8")
    else:
        return False
    return source["rendered_text"] in text


def verify_against_study_checkout(payload: Mapping[str, Any], checkout_root: Path) -> dict[str, Any]:
    """Check a read-only study checkout against the contract's pins.

    Reports the checkout revision, every pinned-file hash comparison, and
    whether every expected value's rendered text is present at its locator.
    The checkout is only read; its absolute location is never returned.
    """
    checkout = Path(checkout_root).resolve()
    revision: str | None
    try:
        completed = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, check=True,
        )
        revision = completed.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        revision = None
    pinned_revision = payload["source_repository"]["revision"]

    file_checks = []
    for pinned in payload["source_repository"]["pinned_files"]:
        target = checkout / pinned["path"]
        observed = _sha256_bytes(target.read_bytes()) if target.is_file() else None
        file_checks.append({
            "path": pinned["path"],
            "role": pinned["role"],
            "expected_sha256": pinned["sha256"],
            "observed_sha256": observed,
            "matches": observed == pinned["sha256"],
        })

    cache: dict[str, Any] = {}
    evidence_checks = []
    for group in ("values", "decisions"):
        for item in payload["expected_evidence"][group]:
            evidence_checks.append({
                "quantity": item["quantity"],
                "source_path": item["source"]["path"],
                "locator": item["source"]["locator"],
                "rendered_text_found": _locate_rendered_text(checkout, item, cache),
            })

    revision_matches = revision == pinned_revision
    files_match = all(check["matches"] for check in file_checks)
    evidence_found = all(check["rendered_text_found"] for check in evidence_checks)
    if revision_matches and files_match and evidence_found:
        status = "synchronized"
    elif files_match and evidence_found:
        status = "revision_differs_but_pinned_content_unchanged"
    else:
        status = "study_revision_drift"
    return {
        "status": status,
        "pinned_revision": pinned_revision,
        "checkout_revision": revision,
        "revision_matches": revision_matches,
        "pinned_files": file_checks,
        "expected_evidence_locators": evidence_checks,
        "checkout_location_recorded": False,
    }
