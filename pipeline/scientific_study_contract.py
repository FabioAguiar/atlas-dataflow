"""Scientific Study Contract loading, capability assessment, and source verification.

A scientific study contract pins one revision of an external Dataset Study:
its commit, the hashes of the files the protocol and reference evidence were
read from, the dataset identity, the scientific environment, the declarative
protocol, and the evidence the study published at that revision. Contracts
live under ``pipeline/scientific-studies/<dataset-slug>/<study-revision-label>/``
and are immutable: a changed study revision gets a new directory.

Two schema versions are accepted and never rewritten into each other:

* ``scientific-study-contract.v1`` -- binary classification only;
* ``scientific-study-contract.v2`` -- binary and multiclass classification,
  with problem-type conditional rules (a multiclass contract must declare
  ``positive_class`` and ``threshold_policy`` as explicitly not applicable and
  must declare estimator/public class orders and an argmax decision rule),
  technical row-occurrence membership, protocol gates, a family shortlist and
  a feature-policy selection stage.

This module never executes a protocol. It answers four questions:

* is the contract structurally valid (JSON Schema of its declared version)?
* is it semantically coherent (``validate_contract_semantics``)?
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


SCHEMA_VERSION_V1 = "scientific-study-contract.v1"
SCHEMA_VERSION_V2 = "scientific-study-contract.v2"
SCHEMA_VERSION = SCHEMA_VERSION_V2
CONTRACT_FILENAME = "scientific-study-contract.json"
_SCHEMA_DIR = Path(__file__).resolve().parent
SCHEMA_PATHS: Mapping[str, Path] = {
    SCHEMA_VERSION_V1: _SCHEMA_DIR / "scientific-study-contract.schema.json",
    SCHEMA_VERSION_V2: _SCHEMA_DIR / "scientific-study-contract.v2.schema.json",
}
SCHEMA_PATH = SCHEMA_PATHS[SCHEMA_VERSION_V1]
STUDIES_ROOT_RELATIVE = "pipeline/scientific-studies"

BINARY = "binary_classification"
MULTICLASS = "multiclass_classification"

# Metric vocabulary per problem type. Binary metrics need a positive class
# and (for threshold metrics) a threshold; multiclass metrics need neither.
METRICS_BY_PROBLEM_TYPE: Mapping[str, frozenset[str]] = {
    BINARY: frozenset({
        "average_precision", "roc_auc", "precision", "recall", "f1", "f2",
        "balanced_accuracy", "accuracy", "log_loss", "brier_score",
    }),
    MULTICLASS: frozenset({
        "macro_f1", "balanced_accuracy", "macro_recall", "weighted_f1",
        "accuracy", "minimum_per_class_recall", "log_loss",
    }),
}

# Protocol vocabulary the reproduction engine implements. A contract element
# outside this vocabulary is an Atlas capability gap, never silently skipped.
REPRODUCTION_CAPABILITIES: Mapping[str, Any] = {
    "problem_types": {BINARY, MULTICLASS},
    "protocol_kinds": {"tabular_holdout_model_selection.v1", "tabular_holdout_model_selection.v2"},
    "preparation_rule_kinds": {"conditional_blank_numeric_fill"},
    "split_kinds": {"two_stage_stratified_holdout"},
    "membership_kinds": {"identifier", "technical_row_occurrence"},
    "preprocessing_kinds": {"column_transformer_onehot_plus_numeric"},
    "cross_validation_kinds": {"stratified_k_fold"},
    "search_kinds": {"grid", "randomized", "none"},
    "selection_kinds": {"leader_anchored_practical_tie"},
    "threshold_policy_kinds": {"max_precision_subject_to_min_recall", "not_applicable"},
    "decision_rule_kinds": {"probability_threshold", "argmax_class_probability"},
    "family_shortlist_kinds": {"top_k_by_cv_metric"},
    "feature_policy_kinds": {"frozen_family_params_feature_projection"},
    "final_evaluation_kinds": {"refit_on_train_plus_validation_single_test_evaluation"},
    "metrics": METRICS_BY_PROBLEM_TYPE,
    "tie_breaker_fields": {"simplicity_rank", "model_id"},
}


def problem_type_of(payload: Mapping[str, Any]) -> str:
    return payload["problem"]["problem_type"]


def metric_vocabulary(problem_type: str) -> frozenset[str]:
    return METRICS_BY_PROBLEM_TYPE.get(problem_type, frozenset())


def _is_supported_tie_breaker_field(field: Any, problem_type: str = BINARY) -> bool:
    """``validation_<metric>``, ``cv_<metric>_mean``/``_std``, or a fixed field."""
    if field in REPRODUCTION_CAPABILITIES["tie_breaker_fields"]:
        return True
    if not isinstance(field, str):
        return False
    metrics = metric_vocabulary(problem_type)
    if field.startswith("validation_"):
        return field.removeprefix("validation_") in metrics
    if field.startswith("cv_"):
        for suffix in ("_mean", "_std"):
            if field.endswith(suffix):
                return field.removeprefix("cv_").removesuffix(suffix) in metrics
    return False


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
    """Validate against the JSON Schema of the contract's own declared version."""
    import jsonschema

    version = payload.get("schema_version") if isinstance(payload, Mapping) else None
    schema_path = SCHEMA_PATHS.get(version)
    if schema_path is None:
        return [f"schema_version: unsupported scientific study contract version {version!r} "
                f"(supported: {sorted(SCHEMA_PATHS)})"]
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
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
    semantic_errors = validate_contract_semantics(payload)
    if semantic_errors:
        raise ScientificStudyContractError("invalid_contract_semantics", "; ".join(semantic_errors))
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


def validate_contract_semantics(payload: Mapping[str, Any]) -> list[str]:
    """Cross-field coherence rules a JSON Schema cannot express.

    v1 contracts predate these rules and are binary by construction; only v2
    contracts are checked here.
    """
    if payload.get("schema_version") != SCHEMA_VERSION_V2:
        return []
    errors: list[str] = []
    problem = payload["problem"]
    target = problem["target"]
    classes = list(target["classes"])
    features = list(payload["features"]["feature_columns"])
    if set(payload["features"]["numerical"]) | set(payload["features"]["categorical"]) != set(features):
        errors.append("features.numerical + features.categorical must cover exactly features.feature_columns")
    if set(payload["features"]["numerical"]) & set(payload["features"]["categorical"]):
        errors.append("features.numerical and features.categorical must be disjoint")
    if target["column"] in features:
        errors.append("the target column cannot be a feature")
    if problem["problem_type"] == MULTICLASS:
        for order_name in ("estimator_class_order", "public_class_order"):
            order = list(target.get(order_name, []))
            if sorted(map(str, order)) != sorted(map(str, classes)) or len(order) != len(classes):
                errors.append(f"problem.target.{order_name} must be a permutation of problem.target.classes")
    if problem["problem_type"] == BINARY:
        encoding = target.get("encoding") or {}
        if str(target.get("positive_class")) not in {str(k) for k in encoding}:
            errors.append("problem.target.positive_class must be one of the encoded classes")
    policies = payload.get("feature_policies")
    if policies:
        seen: set[str] = set()
        for policy in policies["policies"]:
            if policy["policy_id"] in seen:
                errors.append(f"duplicate feature policy {policy['policy_id']!r}")
            seen.add(policy["policy_id"])
            unknown = sorted(set(policy["exclude"]) - set(features))
            if unknown:
                errors.append(f"feature policy {policy['policy_id']!r} excludes unknown features {unknown}")
            if len(set(policy["exclude"])) >= len(features):
                errors.append(f"feature policy {policy['policy_id']!r} excludes every feature")
        shortlist = payload.get("family_shortlist") or {}
        if shortlist.get("k", 0) > len(payload["candidates"]):
            errors.append("family_shortlist.k exceeds the number of candidate families")
    ids = [c["model_id"] for c in payload["candidates"]]
    if len(set(ids)) != len(ids):
        errors.append("candidate model_id values must be unique")
    canonical = payload.get("canonical_run")
    if canonical:
        pinned = {f["path"]: f["sha256"] for f in payload["source_repository"]["pinned_files"]}
        if pinned.get(canonical["path"]) != canonical["sha256"]:
            errors.append("canonical_run must be pinned in source_repository.pinned_files with the same SHA-256")
    for group in ("values", "decisions", "runtime_identity"):
        quantities = [item["quantity"] for item in payload["expected_evidence"].get(group, [])]
        duplicated = sorted({q for q in quantities if quantities.count(q) > 1})
        if duplicated:
            errors.append(f"expected_evidence.{group} repeats quantities {duplicated}")
    return errors


def assess_protocol_support(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return every contract element the Atlas reproduction engine cannot execute.

    Dispatch is by ``problem.problem_type`` (never by dataset): the metric
    vocabulary, the admissible threshold policy, and the decision rule are
    problem-type specific.
    """
    caps = REPRODUCTION_CAPABILITIES
    gaps: list[dict[str, Any]] = []
    problem_type = problem_type_of(payload)

    def check(element: str, value: Any, allowed: Any) -> None:
        if value not in allowed:
            gaps.append({
                "element": element,
                "value": value,
                "reason": f"not implemented by the Atlas reproduction engine (supported: {sorted(allowed)})",
            })

    check("problem.problem_type", problem_type, caps["problem_types"])
    check("study_identity.protocol_kind", payload["study_identity"]["protocol_kind"], caps["protocol_kinds"])
    for index, rule in enumerate(payload["preparation"]["rules"]):
        check(f"preparation.rules[{index}].kind", rule["kind"], caps["preparation_rule_kinds"])
    check("split.kind", payload["split"]["kind"], caps["split_kinds"])
    membership = payload["split"].get("membership")
    if membership is not None:
        check("split.membership.kind", membership.get("kind"), caps["membership_kinds"])
    check("preprocessing.kind", payload["preprocessing"]["kind"], caps["preprocessing_kinds"])
    check("cross_validation.kind", payload["cross_validation"]["kind"], caps["cross_validation_kinds"])
    check("selection.kind", payload["selection"]["kind"], caps["selection_kinds"])
    check("threshold_policy.kind", payload["threshold_policy"]["kind"], caps["threshold_policy_kinds"])
    decision_rule = payload["problem"].get("decision_rule")
    if decision_rule is not None:
        check("problem.decision_rule.kind", decision_rule.get("kind"), caps["decision_rule_kinds"])
    # Problem-type coherence of the threshold concept (explicit N/A semantics).
    threshold_kind = payload["threshold_policy"]["kind"]
    if problem_type == MULTICLASS and threshold_kind != "not_applicable":
        gaps.append({"element": "threshold_policy.kind", "value": threshold_kind,
                     "reason": "a multiclass argmax protocol has no binary threshold; it must be declared not_applicable"})
    if problem_type == BINARY and threshold_kind == "not_applicable":
        gaps.append({"element": "threshold_policy.kind", "value": threshold_kind,
                     "reason": "the binary reproduction protocol requires a declared threshold policy"})
    if payload.get("family_shortlist"):
        check("family_shortlist.kind", payload["family_shortlist"]["kind"], caps["family_shortlist_kinds"])
    if payload.get("feature_policies"):
        check("feature_policies.kind", payload["feature_policies"]["kind"], caps["feature_policy_kinds"])
    check("final_evaluation.kind", payload["final_evaluation"]["kind"], caps["final_evaluation_kinds"])
    vocabulary = metric_vocabulary(problem_type)
    for metric in payload["metrics"]["evaluated"]:
        if metric not in vocabulary:
            gaps.append({"element": "metrics.evaluated", "value": metric,
                         "reason": f"metric is not implemented for {problem_type!r} (supported: {sorted(vocabulary)})"})
    for metric in payload["metrics"].get("cv_scorers", []):
        if metric not in vocabulary or metric == "minimum_per_class_recall":
            gaps.append({"element": "metrics.cv_scorers", "value": metric,
                         "reason": "no cross-validation scorer is implemented for this metric"})
    for field_name in ("primary", "refit"):
        metric = payload["metrics"].get(field_name)
        if metric is not None and metric not in vocabulary:
            gaps.append({"element": f"metrics.{field_name}", "value": metric,
                         "reason": f"metric is not implemented for {problem_type!r}"})
    for breaker in payload["selection"].get("tie_breakers", []):
        if not _is_supported_tie_breaker_field(breaker.get("field"), problem_type):
            gaps.append({"element": "selection.tie_breakers.field", "value": breaker.get("field"),
                         "reason": "tie-breaker field is not a validation/cv metric or a supported fixed field"})

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
    for group in ("values", "decisions", "runtime_identity"):
        for item in payload["expected_evidence"].get(group, []):
            evidence_checks.append({
                "quantity": item["quantity"],
                "source_path": item["source"]["path"],
                "locator": item["source"]["locator"],
                "rendered_text_found": _locate_rendered_text(checkout, item, cache),
            })

    revision_matches = revision == pinned_revision
    files_match = all(check["matches"] for check in file_checks)
    # Protocol gates (membership digests, final-fit row count) are reference
    # evidence too, so their sources are re-checked like expected values.
    gate_items = []
    gate = payload["split"].get("membership_gate")
    if gate:
        for partition, digest in gate["expected_membership_sha256"].items():
            pointer = gate["source"]["locator"].rstrip("/") + "/" + partition
            gate_items.append(("split.membership_gate." + partition, {"expected": digest, "source": {
                **gate["source"], "locator": pointer}}))
    row_gate = payload["final_evaluation"].get("fit_row_count_gate")
    if row_gate:
        gate_items.append(("final_evaluation.fit_row_count_gate", {"expected": row_gate["expected_rows"],
                                                                   "source": row_gate["source"]}))
    for quantity, item in gate_items:
        evidence_checks.append({
            "quantity": quantity,
            "source_path": item["source"]["path"],
            "locator": item["source"]["locator"],
            "rendered_text_found": _locate_rendered_text(checkout, item, cache),
        })
    parameter_checks = verify_protocol_parameter_sources(payload, checkout, cache)
    evidence_found = all(check["rendered_text_found"] for check in evidence_checks) and all(
        check["matches"] for check in parameter_checks)
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
        "protocol_parameter_sources": parameter_checks,
        "checkout_location_recorded": False,
    }


def verify_protocol_parameter_sources(payload: Mapping[str, Any], checkout: Path,
                                      cache: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Check declared protocol inputs (seeds, orders, tolerances...) against the study's own artifact.

    Each ``protocol_parameter_sources`` entry names a JSON pointer into this
    contract and a JSON pointer into a pinned study file; both must resolve to
    equal values, so a declared parameter cannot silently drift from the study.
    """
    cache = {} if cache is None else cache
    checks = []
    for entry in payload.get("protocol_parameter_sources", []):
        found_contract, declared = _resolve_json_pointer(payload, entry["contract_pointer"])
        path = Path(checkout) / entry["source"]["path"]
        observed = None
        found_source = False
        if path.is_file():
            if entry["source"]["path"] not in cache:
                cache[entry["source"]["path"]] = json.loads(path.read_text(encoding="utf-8"))
            found_source, observed = _resolve_json_pointer(cache[entry["source"]["path"]],
                                                           entry["source"]["locator"].split(":", 1)[1])
        checks.append({
            "contract_pointer": entry["contract_pointer"],
            "source_path": entry["source"]["path"],
            "locator": entry["source"]["locator"],
            "declared": declared if found_contract else None,
            "study_value": observed if found_source else None,
            "matches": bool(found_contract and found_source and declared == observed),
        })
    return checks


def author_contract_from_draft(draft: Mapping[str, Any], checkout_root: Path) -> dict[str, Any]:
    """Materialize a contract from an authoring draft and a read-only study checkout.

    Generic and deterministic: every ``json_pointer`` expected value, protocol
    gate and pinned-file hash is *read* from the pinned study checkout, never
    transcribed by hand. Draft conventions:

    * an expected item whose locator is ``json_pointer:...`` and which omits
      ``expected`` receives the pointed value (and a rendered text);
    * ``file_text`` items must carry their expected value and rendered text,
      which ``verify_against_study_checkout`` re-checks;
    * a pinned file (or the lock / canonical run) without ``sha256`` receives
      the hash of the checkout file;
    * a membership gate or fit-row gate without values receives them from its
      source pointer.
    """
    checkout = Path(checkout_root).resolve()
    contract = json.loads(json.dumps(draft))
    cache: dict[str, Any] = {}

    def pointed(source: Mapping[str, Any]) -> Any:
        if source["path"] not in cache:
            cache[source["path"]] = json.loads((checkout / source["path"]).read_text(encoding="utf-8"))
        found, value = _resolve_json_pointer(cache[source["path"]], source["locator"].split(":", 1)[1])
        if not found:
            raise ScientificStudyContractError("unresolved_json_pointer",
                                               f"{source['path']} {source['locator']} does not resolve")
        return value

    def file_hash(relative: str) -> str:
        return _sha256_bytes((checkout / relative).read_bytes())

    for pinned in contract["source_repository"]["pinned_files"]:
        pinned.setdefault("sha256", file_hash(pinned["path"]))
    if contract.get("canonical_run"):
        contract["canonical_run"].setdefault("sha256", file_hash(contract["canonical_run"]["path"]))
    lock = contract["scientific_environment"]["lock"]
    lock.setdefault("sha256", file_hash(lock["path"]))
    if lock.get("python_version_file"):
        lock.setdefault("python_version_file_sha256", file_hash(lock["python_version_file"]))
    for group in ("values", "decisions", "runtime_identity"):
        for item in contract["expected_evidence"].get(group, []):
            source = item["source"]
            if source["locator"].startswith("json_pointer:") and "expected" not in item:
                item["expected"] = pointed(source)
                source.setdefault("rendered_text", json.dumps(item["expected"], ensure_ascii=False, sort_keys=True))
            item.setdefault("reported_decimal_places", None)
    for entry in contract.get("protocol_parameter_sources", []):
        entry["source"].setdefault("rendered_text", json.dumps(pointed(entry["source"]), ensure_ascii=False, sort_keys=True))
    gate = contract["split"].get("membership_gate")
    if gate is not None and "expected_membership_sha256" not in gate:
        gate["expected_membership_sha256"] = pointed(gate["source"])
        gate["source"].setdefault("rendered_text", json.dumps(gate["expected_membership_sha256"], sort_keys=True))
    row_gate = contract["final_evaluation"].get("fit_row_count_gate")
    if row_gate is not None and "expected_rows" not in row_gate:
        row_gate["expected_rows"] = pointed(row_gate["source"])
        row_gate["source"].setdefault("rendered_text", json.dumps(row_gate["expected_rows"]))
    return contract


def main(argv: list[str] | None = None) -> int:
    """``author`` materializes a contract from a draft; ``verify`` re-checks one against a checkout."""
    import argparse

    parser = argparse.ArgumentParser(description="Author or verify a Scientific Study Contract.")
    sub = parser.add_subparsers(dest="command", required=True)
    author = sub.add_parser("author")
    author.add_argument("--draft", required=True)
    author.add_argument("--study-checkout", required=True)
    author.add_argument("--output", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--contract", required=True)
    verify.add_argument("--study-checkout", required=True)
    verify.add_argument("--repo-root", default=str(Path(__file__).resolve().parent.parent))
    args = parser.parse_args(argv)
    if args.command == "author":
        draft = json.loads(Path(args.draft).read_text(encoding="utf-8"))
        contract = author_contract_from_draft(draft, Path(args.study_checkout))
        errors = validate_contract_schema(contract) + validate_contract_semantics(contract)
        if errors:
            raise ScientificStudyContractError("invalid_contract", "; ".join(errors))
        output = Path(args.output)
        if output.exists():
            raise ScientificStudyContractError("contract_exists", f"{output} exists; contracts are immutable per revision")
        output.write_text(json.dumps(contract, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({"written": str(output), "sha256": _sha256_bytes(output.read_bytes())}, indent=2))
        return 0
    root = Path(args.repo_root).resolve()
    contract = load_scientific_study_contract(root / args.contract, repo_root=root)
    result = verify_against_study_checkout(contract.payload, Path(args.study_checkout))
    summary = {
        "status": result["status"],
        "revision_matches": result["revision_matches"],
        "pinned_files_matching": sum(c["matches"] for c in result["pinned_files"]),
        "pinned_files_total": len(result["pinned_files"]),
        "evidence_locators_found": sum(c["rendered_text_found"] for c in result["expected_evidence_locators"]),
        "evidence_locators_total": len(result["expected_evidence_locators"]),
        "parameters_matching": sum(c["matches"] for c in result["protocol_parameter_sources"]),
        "parameters_total": len(result["protocol_parameter_sources"]),
        "failures": [c for c in result["expected_evidence_locators"] if not c["rendered_text_found"]]
        + [c for c in result["protocol_parameter_sources"] if not c["matches"]]
        + [c for c in result["pinned_files"] if not c["matches"]],
        "protocol_support_gaps": assess_protocol_support(contract.payload),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "synchronized" else 1


if __name__ == "__main__":
    raise SystemExit(main())
