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

`_build_execution_contract` (Project Spec S0024, updated by S0102) also
materializes any reviewed, approved `categorical_domain_intent` declarations
from the modeling intent into `feature_definitions[name].domain_constraints.values`.
Only declarations with `review_status == "approved"` for an active
categorical feature are ever applied; every other declaration is left
unresolved/rejected and named explicitly in the companion
`execution_contract_materialization_evidence.v1`'s
`categorical_domain_materialization` section rather than silently
approved or silently dropped.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline.discovery_evidence import build_binary_result_semantics_intent


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


def unresolved_select_features(public_contract):
    """Return the names of every input_type: select feature that has no
    safe options projection (Project Spec S0099).

    A select feature with no "options" key is schema-valid (options is an
    optional, present-only-when-derivable field), but it is not a fully
    configured select control -- the web experience must fall back to an
    unguided input for it rather than rendering an empty or invented option
    list. This condition is never invented or silently ignored here; it is
    only detected and named so a caller (derive_projections.derive) can
    report it explicitly instead of it passing through unremarked.
    """
    return [
        feature["name"]
        for feature in public_contract.get("features", [])
        if feature.get("input_type") == "select" and "options" not in feature
    ]


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


# ---------------------------------------------------------------------------
# Execution contract materialization (Project Spec S0024)
#
# Materializes an official `execution_contract.v1` artifact
# (contracts/execution-contract.schema.json) from already-built upstream
# artifacts: `dataset_modeling_intent.v1` (Project Spec S0013), dataset
# discovery evidence, and an optional candidate preparation recipe. Unlike
# `project_execution_contract_draft` above, this IS the official execution
# contract -- it is schema-validated and written to
# contracts/<dataset_slug>/execution-contract.json. The schema is
# `additionalProperties: false` with a fixed required-field shape, so
# `source_artifact_references`/`boundary_confirmations`/positive-label policy
# cannot be embedded in the contract itself; those are recorded instead in a
# companion `execution_contract_materialization_evidence.v1` reduced-evidence
# object returned alongside the contract.
# ---------------------------------------------------------------------------

EXECUTION_CONTRACT_CONTRACT_VERSION = "execution_contract.v1"
EXECUTION_CONTRACT_MATERIALIZATION_EVIDENCE_CONTRACT_VERSION = (
    "execution_contract_materialization_evidence.v1"
)

# Mirrors pipeline/discovery_evidence.py._RESOLVED_TRANSFORMATION_REVIEW_STATUSES.
# If that module's constant changes, this constant must be updated to match.
_RESOLVED_TRANSFORMATION_REVIEW_STATUSES = frozenset({"explicit", "inferred_approved"})

# Mirrors pipeline/validate_contract_consistency.py._COMPAT, inverted: maps a
# discovery inferred_type to the single execution_contract.v1 feature type it
# is compatible with. Kept in sync manually -- no automatic synchronization.
_INFERRED_TYPE_TO_FEATURE_TYPE = {
    "integer": "numeric",
    "float": "numeric",
    "string": "categorical",
    "boolean": "boolean",
}

EXECUTION_CONTRACT_BOUNDARY_CONFIRMATIONS = {
    "is_runtime_contract": False,
    "is_public_contract": False,
    "is_release_candidate_input": False,
    "is_publisher_input": False,
    "is_registry_artifact": False,
    "is_api_fixture": False,
    "is_ui_fixture": False,
    "model_training_performed": False,
    "model_family_selected": False,
}

# Training-policy fields this materialization populates with conservative,
# disclosed repository-standard defaults whenever the upstream modeling
# intent supplies no reviewed value for them (e.g. `metric_candidates: []`,
# `split_policy_candidate: null`). Listed explicitly in the materialization
# evidence rather than silently presented as reviewed policy.
_POLICY_DEFAULT_FIELDS = (
    "categorical_encoding_policy",
    "numeric_handling",
    "allowed_transformations",
    "split_policy",
    "primary_metric",
    "secondary_metrics",
    "modeling_constraints",
)


CATEGORICAL_DOMAIN_APPROVED_STATUS = "approved"


def _validate_categorical_domain_declaration(
    entry: dict[str, Any],
    feature_columns: list[str],
    feature_definitions: dict[str, Any],
) -> tuple[list[str] | None, str | None]:
    """Validate a single reviewed categorical-domain declaration (Project Spec S0102).

    Returns `(values, None)` when `entry` is a well-formed, approved
    declaration for an active categorical feature; returns `(None, reason)`
    otherwise. Never raises -- an invalid or unresolved declaration is a
    normal, reportable outcome (rejected/unresolved), not an exceptional one.
    Re-validates the declaration's own shape independently of
    `pipeline.discovery_evidence.build_categorical_domain_declaration`, since
    a hand-built `dataset_modeling_intent` (e.g. in tests, or an unreviewed
    upstream artifact) may not have gone through that builder.
    """
    name = entry.get("name")
    if not name or not isinstance(name, str):
        return None, "declaration is missing a valid, non-empty feature name"
    if name not in feature_columns:
        return None, f"{name}: not an active feature column (ignored, target, or unknown column)"
    feature_type = feature_definitions.get(name, {}).get("type")
    if feature_type != "categorical":
        return None, f"{name}: declared feature type is {feature_type!r}, not categorical"
    if entry.get("review_status") != CATEGORICAL_DOMAIN_APPROVED_STATUS:
        return None, (
            f"{name}: review_status is {entry.get('review_status')!r}, not "
            f"{CATEGORICAL_DOMAIN_APPROVED_STATUS!r}"
        )
    values = entry.get("accepted_values")
    if not values or not isinstance(values, list):
        return None, f"{name}: accepted_values must be a non-empty list"
    if any(not isinstance(v, str) or v.strip() == "" for v in values):
        return None, f"{name}: accepted_values must be non-blank strings"
    if len(set(values)) != len(values):
        return None, f"{name}: accepted_values must not contain duplicate values"
    return list(values), None


def _unresolved_review_columns(preparation_recipe: dict[str, Any] | None) -> dict[str, str]:
    """Columns with a missing-value-handling transformation whose
    review_status is not 'explicit'/'inferred_approved'.

    Mirrors the dataset_modeling_intent blank-value-policy-candidate
    convention: a column is only ever treated as resolved when the
    preparation recipe itself recorded an approved review_status.
    """
    unresolved: dict[str, str] = {}
    for transformation in (preparation_recipe or {}).get("transformations", []):
        if transformation.get("transformation_type") != "missing_value_handling":
            continue
        review_status = transformation.get("review_status")
        if review_status in _RESOLVED_TRANSFORMATION_REVIEW_STATUSES:
            continue
        for column in transformation.get("target_columns", []):
            unresolved[column] = review_status
    return unresolved


# Project Spec S0108: materialize a reviewed, approved binary_result_semantics_intent
# from the modeling intent into a normalized result_semantics block on the
# execution contract. Never trusts the modeling intent's own prior
# validation -- re-validates independently via
# discovery_evidence.build_binary_result_semantics_intent, mirroring the
# _validate_categorical_domain_declaration re-validation convention above.
_BINARY_RESULT_SEMANTICS_SCHEMA_VERSION = "binary-result-semantics.v1"


def _materialize_binary_result_semantics(
    modeling_intent: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Return (result_semantics_or_None, materialization_evidence).

    `result_semantics` is None whenever the modeling intent's
    `binary_result_semantics_intent` is absent, not approved, or fails
    independent re-validation -- the execution contract as a whole is still
    built successfully in every case; this only omits the optional
    `result_semantics` block rather than blocking materialization of the
    whole contract. Never infers or defaults any field.
    """
    intent = modeling_intent.get("binary_result_semantics_intent")
    if not isinstance(intent, dict):
        return None, {
            "reviewed_source_intent_present": False,
            "positive_class": None,
            "threshold": None,
            "bands": None,
            "no_defaults_inferred": True,
            "readiness": "not_materialized",
            "blocking_reasons": [
                "binary_result_semantics_intent is absent from the dataset modeling intent"
            ],
        }

    review_status = intent.get("review_status")
    if review_status != "approved":
        return None, {
            "reviewed_source_intent_present": True,
            "positive_class": None,
            "threshold": None,
            "bands": None,
            "no_defaults_inferred": True,
            "readiness": "not_materialized",
            "blocking_reasons": [
                f"binary_result_semantics_intent.review_status is {review_status!r}, "
                "not 'approved'"
            ],
        }

    positive_class = intent.get("positive_class") or {}
    interpretation = intent.get("interpretation") or {}
    decision = intent.get("decision") or {}
    try:
        rebuilt = build_binary_result_semantics_intent(
            review_status=review_status,
            problem_type=intent.get("problem_type"),
            positive_class_id=positive_class.get("class_id"),
            event_label=positive_class.get("event_label"),
            primary_output=intent.get("primary_output"),
            threshold=decision.get("threshold"),
            preset=interpretation.get("preset"),
            bands=interpretation.get("bands") or [],
        )
    except ValueError as exc:
        return None, {
            "reviewed_source_intent_present": True,
            "positive_class": None,
            "threshold": None,
            "bands": None,
            "no_defaults_inferred": True,
            "readiness": "not_materialized",
            "blocking_reasons": [
                f"binary_result_semantics_intent failed independent re-validation: {exc}"
            ],
        }

    result_semantics = {
        "schema_version": _BINARY_RESULT_SEMANTICS_SCHEMA_VERSION,
        "problem_type": rebuilt["problem_type"],
        "positive_class": dict(rebuilt["positive_class"]),
        "primary_output": rebuilt["primary_output"],
        "decision": dict(rebuilt["decision"]),
        "interpretation": {
            "preset": rebuilt["interpretation"]["preset"],
            "bands": [dict(band) for band in rebuilt["interpretation"]["bands"]],
        },
    }
    evidence = {
        "reviewed_source_intent_present": True,
        "positive_class": dict(result_semantics["positive_class"]),
        "threshold": result_semantics["decision"]["threshold"],
        "bands": [dict(band) for band in result_semantics["interpretation"]["bands"]],
        "no_defaults_inferred": True,
        "readiness": "materialized",
        "blocking_reasons": [],
    }
    return result_semantics, evidence


def _build_execution_contract(
    modeling_intent: dict[str, Any],
    discovery_evidence: dict[str, Any],
    preparation_recipe: dict[str, Any] | None,
) -> dict[str, Any]:
    """Pure projection of upstream artifacts into an execution_contract.v1 dict.

    A feature candidate is excluded from `feature_columns` (moved into
    `ignored_columns`) when either: it is an identifier
    (`identifier_and_ignored_columns`), or discovery evidence has no
    recognised `inferred_type` for it, or an unresolved (not
    'explicit'/'inferred_approved') missing-value-handling review item names
    it -- this is how a still-pending blank-value concern (e.g.
    TotalCharges) is excluded from execution scope instead of being silently
    approved. Per-feature `type` is grounded in discovery evidence's own
    `inferred_type`, using the same compatibility mapping enforced by
    `pipeline/validate_contract_consistency.py`, so a materialized contract
    always passes that consistency check by construction.
    """
    dataset_identity = modeling_intent.get("dataset_identity") or {}
    target_intent = modeling_intent.get("target_intent") or {}
    target_column = target_intent.get("target_column")

    identifier_columns = [
        entry["name"]
        for entry in modeling_intent.get("identifier_and_ignored_columns") or []
    ]

    obs_by_name = {
        obs["name"]: obs for obs in discovery_evidence.get("field_observations", [])
    }

    unresolved_review_columns = _unresolved_review_columns(preparation_recipe)
    candidate_features = list(modeling_intent.get("initial_feature_candidates") or [])

    feature_columns: list[str] = []
    excluded_for_review: list[str] = []
    excluded_for_unrecognised_type: list[str] = []
    for name in candidate_features:
        if name in identifier_columns:
            continue
        if name in unresolved_review_columns:
            excluded_for_review.append(name)
            continue
        obs = obs_by_name.get(name)
        if obs is None or obs.get("inferred_type") not in _INFERRED_TYPE_TO_FEATURE_TYPE:
            excluded_for_unrecognised_type.append(name)
            continue
        feature_columns.append(name)

    ignored_columns = identifier_columns + excluded_for_review + excluded_for_unrecognised_type

    feature_definitions: dict[str, Any] = {}
    required_columns: list[str] = []
    optional_columns: list[str] = []
    for name in feature_columns:
        obs = obs_by_name[name]
        feature_type = _INFERRED_TYPE_TO_FEATURE_TYPE[obs["inferred_type"]]
        definition: dict[str, Any] = {"type": feature_type}
        if (
            feature_type == "numeric"
            and obs.get("sample_min") is not None
            and obs.get("sample_max") is not None
        ):
            definition["domain_constraints"] = {
                "min": obs["sample_min"],
                "max": obs["sample_max"],
            }
        feature_definitions[name] = definition
        if obs.get("null_rate") or 0:
            optional_columns.append(name)
        else:
            required_columns.append(name)

    # Project Spec S0102: materialize approved, reviewed categorical-domain
    # declarations into feature_definitions[name].domain_constraints.values.
    # An invalid or unapproved declaration is never applied -- it is simply
    # not materialized here; the accompanying materialization evidence (see
    # _build_execution_contract_materialization_evidence) independently
    # re-derives and names every rejected/unresolved case for disclosure.
    for entry in modeling_intent.get("categorical_domain_intent") or []:
        values, _rejection_reason = _validate_categorical_domain_declaration(
            entry, feature_columns, feature_definitions
        )
        if values is not None:
            feature_definitions[entry["name"]]["domain_constraints"] = {"values": values}

    seed = (discovery_evidence.get("generation_settings") or {}).get("seed")

    # Project Spec S0108: materialize a reviewed, approved
    # binary_result_semantics_intent into a normalized result_semantics
    # block. Omitted entirely (never present-but-null) when absent, pending,
    # or invalid -- this is what "blocks executable materialization" means
    # for this optional, backward-compatible field.
    result_semantics, _result_semantics_evidence = _materialize_binary_result_semantics(
        modeling_intent
    )

    contract: dict[str, Any] = {
        "contract_version": EXECUTION_CONTRACT_CONTRACT_VERSION,
        "dataset_id": dataset_identity.get("dataset_slug"),
        "target_column": target_column,
        "feature_columns": feature_columns,
        "ignored_columns": ignored_columns,
        "required_columns": required_columns,
        "optional_columns": optional_columns,
        "feature_definitions": feature_definitions,
        # No feature currently carries an approved missing-value strategy --
        # TotalCharges (the only column with real missing values) is excluded
        # from feature_columns above rather than assigned a fabricated
        # strategy here.
        "missing_value_policy": {},
        "categorical_encoding_policy": "onehot",
        "numeric_handling": "standardize",
        "allowed_transformations": ["passthrough"],
        "split_policy": {
            "strategy": "stratified",
            "train_ratio": 0.7,
            "val_ratio": 0.15,
            "test_ratio": 0.15,
        },
        "random_seed": seed if isinstance(seed, int) else None,
        "primary_metric": "roc_auc",
        "secondary_metrics": ["f1", "pr_auc"],
        "modeling_constraints": {
            # Full schema-permitted family space -- modeling_intent records
            # no model family constraint (`metric_candidates: []`), so this
            # deliberately narrows nothing beyond what the schema itself
            # already scopes to Atlas classification families, rather than
            # selecting a specific model family or candidate.
            "allowed_model_families": [
                "logistic_regression",
                "gradient_boosting",
                "random_forest",
                "xgboost",
                "lightgbm",
            ],
            "no_automl": True,
            "max_training_time_seconds": None,
        },
    }
    if result_semantics is not None:
        contract["result_semantics"] = result_semantics
    return contract


def _build_execution_contract_materialization_evidence(
    modeling_intent: dict[str, Any],
    preparation_recipe: dict[str, Any] | None,
    execution_contract: dict[str, Any],
    *,
    execution_contract_relative_path: str,
    discovery_evidence_relative_path: str | Path | None,
    preparation_recipe_relative_path: str | Path | None,
    prepared_data_metadata_relative_path: str | Path | None,
    modeling_intent_relative_path: str | Path | None,
    public_context_relative_path: str | Path | None,
    raw_dataset_relative_path: str | Path | None,
    generated_at: str | None,
) -> dict[str, Any]:
    """Reduced evidence recording facts the schema-locked execution contract
    has no room for: source artifact references, positive-label policy,
    identifier/unresolved-feature exclusion rationale, per-feature type
    grounding, and boundary confirmations.
    """
    dataset_identity = modeling_intent.get("dataset_identity") or {}
    target_intent = modeling_intent.get("target_intent") or {}
    unresolved_review_columns = _unresolved_review_columns(preparation_recipe)
    candidate_features = set(modeling_intent.get("initial_feature_candidates") or [])

    identifier_exclusion_policy = [
        {"name": entry["name"], "reason": entry.get("reason")}
        for entry in modeling_intent.get("identifier_and_ignored_columns") or []
    ]

    unresolved_feature_exclusions = [
        {
            "name": name,
            "review_status": review_status,
            "reason": (
                "blank-value handling review_status is "
                f"{review_status!r}, not an approved status "
                f"({sorted(_RESOLVED_TRANSFORMATION_REVIEW_STATUSES)}); excluded "
                "from feature_columns rather than silently approved"
            ),
        }
        for name, review_status in sorted(unresolved_review_columns.items())
        if name in candidate_features
    ]

    feature_type_grounding = {
        name: {
            "declared_type": definition["type"],
            "grounded_from": "discovery_evidence.field_observations[].inferred_type",
        }
        for name, definition in execution_contract["feature_definitions"].items()
    }

    # Project Spec S0102: reduced categorical-domain coverage. Independently
    # re-derived from the final execution_contract + the modeling intent's own
    # categorical_domain_intent, rather than trusted from hidden state set
    # during _build_execution_contract -- mirrors the existing
    # _unresolved_review_columns re-derivation convention used above.
    categorical_feature_names = sorted(
        name
        for name, definition in execution_contract["feature_definitions"].items()
        if definition.get("type") == "categorical"
    )
    approved_categorical_domains = sorted(
        name
        for name in categorical_feature_names
        if execution_contract["feature_definitions"][name].get("domain_constraints", {}).get("values")
    )
    unresolved_categorical_features = sorted(
        set(categorical_feature_names) - set(approved_categorical_domains)
    )
    rejected_categorical_domain_declarations = []
    for entry in modeling_intent.get("categorical_domain_intent") or []:
        entry_name = entry.get("name")
        if entry_name in approved_categorical_domains:
            continue
        _values, rejection_reason = _validate_categorical_domain_declaration(
            entry,
            execution_contract["feature_columns"],
            execution_contract["feature_definitions"],
        )
        if rejection_reason is not None:
            rejected_categorical_domain_declarations.append(
                {"name": entry_name, "reason": rejection_reason}
            )

    # Project Spec S0108: independently re-derived (never trusted from hidden
    # state set during _build_execution_contract), mirroring the categorical
    # domain re-derivation convention above.
    _result_semantics, result_semantics_evidence = _materialize_binary_result_semantics(
        modeling_intent
    )

    return {
        "artifact_type": "execution_contract_materialization_evidence",
        "contract_version": EXECUTION_CONTRACT_MATERIALIZATION_EVIDENCE_CONTRACT_VERSION,
        "dataset_identity": dict(dataset_identity),
        "execution_contract_ref": str(execution_contract_relative_path),
        "source_artifact_references": {
            "discovery_evidence_ref": (
                str(discovery_evidence_relative_path)
                if discovery_evidence_relative_path
                else None
            ),
            "preparation_recipe_ref": (
                str(preparation_recipe_relative_path)
                if preparation_recipe_relative_path
                else None
            ),
            "prepared_data_metadata_ref": (
                str(prepared_data_metadata_relative_path)
                if prepared_data_metadata_relative_path
                else None
            ),
            "dataset_modeling_intent_ref": (
                str(modeling_intent_relative_path) if modeling_intent_relative_path else None
            ),
            "public_context_ref": (
                str(public_context_relative_path) if public_context_relative_path else None
            ),
            "raw_dataset_ref": (
                str(raw_dataset_relative_path) if raw_dataset_relative_path else None
            ),
        },
        "target_policy": {
            "target_column": target_intent.get("target_column"),
            "task_type": target_intent.get("task_type"),
        },
        "positive_label_policy": {
            "positive_label_candidate": target_intent.get("positive_label_candidate"),
            "observed_labels": list(target_intent.get("observed_labels") or []),
            "is_reviewed_final_decision": False,
        },
        "identifier_exclusion_policy": identifier_exclusion_policy,
        "unresolved_feature_exclusions": unresolved_feature_exclusions,
        "feature_type_grounding": feature_type_grounding,
        "categorical_domain_materialization": {
            "approved_categorical_domains": approved_categorical_domains,
            "unresolved_categorical_features": unresolved_categorical_features,
            "rejected_categorical_domain_declarations": rejected_categorical_domain_declarations,
            "values_inferred_during_materialization": False,
        },
        "policy_defaults_requiring_future_review": list(_POLICY_DEFAULT_FIELDS),
        "result_semantics_materialization": result_semantics_evidence,
        "execution_contract_boundary_confirmations": dict(EXECUTION_CONTRACT_BOUNDARY_CONFIRMATIONS),
        "generated_at": generated_at or _utc_now_iso(),
    }


def materialize_execution_contract(
    modeling_intent: dict[str, Any],
    discovery_evidence: dict[str, Any],
    output_relative_path: str | Path,
    repo_root: str | Path,
    preparation_recipe: dict[str, Any] | None = None,
    evidence_output_relative_path: str | Path | None = None,
    discovery_evidence_relative_path: str | Path | None = None,
    preparation_recipe_relative_path: str | Path | None = None,
    prepared_data_metadata_relative_path: str | Path | None = None,
    modeling_intent_relative_path: str | Path | None = None,
    public_context_relative_path: str | Path | None = None,
    raw_dataset_relative_path: str | Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build, schema-validate, and write the official Telco execution contract.

    Every field is read from already-built upstream objects
    (`modeling_intent`, `discovery_evidence`, `preparation_recipe`) passed in
    explicitly -- never from raw dataset rows or hidden notebook state.
    Raises RuntimeError if the built contract fails validation against
    contracts/execution-contract.schema.json; an invalid contract is never
    written to disk. Also builds (and, when a path is supplied, writes) a
    companion `execution_contract_materialization_evidence.v1` object.

    Returns {"execution_contract": ..., "execution_contract_materialization_evidence": ...}.
    """
    resolved_repo_root = Path(repo_root).expanduser().resolve()

    execution_contract = _build_execution_contract(
        modeling_intent, discovery_evidence, preparation_recipe
    )

    schema_path = resolved_repo_root / "contracts" / "execution-contract.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema_errors = _validate_schema(execution_contract, schema)
    if schema_errors:
        raise RuntimeError(
            "Materialized execution contract failed schema validation: "
            + "; ".join(schema_errors)
        )

    output_path = (resolved_repo_root / output_relative_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(execution_contract, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    evidence = _build_execution_contract_materialization_evidence(
        modeling_intent,
        preparation_recipe,
        execution_contract,
        execution_contract_relative_path=output_relative_path,
        discovery_evidence_relative_path=discovery_evidence_relative_path,
        preparation_recipe_relative_path=preparation_recipe_relative_path,
        prepared_data_metadata_relative_path=prepared_data_metadata_relative_path,
        modeling_intent_relative_path=modeling_intent_relative_path,
        public_context_relative_path=public_context_relative_path,
        raw_dataset_relative_path=raw_dataset_relative_path,
        generated_at=generated_at,
    )

    if evidence_output_relative_path is not None:
        evidence_output_path = (resolved_repo_root / evidence_output_relative_path).resolve()
        evidence_output_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_output_path.write_text(
            json.dumps(evidence, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    return {
        "execution_contract": execution_contract,
        "execution_contract_materialization_evidence": evidence,
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
