"""
Contract derivation pipeline for atlas-dataflow (M13-03).

Validates the runtime contract at source_contract_ref against the runtime contract schema,
then derives a safe public contract artifact by applying projection rules.

Scope: contract validation (runtime) and derivation (public) only. Does not perform
candidate assembly, publisher calls, registry mutation, or public contract editing.

FRESH field defaults are deterministic and reproducible:
- label: feature name with underscores/hyphens replaced by spaces, converted to title case.
- display_order: 1-based positional index of the feature in the runtime features array.
- schema_version (public): fixed constant "1.0.0" (first-cycle versioning assumption).

Feature order in the runtime contract is the authoritative source for display_order.
Study authors must order features intentionally in the runtime contract document.

Pipeline-derived labels are templates for study-author refinement, not production-ready
UI strings.

Categorical (select) features additionally carry an options projection (M32-01):
- options: present only when the runtime feature has a non-empty
  domain_constraints.values list. Each entry is a safe {value, label} pair —
  value CARRIED verbatim from the runtime domain value, label FRESH-derived via
  _fresh_label, in source declaration order. Entirely absent (not an empty list)
  when domain_constraints or values are missing, so the web experience has a
  deterministic signal to fall back to an unguided input. Never present for
  numeric or boolean features. The raw domain_constraints object itself is never
  copied into the public feature — only newly constructed {value, label} dicts.

_RUNTIME_ONLY_KEYS mirrors api/public_contract_loader.py._RUNTIME_ONLY_KEYS.
If that module's constant changes, this constant must be updated to match.

This module also exposes `project_execution_contract_draft` (Project Spec
S0014): a deterministic projection from a `dataset_modeling_intent.v1`
authoring-intent object (Project Spec S0013,
`pipeline/discovery_evidence.py.build_dataset_modeling_intent`) into an
`execution_contract_draft.v1` candidate. This draft reuses
`execution_contract.v1` vocabulary (target_column, feature_columns,
ignored_columns, feature type) where the modeling intent already supports
it, but is never itself an execution contract — unresolved review items stay
visible instead of being converted into accepted execution policy.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent
RUNTIME_SCHEMA_PATH = REPO_ROOT / "contracts" / "runtime-contract.schema.json"
PUBLIC_SCHEMA_PATH = REPO_ROOT / "contracts" / "public-contract.schema.json"

# Source: api/public_contract_loader.py._RUNTIME_ONLY_KEYS
# Must be kept in sync with that module manually — no automatic synchronization.
_RUNTIME_ONLY_KEYS = frozenset({
    "artifact",
    "artifacts",
    "constraints",
    "domain_constraints",
    "hidden_constraints",
    "implementation",
    "internal",
    "path",
    "reference",
    "release",
    "required",
    "schema",
    "validation",
    "validators",
})

_INPUT_TYPE_MAP = {
    "numeric": "number",
    "categorical": "select",
    "boolean": "checkbox",
}

PUBLIC_CONTRACT_SCHEMA_VERSION = "1.0.0"


def _load_json(path):
    """Load and parse a JSON file. Returns (data, error_message)."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None
    except FileNotFoundError:
        return None, f"file not found: {path}"
    except PermissionError:
        return None, f"file not readable: {path}"
    except json.JSONDecodeError as exc:
        return None, f"not valid JSON: {exc}"


def _validate_schema(data, schema):
    """Validate data against schema. Returns list of error messages."""
    try:
        import jsonschema
        validator = jsonschema.Draft7Validator(schema)
        errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
        return [e.message for e in errors]
    except ImportError:
        # Fail-safe: reject rather than accept if jsonschema is unavailable.
        required = schema.get("required", [])
        missing = [f for f in required if f not in data]
        if missing:
            return [f"missing required field: '{f}'" for f in missing]
        return ["jsonschema library unavailable — cannot perform full schema validation; rejecting as fail-safe"]


def _fresh_label(name):
    """Deterministic FRESH label default: replace _ and - with spaces, apply title case."""
    return name.replace("_", " ").replace("-", " ").title()


def _derive_public_options(feature):
    """Derive a safe options projection for a categorical feature, or None.

    Returns a list of {value, label} dicts sourced from a non-empty
    domain_constraints.values, in source declaration order. Returns None
    (absence, never an empty list) when the feature is not categorical, or
    has no domain_constraints, or has an empty values list.
    """
    if feature["type"] != "categorical":
        return None
    values = feature.get("domain_constraints", {}).get("values")
    if not values:
        return None
    return [{"value": value, "label": _fresh_label(value)} for value in values]


def _derive_public_feature(feature, display_order):
    """Apply projection rules to a single runtime feature to produce a public feature."""
    public = {}
    # CARRIED: name always; description if present
    public["name"] = feature["name"]
    if "description" in feature:
        public["description"] = feature["description"]
    # DERIVED: input_type from type
    public["input_type"] = _INPUT_TYPE_MAP[feature["type"]]
    # INVERTED: optional = not required (default required=True → optional=False)
    public["optional"] = not feature.get("required", True)
    # FRESH: label from title-cased name
    public["label"] = _fresh_label(feature["name"])
    # FRESH: display_order from 1-based position
    public["display_order"] = display_order
    # OPTIONAL-DERIVED: options, categorical features with declared values only
    options = _derive_public_options(feature)
    if options is not None:
        public["options"] = options
    return public


def _derive_public_contract(runtime_contract):
    """Derive a complete public contract from a validated runtime contract."""
    public_features = [
        _derive_public_feature(feature, i + 1)
        for i, feature in enumerate(runtime_contract["features"])
    ]
    return {
        "schema_version": PUBLIC_CONTRACT_SCHEMA_VERSION,
        "features": public_features,
    }


def _check_safety(public_contract):
    """Verify no _RUNTIME_ONLY_KEYS appear in any public feature object."""
    violations = []
    for i, feature in enumerate(public_contract.get("features", [])):
        leaked = _RUNTIME_ONLY_KEYS & set(feature.keys())
        if leaked:
            violations.append(
                f"feature[{i}] ({feature.get('name', '?')!r}) "
                f"contains runtime-only keys: {sorted(leaked)}"
            )
    return violations


def _rejection(reason, rejection_phase, source_contract_ref, input_path):
    return {
        "status": "rejected",
        "reason": reason,
        "rejection_phase": rejection_phase,
        "source_contract_ref": source_contract_ref,
        "input_path": str(input_path) if input_path else None,
    }


def _acceptance(dataset_slug, release_id, runtime_path, public_path):
    return {
        "status": "accepted",
        "dataset_slug": dataset_slug,
        "release_id": release_id,
        "runtime_contract_path": str(runtime_path),
        "public_contract_path": str(public_path),
    }


# ---------------------------------------------------------------------------
# Execution contract draft projection (Project Spec S0014)
#
# Projects a `dataset_modeling_intent.v1` authoring-intent object into a
# narrow `execution_contract_draft.v1` candidate. This is deliberately not an
# `execution_contract.v1` (contracts/execution-contract.schema.json): the
# draft never populates that schema's execution-only training policy fields
# (missing_value_policy, categorical_encoding_policy, numeric_handling,
# allowed_transformations, split_policy, random_seed, primary_metric,
# secondary_metrics, modeling_constraints) — those remain explicit unresolved
# review items until a later, separately authorized spec supplies reviewed
# policy. Not an execution contract, runtime contract, public contract,
# release candidate input, publisher input, registry artifact, API fixture,
# or UI fixture.
# ---------------------------------------------------------------------------

EXECUTION_CONTRACT_DRAFT_CONTRACT_VERSION = "execution_contract_draft.v1"

# execution_contract.v1 required fields this projection never derives —
# surfaced as standing blocking reasons so a draft can never look
# execution-ready just because its known fields happen to be filled in.
_UNRESOLVED_EXECUTION_CONTRACT_POLICY_FIELDS = (
    "missing_value_policy",
    "categorical_encoding_policy",
    "numeric_handling",
    "allowed_transformations",
    "split_policy",
    "random_seed",
    "primary_metric",
    "secondary_metrics",
    "modeling_constraints",
)

EXECUTION_CONTRACT_DRAFT_BOUNDARY_CONFIRMATIONS = {
    "is_execution_contract": False,
    "is_runtime_contract": False,
    "is_public_contract": False,
    "is_release_candidate_input": False,
    "is_publisher_input": False,
    "is_registry_artifact": False,
    "is_api_fixture": False,
    "is_ui_fixture": False,
    "model_training_performed": False,
    "promoted_to_official_execution_contract": False,
}


def _utc_now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _draft_blocking_reasons(modeling_intent):
    """Collect explicit, unresolved preparation review items.

    Never invents a blocking reason for something the modeling intent
    doesn't itself flag — only surfaces blank-value policy candidates and
    feature-type entries the modeling intent already marked as under review,
    plus the standing execution-contract policy fields this projection never
    derives.
    """
    reasons = []
    blank_value_policy_candidates = modeling_intent.get("blank_value_policy_candidates") or {}
    for column in sorted(blank_value_policy_candidates):
        policy = blank_value_policy_candidates[column]
        reasons.append(
            f"{column}: blank-value handling is only a candidate policy "
            f"({policy!r}), not yet accepted — requires explicit resolution "
            "before execution-ready use"
        )
    for entry in modeling_intent.get("feature_type_intent") or []:
        if entry.get("type_intent") == "requires_review":
            reasons.append(
                f"{entry.get('name')}: feature type/semantic classification "
                "requires explicit review before execution-ready use"
            )
    for field in _UNRESOLVED_EXECUTION_CONTRACT_POLICY_FIELDS:
        reasons.append(
            f"{field}: not supplied by this draft projection; required by "
            "execution_contract.v1 before promotion to an official contract"
        )
    return reasons


def project_execution_contract_draft(modeling_intent, generated_at=None):
    """Project a `dataset_modeling_intent.v1` object into an execution-contract draft.

    Deterministic and independent of Jupyter execution: every field is read
    from the already-built modeling-intent object (see
    `pipeline.discovery_evidence.build_dataset_modeling_intent`), never from
    raw dataset rows. Reuses `execution_contract.v1` vocabulary
    (`target_column`, `feature_columns`, `ignored_columns`) where the
    modeling intent already supports it, but `artifact_type`/
    `contract_version` are distinct from `execution_contract.v1` and
    `execution_readiness.is_execution_ready` is always `False` — this
    projection never emits final preprocessing, split, metric, or
    model-family policy, so the result must never be mistaken for an
    execution-ready contract.
    """
    dataset_identity = modeling_intent.get("dataset_identity") or {}
    authoring_source = modeling_intent.get("authoring_source") or {}
    target_intent = modeling_intent.get("target_intent") or {}
    identifier_and_ignored_columns = list(
        modeling_intent.get("identifier_and_ignored_columns") or []
    )

    feature_definitions = {
        entry["name"]: {"type_intent": entry.get("type_intent", "requires_review")}
        for entry in modeling_intent.get("feature_type_intent") or []
    }

    return {
        "artifact_type": "execution_contract_draft",
        "contract_version": EXECUTION_CONTRACT_DRAFT_CONTRACT_VERSION,
        "draft_status": "not_execution_ready",
        "dataset_identity": dict(dataset_identity),
        "authoring_traceability": {
            "authoring_notebook_ref": authoring_source.get("authoring_notebook_ref"),
            "reduced_discovery_evidence_ref": authoring_source.get(
                "reduced_discovery_evidence_ref"
            ),
            "source_modeling_intent_contract_version": modeling_intent.get("contract_version"),
            "source_modeling_intent_generated_at": modeling_intent.get("generated_at"),
        },
        "task_intent": {"task_type": target_intent.get("task_type")},
        "target_column": target_intent.get("target_column"),
        "target_intent": {
            "target_column": target_intent.get("target_column"),
            "observed_labels": list(target_intent.get("observed_labels") or []),
            "observed_target_distribution": dict(
                target_intent.get("observed_target_distribution") or {}
            ),
            "positive_label_candidate": target_intent.get("positive_label_candidate"),
        },
        "ignored_columns": [entry["name"] for entry in identifier_and_ignored_columns],
        "identifier_and_ignored_columns": identifier_and_ignored_columns,
        "feature_columns": list(modeling_intent.get("initial_feature_candidates") or []),
        "feature_definitions": feature_definitions,
        "feature_review_notes": dict(modeling_intent.get("feature_review_notes") or {}),
        "blank_value_policy_candidates": dict(
            modeling_intent.get("blank_value_policy_candidates") or {}
        ),
        "execution_readiness": {
            "is_execution_ready": False,
            "blocking_reasons": _draft_blocking_reasons(modeling_intent),
        },
        "execution_contract_draft_boundary_confirmations": dict(
            EXECUTION_CONTRACT_DRAFT_BOUNDARY_CONFIRMATIONS
        ),
        "generated_at": generated_at or _utc_now_iso(),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Validate runtime contract and derive public contract artifacts."
    )
    parser.add_argument(
        "source_input_path",
        help="Path to validated source input JSON file (source-contract-input.v1).",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory where runtime-contract.json and public-contract.json are written.",
    )
    args = parser.parse_args()

    input_path = args.source_input_path
    output_dir = Path(args.output_dir)

    # Step 1: Load source input JSON and extract fields.
    source_input, load_err = _load_json(input_path)
    if load_err:
        print(json.dumps(_rejection(
            f"could not load source input: {load_err}",
            "source_input_read",
            None,
            input_path,
        ), indent=2))
        return 1

    source_contract_ref = source_input.get("source_contract_ref")
    dataset_slug = source_input.get("dataset_slug")
    release_id = source_input.get("release_id")

    # Step 2: Resolve source_contract_ref relative to working directory.
    if not source_contract_ref:
        print(json.dumps(_rejection(
            "source_contract_ref is missing from source input",
            "runtime_contract_read",
            source_contract_ref,
            input_path,
        ), indent=2))
        return 1

    runtime_ref_path = Path(source_contract_ref)
    if not runtime_ref_path.exists() or not runtime_ref_path.is_file():
        print(json.dumps(_rejection(
            f"runtime contract not found at source_contract_ref: {source_contract_ref}",
            "runtime_contract_read",
            source_contract_ref,
            input_path,
        ), indent=2))
        return 1

    # Step 3: Parse runtime contract JSON.
    runtime_contract, parse_err = _load_json(str(runtime_ref_path))
    if parse_err:
        print(json.dumps(_rejection(
            f"could not parse runtime contract: {parse_err}",
            "runtime_contract_parse",
            source_contract_ref,
            input_path,
        ), indent=2))
        return 1

    # Step 4: Load runtime schema and validate runtime contract against it.
    runtime_schema, schema_load_err = _load_json(str(RUNTIME_SCHEMA_PATH))
    if schema_load_err:
        print(json.dumps(_rejection(
            f"could not load runtime contract schema: {schema_load_err}",
            "runtime_contract_schema",
            source_contract_ref,
            input_path,
        ), indent=2))
        return 1

    runtime_errors = _validate_schema(runtime_contract, runtime_schema)
    if runtime_errors:
        first = runtime_errors[0]
        reason = first if len(runtime_errors) == 1 else f"{len(runtime_errors)} validation errors: {first}"
        print(json.dumps(_rejection(
            f"runtime contract fails schema validation: {reason}",
            "runtime_contract_schema",
            source_contract_ref,
            input_path,
        ), indent=2))
        return 1

    # Step 5: Derive public contract from the validated runtime contract.
    public_contract = _derive_public_contract(runtime_contract)

    # Step 6: Load public schema and validate the derived public contract.
    public_schema, pub_schema_err = _load_json(str(PUBLIC_SCHEMA_PATH))
    if pub_schema_err:
        print(json.dumps(_rejection(
            f"could not load public contract schema: {pub_schema_err}",
            "public_contract_schema",
            source_contract_ref,
            input_path,
        ), indent=2))
        return 1

    public_errors = _validate_schema(public_contract, public_schema)
    if public_errors:
        first = public_errors[0]
        reason = first if len(public_errors) == 1 else f"{len(public_errors)} validation errors: {first}"
        print(json.dumps(_rejection(
            f"derived public contract fails schema validation (pipeline bug): {reason}",
            "public_contract_schema",
            source_contract_ref,
            input_path,
        ), indent=2))
        return 1

    # Step 7: Safety check — no _RUNTIME_ONLY_KEYS in any derived public feature.
    violations = _check_safety(public_contract)
    if violations:
        print(json.dumps(_rejection(
            f"public contract safety check failed: {'; '.join(violations)}",
            "public_contract_safety",
            source_contract_ref,
            input_path,
        ), indent=2))
        return 1

    # Step 8: Assert distinct output paths (always true by construction).
    runtime_out = output_dir / "runtime-contract.json"
    public_out = output_dir / "public-contract.json"
    assert runtime_out != public_out, (
        "pipeline bug: runtime and public contract output paths must be distinct"
    )

    # Step 9: Write validated runtime contract to output directory.
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(runtime_out, "w", encoding="utf-8") as f:
        json.dump(runtime_contract, f, indent=2)

    # Step 10: Write derived public contract to output directory.
    with open(public_out, "w", encoding="utf-8") as f:
        json.dump(public_contract, f, indent=2)

    # Step 11: Emit acceptance result to stdout.
    print(json.dumps(_acceptance(dataset_slug, release_id, runtime_out, public_out), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
