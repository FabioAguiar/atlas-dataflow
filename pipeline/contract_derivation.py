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

This module also exposes `project_capability_aware_source_contract`
(Project Spec S0167): a capability-aware bridge from a
`source-contract-input.v1` instance carrying the additive
`authoring_manifest_ref`/`capability_profile_*` fields into this same
runtime->public projection, gated by the Project Spec S0166 authoring
boundary (`pipeline/authoring_contracts.validate_authoring_contracts`) and
the resolved capability profile's `support_status`. It never derives new
capability-specific projection behavior itself -- for the currently
supported `binary-predictive-classification` capability it reuses the
runtime->public projection above unchanged, and for every other capability
(including a syntactically valid but unsupported profile) it fails closed
with a typed `CapabilityProjectionResult` rather than fabricating a
contract. Contains no dataset-slug or dataset-name conditional anywhere.
"""

import argparse
import hashlib
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline.authoring_contracts import validate_authoring_contracts
from pipeline.discovery_evidence import (
    build_binary_result_semantics_intent,
    build_continuous_regression_result_semantics_intent,
    build_multiclass_result_semantics_intent,
)


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
    return str(name).replace("_", " ").replace("-", " ").title()


# Project Spec S0156: shared categorical/conditional-policy helpers, reused by
# pipeline/derive_projections.py and pipeline/validate_contract_consistency.py
# so the scalar-type/condition-compatibility rules are defined exactly once.

def categorical_scalar_type(domain_constraints):
    """Resolve the declared scalar type ("string" or "integer") of a
    categorical feature's domain_constraints. Defaults to "string" when
    domain_constraints is absent/malformed or only declares the legacy
    'values' vocabulary, matching current/legacy string-only behavior.
    """
    if not isinstance(domain_constraints, dict):
        return "string"
    declared = domain_constraints.get("categorical_value_type")
    if declared in ("string", "integer"):
        return declared
    return "string"


def categorical_known_values(domain_constraints):
    """Return the effective known-values list (known_values, falling back to
    the legacy 'values' vocabulary), or None when neither is declared."""
    if not isinstance(domain_constraints, dict):
        return None
    known_values = domain_constraints.get("known_values")
    if known_values is not None:
        return known_values
    return domain_constraints.get("values")


def categorical_validation_behavior(domain_constraints):
    """Return the effective validation_behavior, defaulting to
    "reject_unknown" (the existing closed-domain behavior) when absent --
    Project Spec S0156 requires missing validation_behavior on legacy
    categorical definitions to preserve existing closed behavior."""
    if not isinstance(domain_constraints, dict):
        return "reject_unknown"
    behavior = domain_constraints.get("validation_behavior")
    if behavior in ("reject_unknown", "ignore_and_report"):
        return behavior
    return "reject_unknown"


def condition_value_type_compatible(value, referenced_type, referenced_definition):
    """Whether an equality_condition.value is compatible with the declared
    scalar type of the feature it references (Project Spec S0156)."""
    if referenced_type == "numeric":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if referenced_type == "boolean":
        return isinstance(value, bool)
    if referenced_type == "categorical":
        scalar_type = categorical_scalar_type((referenced_definition or {}).get("domain_constraints"))
        if scalar_type == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        return isinstance(value, str)
    return False


def conditional_policy_errors(feature_columns, feature_definitions):
    """Validate every declared input_policy.conditional_blank_normalization
    across feature_definitions (Project Spec S0156): the condition field
    must be another declared feature, must not self-reference, and its
    comparison value must be compatible with the referenced feature's
    declared scalar type. Returns a list of human-readable error strings
    (empty when every declared policy is valid). Never raises.
    """
    errors: list[str] = []
    for name in feature_columns:
        defn = feature_definitions.get(name, {})
        input_policy = defn.get("input_policy")
        if not isinstance(input_policy, dict):
            continue
        conditional = input_policy.get("conditional_blank_normalization")
        if not isinstance(conditional, dict):
            continue
        when = conditional.get("when")
        if not isinstance(when, dict):
            continue
        ref_field = when.get("field")
        ref_value = when.get("value")
        if ref_field == name:
            errors.append(
                f'feature "{name}": conditional_blank_normalization.when.field must not reference itself'
            )
            continue
        if ref_field not in feature_columns:
            errors.append(
                f'feature "{name}": conditional_blank_normalization.when.field '
                f'"{ref_field}" is not a declared feature column'
            )
            continue
        ref_defn = feature_definitions.get(ref_field, {})
        ref_type = ref_defn.get("type")
        if not condition_value_type_compatible(ref_value, ref_type, ref_defn):
            errors.append(
                f'feature "{name}": conditional_blank_normalization.when.value is '
                f'incompatible with referenced feature "{ref_field}" declared scalar type'
            )
    return errors


def _derive_public_options(feature):
    """Derive a safe options projection for a categorical feature, or None.

    Returns a list of {value, label} dicts sourced from a non-empty
    domain_constraints.values or known_values (Project Spec S0156), in
    source declaration order. Returns None (absence, never an empty list)
    when the feature is not categorical, or has no domain_constraints, or
    has an empty values/known_values list.
    """
    if feature["type"] != "categorical":
        return None
    values = categorical_known_values(feature.get("domain_constraints"))
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
    # Project Spec S0156: bounded select serialization hint, categorical
    # features only -- carries the runtime categorical scalar type forward
    # so the web experience serializes integer selects correctly.
    if feature["type"] == "categorical":
        public["select_value_type"] = categorical_scalar_type(feature.get("domain_constraints"))
    # Project Spec S0156: presentation-only conditional blank policy metadata.
    # Never carries the condition field/operator/comparison value or the
    # materialized value -- the backend remains the sole evaluator.
    input_policy = feature.get("input_policy")
    if isinstance(input_policy, dict):
        conditional = input_policy.get("conditional_blank_normalization")
        if isinstance(conditional, dict) and conditional.get("accepted_representation"):
            public["conditional_blank_policy"] = {
                "accepted_representation": conditional["accepted_representation"]
            }
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


# ---------------------------------------------------------------------------
# Reviewed native training policy validation and materialization
# (Project Spec S0216)
#
# `_validate_training_policy_intent` strictly validates an optional, reviewed
# `training_policy_intent` object (`pipeline.discovery_evidence
# .build_dataset_modeling_intent`'s optional field) before it may ever
# replace `_POLICY_DEFAULT_FIELDS`'s repository-standard defaults. Either the
# complete approved policy is accepted (every execution-only field present
# and schema-compatible) or it is rejected outright with a concrete reason --
# there is no partial/field-by-field fallback from a partially supplied
# approved policy. Absence of `training_policy_intent` entirely is not a
# validation failure; that is the existing, unchanged legacy-defaults path
# (`_build_execution_contract`) and this validator is never consulted for it.
# ---------------------------------------------------------------------------

_TRAINING_POLICY_METRIC_VOCABULARY = frozenset({
    "roc_auc", "f1", "accuracy", "log_loss", "pr_auc", "average_precision",
    "precision", "recall", "f2", "balanced_accuracy", "brier_score",
    "f1_macro", "f1_weighted", "precision_macro", "recall_macro",
    "r2", "mae", "rmse",
})
_TRAINING_POLICY_MODEL_FAMILY_VOCABULARY = frozenset({
    "logistic_regression", "gradient_boosting", "random_forest",
    "xgboost", "lightgbm", "hist_gradient_boosting",
})
_TRAINING_POLICY_NUMERIC_HANDLING_VOCABULARY = frozenset({"standardize", "normalize", "passthrough"})
_TRAINING_POLICY_CATEGORICAL_ENCODING_VOCABULARY = frozenset({"onehot", "ordinal", "target_encode", "binary"})
_TRAINING_POLICY_TRANSFORMATION_VOCABULARY = frozenset({"log1p", "sqrt", "clip", "passthrough"})
_TRAINING_POLICY_SPLIT_STRATEGY_VOCABULARY = frozenset({"stratified", "random"})
_TRAINING_POLICY_SELECTION_MODE_VOCABULARY = frozenset({"evaluate_allowed_families", "fixed_configuration"})

# Project Spec S0216: the only bounded fixed-parameter family this
# validator (and pipeline/training.py's native estimator construction)
# currently recognizes. A future family requires a new, separately
# authorized whitelist -- never an ad hoc extension here.
_HGB_REQUIRED_HYPERPARAMETERS = frozenset({
    "class_weight", "l2_regularization", "learning_rate", "max_iter", "max_leaf_nodes", "min_samples_leaf",
})
_HGB_OPTIONAL_HYPERPARAMETERS = frozenset({"early_stopping"})
_HGB_ALLOWED_HYPERPARAMETERS = _HGB_REQUIRED_HYPERPARAMETERS | _HGB_OPTIONAL_HYPERPARAMETERS

# Project Spec S0224: the two bounded fixed-parameter families this
# validator (and pipeline/training.py's native regression estimator
# construction) currently recognizes for continuous regression. A future
# family requires a new, separately authorized whitelist -- never an ad hoc
# extension here.
_GBR_REQUIRED_HYPERPARAMETERS = frozenset({
    "n_estimators", "learning_rate", "max_depth", "min_samples_leaf", "subsample", "loss",
})
_GBR_ALLOWED_HYPERPARAMETERS = _GBR_REQUIRED_HYPERPARAMETERS
_RFR_REQUIRED_HYPERPARAMETERS = frozenset({
    "n_estimators", "max_depth", "min_samples_leaf", "max_features", "bootstrap",
})
_RFR_ALLOWED_HYPERPARAMETERS = _RFR_REQUIRED_HYPERPARAMETERS
_CONTINUOUS_REGRESSION_METRIC_VOCABULARY = frozenset({"r2", "mae", "rmse"})
_CONTINUOUS_REGRESSION_FIXED_FAMILY_VOCABULARY = frozenset({"gradient_boosting", "random_forest"})

TRAINING_POLICY_REQUIRED_FIELDS = (
    "review_status",
    "numeric_handling",
    "categorical_encoding_policy",
    "allowed_transformations",
    "split_policy",
    "primary_metric",
    "secondary_metrics",
    "modeling_constraints",
)


class TrainingPolicyValidationError(ValueError):
    """Raised when a supplied `training_policy_intent` is present but not a
    complete, approved, schema-compatible reviewed native training policy.

    Never raised for an absent `training_policy_intent` on a binary/
    multiclass execution contract -- that case uses the unchanged legacy
    derivation defaults instead. Project Spec S0223 adds the one exception:
    an absent `training_policy_intent` alongside a present
    `continuous_regression_result_semantics_intent` also raises this error,
    since continuous regression can never inherit the legacy classification
    training defaults.
    """

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = list(reasons)
        super().__init__("training_policy_intent failed strict validation: " + "; ".join(reasons))


def _validate_hgb_hyperparameters(hyperparameters: Any) -> list[str]:
    reasons: list[str] = []
    if not isinstance(hyperparameters, dict):
        return ["fixed_model_configuration.hyperparameters must be an object"]
    missing = _HGB_REQUIRED_HYPERPARAMETERS - set(hyperparameters)
    if missing:
        reasons.append(
            f"fixed_model_configuration.hyperparameters is missing required fields: {sorted(missing)}"
        )
    unsupported = set(hyperparameters) - _HGB_ALLOWED_HYPERPARAMETERS
    if unsupported:
        reasons.append(f"unsupported HGB hyperparameter(s): {sorted(unsupported)}")
    if "class_weight" in hyperparameters and hyperparameters["class_weight"] not in (None, "balanced"):
        reasons.append("hyperparameters.class_weight must be null or 'balanced'")
    if "l2_regularization" in hyperparameters:
        value = hyperparameters["l2_regularization"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            reasons.append("hyperparameters.l2_regularization must be a number >= 0")
    if "learning_rate" in hyperparameters:
        value = hyperparameters["learning_rate"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            reasons.append("hyperparameters.learning_rate must be a number > 0")
    if "max_iter" in hyperparameters:
        value = hyperparameters["max_iter"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            reasons.append("hyperparameters.max_iter must be an integer >= 1")
    if "max_leaf_nodes" in hyperparameters:
        value = hyperparameters["max_leaf_nodes"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 2:
            reasons.append("hyperparameters.max_leaf_nodes must be an integer >= 2")
    if "min_samples_leaf" in hyperparameters:
        value = hyperparameters["min_samples_leaf"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            reasons.append("hyperparameters.min_samples_leaf must be an integer >= 1")
    if "early_stopping" in hyperparameters and hyperparameters["early_stopping"] not in ("auto", True, False):
        reasons.append("hyperparameters.early_stopping must be 'auto' or a boolean")
    return reasons


def _validate_gradient_boosting_regression_hyperparameters(hyperparameters: Any) -> list[str]:
    reasons: list[str] = []
    if not isinstance(hyperparameters, dict):
        return ["fixed_model_configuration.hyperparameters must be an object"]
    missing = _GBR_REQUIRED_HYPERPARAMETERS - set(hyperparameters)
    if missing:
        reasons.append(
            f"fixed_model_configuration.hyperparameters is missing required fields: {sorted(missing)}"
        )
    unsupported = set(hyperparameters) - _GBR_ALLOWED_HYPERPARAMETERS
    if unsupported:
        reasons.append(f"unsupported gradient_boosting regression hyperparameter(s): {sorted(unsupported)}")
    if "n_estimators" in hyperparameters:
        value = hyperparameters["n_estimators"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            reasons.append("hyperparameters.n_estimators must be an integer >= 1")
    if "learning_rate" in hyperparameters:
        value = hyperparameters["learning_rate"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            reasons.append("hyperparameters.learning_rate must be a number > 0")
    if "max_depth" in hyperparameters:
        value = hyperparameters["max_depth"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            reasons.append("hyperparameters.max_depth must be an integer >= 1")
    if "min_samples_leaf" in hyperparameters:
        value = hyperparameters["min_samples_leaf"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            reasons.append("hyperparameters.min_samples_leaf must be an integer >= 1")
    if "subsample" in hyperparameters:
        value = hyperparameters["subsample"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not (0 < value <= 1):
            reasons.append("hyperparameters.subsample must be a number > 0 and <= 1")
    if "loss" in hyperparameters and hyperparameters["loss"] != "squared_error":
        reasons.append("hyperparameters.loss must be 'squared_error'")
    return reasons


def _validate_random_forest_regression_hyperparameters(hyperparameters: Any) -> list[str]:
    reasons: list[str] = []
    if not isinstance(hyperparameters, dict):
        return ["fixed_model_configuration.hyperparameters must be an object"]
    missing = _RFR_REQUIRED_HYPERPARAMETERS - set(hyperparameters)
    if missing:
        reasons.append(
            f"fixed_model_configuration.hyperparameters is missing required fields: {sorted(missing)}"
        )
    unsupported = set(hyperparameters) - _RFR_ALLOWED_HYPERPARAMETERS
    if unsupported:
        reasons.append(f"unsupported random_forest regression hyperparameter(s): {sorted(unsupported)}")
    if "n_estimators" in hyperparameters:
        value = hyperparameters["n_estimators"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            reasons.append("hyperparameters.n_estimators must be an integer >= 1")
    if "max_depth" in hyperparameters:
        value = hyperparameters["max_depth"]
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
            reasons.append("hyperparameters.max_depth must be an integer >= 1 or null")
    if "min_samples_leaf" in hyperparameters:
        value = hyperparameters["min_samples_leaf"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            reasons.append("hyperparameters.min_samples_leaf must be an integer >= 1")
    if "max_features" in hyperparameters and hyperparameters["max_features"] not in ("sqrt", "log2", None):
        reasons.append("hyperparameters.max_features must be 'sqrt', 'log2', or null")
    if "bootstrap" in hyperparameters and not isinstance(hyperparameters["bootstrap"], bool):
        reasons.append("hyperparameters.bootstrap must be a boolean")
    return reasons


def _validate_modeling_constraints_intent(
    modeling_constraints: Any, *, problem_type_hint: str | None = None
) -> list[str]:
    reasons: list[str] = []
    if not isinstance(modeling_constraints, dict):
        return ["modeling_constraints must be an object"]

    allowed_model_families = modeling_constraints.get("allowed_model_families")
    if not isinstance(allowed_model_families, list) or not allowed_model_families:
        reasons.append("modeling_constraints.allowed_model_families must be a non-empty array")
        allowed_model_families = []
    unknown_families = [
        family for family in allowed_model_families
        if family not in _TRAINING_POLICY_MODEL_FAMILY_VOCABULARY
    ]
    if unknown_families:
        reasons.append(f"unknown model family: {unknown_families}")

    selection_mode = modeling_constraints.get("selection_mode")
    if selection_mode is not None and selection_mode not in _TRAINING_POLICY_SELECTION_MODE_VOCABULARY:
        reasons.append(f"modeling_constraints.selection_mode is unrecognized: {selection_mode!r}")

    # Project Spec S0224: continuous regression can never use the historical
    # evaluate_allowed_families multi-candidate selection strategy -- it
    # always requires an explicit fixed, reviewed configuration.
    if problem_type_hint == "continuous_regression" and selection_mode != "fixed_configuration":
        reasons.append(
            "continuous regression requires modeling_constraints.selection_mode = "
            "fixed_configuration; evaluate_allowed_families is not supported for continuous "
            "regression"
        )

    if selection_mode == "fixed_configuration":
        fixed_model_configuration = modeling_constraints.get("fixed_model_configuration")
        if not isinstance(fixed_model_configuration, dict):
            reasons.append("modeling_constraints.fixed_model_configuration is required for fixed_configuration")
            return reasons
        fixed_family = fixed_model_configuration.get("model_family")
        if len(allowed_model_families) != 1 or (allowed_model_families and allowed_model_families[0] != fixed_family):
            reasons.append(
                "fixed configuration with multiple allowed families, or fixed family not present in "
                "allowed families"
            )
        if problem_type_hint == "continuous_regression":
            if fixed_family == "gradient_boosting":
                reasons.extend(
                    _validate_gradient_boosting_regression_hyperparameters(
                        fixed_model_configuration.get("hyperparameters")
                    )
                )
            elif fixed_family == "random_forest":
                reasons.extend(
                    _validate_random_forest_regression_hyperparameters(
                        fixed_model_configuration.get("hyperparameters")
                    )
                )
            else:
                reasons.append(
                    "continuous regression fixed family must be gradient_boosting or "
                    f"random_forest, got {fixed_family!r}"
                )
        elif fixed_family == "hist_gradient_boosting":
            reasons.extend(
                _validate_hgb_hyperparameters(fixed_model_configuration.get("hyperparameters"))
            )
        elif fixed_family is not None:
            reasons.append(f"fixed family not present in allowed families: {fixed_family!r}")
    elif "fixed_model_configuration" in modeling_constraints:
        reasons.append(
            "modeling_constraints.fixed_model_configuration is only valid when selection_mode is "
            "fixed_configuration"
        )

    return reasons


def _validate_split_policy_intent(split_policy: Any, *, problem_type_hint: str | None = None) -> list[str]:
    reasons: list[str] = []
    if not isinstance(split_policy, dict):
        return ["split_policy must be an object"]
    strategy = split_policy.get("strategy")
    if strategy not in _TRAINING_POLICY_SPLIT_STRATEGY_VOCABULARY:
        reasons.append(f"split_policy.strategy is invalid: {strategy!r}")
    elif problem_type_hint == "continuous_regression" and strategy != "random":
        reasons.append(
            f"continuous regression requires split_policy.strategy = random, got {strategy!r}"
        )
    train_ratio = split_policy.get("train_ratio")
    val_ratio = split_policy.get("val_ratio", 0)
    test_ratio = split_policy.get("test_ratio")
    for name, value in (("train_ratio", train_ratio), ("val_ratio", val_ratio), ("test_ratio", test_ratio)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not (0 <= value <= 1):
            reasons.append(f"split_policy.{name} must be a number within [0, 1]")
    if (
        problem_type_hint == "continuous_regression"
        and not isinstance(val_ratio, bool)
        and isinstance(val_ratio, (int, float))
        and val_ratio <= 0
    ):
        reasons.append("continuous regression requires split_policy.val_ratio > 0")
    if not reasons and not math.isclose(float(train_ratio) + float(val_ratio) + float(test_ratio), 1.0):
        reasons.append("split_policy train_ratio, val_ratio, and test_ratio must sum to 1.0")
    return reasons


def _validate_training_policy_intent(
    training_policy_intent: dict[str, Any], *, problem_type_hint: str | None = None
) -> list[str]:
    """Return a list of blocking reasons for a supplied `training_policy_intent`.

    Empty list means the policy is a complete, approved, schema-compatible
    reviewed native training policy. Never mutates its input; never invents
    a value the intent does not itself declare.

    `problem_type_hint` is `"continuous_regression"` only when the caller has
    independently confirmed a `continuous_regression_result_semantics_intent`
    is present on the modeling intent (Project Spec S0224); it is `None` for
    every binary/multiclass caller, which retains the historical validation
    behavior below completely unchanged.
    """
    reasons: list[str] = []
    missing_fields = [
        field for field in TRAINING_POLICY_REQUIRED_FIELDS if field not in training_policy_intent
    ]
    if missing_fields:
        reasons.append(f"training_policy_intent is missing required fields: {missing_fields}")

    if training_policy_intent.get("review_status") != "approved":
        reasons.append(
            f"unapproved review status: {training_policy_intent.get('review_status')!r}"
        )

    if "numeric_handling" in training_policy_intent:
        if training_policy_intent["numeric_handling"] not in _TRAINING_POLICY_NUMERIC_HANDLING_VOCABULARY:
            reasons.append(f"numeric_handling is invalid: {training_policy_intent['numeric_handling']!r}")

    if "categorical_encoding_policy" in training_policy_intent:
        if training_policy_intent["categorical_encoding_policy"] not in _TRAINING_POLICY_CATEGORICAL_ENCODING_VOCABULARY:
            reasons.append(
                f"categorical_encoding_policy is invalid: {training_policy_intent['categorical_encoding_policy']!r}"
            )

    if "allowed_transformations" in training_policy_intent:
        allowed_transformations = training_policy_intent["allowed_transformations"]
        if not isinstance(allowed_transformations, list):
            reasons.append("allowed_transformations must be an array")
        else:
            unknown = [t for t in allowed_transformations if t not in _TRAINING_POLICY_TRANSFORMATION_VOCABULARY]
            if unknown:
                reasons.append(f"allowed_transformations contains unknown value(s): {unknown}")

    if "split_policy" in training_policy_intent:
        reasons.extend(
            _validate_split_policy_intent(
                training_policy_intent["split_policy"], problem_type_hint=problem_type_hint
            )
        )

    metric_vocabulary = (
        _CONTINUOUS_REGRESSION_METRIC_VOCABULARY
        if problem_type_hint == "continuous_regression"
        else _TRAINING_POLICY_METRIC_VOCABULARY
    )

    if "primary_metric" in training_policy_intent:
        primary_metric = training_policy_intent["primary_metric"]
        if primary_metric not in metric_vocabulary:
            reasons.append(f"unknown metric: {primary_metric!r}")

    if "secondary_metrics" in training_policy_intent:
        secondary_metrics = training_policy_intent["secondary_metrics"]
        if not isinstance(secondary_metrics, list):
            reasons.append("secondary_metrics must be an array")
        else:
            unknown_metrics = [m for m in secondary_metrics if m not in metric_vocabulary]
            if unknown_metrics:
                reasons.append(f"unknown metric: {unknown_metrics}")

    if "modeling_constraints" in training_policy_intent:
        reasons.extend(
            _validate_modeling_constraints_intent(
                training_policy_intent["modeling_constraints"], problem_type_hint=problem_type_hint
            )
        )

    return reasons


def _materialize_training_policy_fields(modeling_intent: dict[str, Any]) -> dict[str, Any] | None:
    """Return the materialized execution-only policy fields from a modeling
    intent's `training_policy_intent`, or None when absent.

    Raises `TrainingPolicyValidationError` when `training_policy_intent` is
    present but fails strict validation -- a present-but-invalid policy is
    never silently replaced by the legacy defaults.
    """
    training_policy_intent = modeling_intent.get("training_policy_intent")
    if training_policy_intent is None:
        return None
    if not isinstance(training_policy_intent, dict):
        raise TrainingPolicyValidationError(["training_policy_intent must be an object"])

    # Project Spec S0224: presence alone of continuous_regression_result_semantics_intent
    # (regardless of its own approval/materialization outcome) is enough to
    # apply the continuous-regression-specific strictness above -- never
    # inferred from training_policy_intent's own contents.
    problem_type_hint = (
        "continuous_regression"
        if isinstance(modeling_intent.get("continuous_regression_result_semantics_intent"), dict)
        else None
    )
    reasons = _validate_training_policy_intent(training_policy_intent, problem_type_hint=problem_type_hint)
    if reasons:
        raise TrainingPolicyValidationError(reasons)

    return {
        "numeric_handling": training_policy_intent["numeric_handling"],
        "categorical_encoding_policy": training_policy_intent["categorical_encoding_policy"],
        "allowed_transformations": list(training_policy_intent["allowed_transformations"]),
        "split_policy": dict(training_policy_intent["split_policy"]),
        "primary_metric": training_policy_intent["primary_metric"],
        "secondary_metrics": list(training_policy_intent["secondary_metrics"]),
        "modeling_constraints": json.loads(json.dumps(training_policy_intent["modeling_constraints"])),
    }


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


# Project Spec S0207: materialize a reviewed, approved
# multiclass_result_semantics_intent, requiring a valid dataset-semantic-
# intent.v2 governed class declaration, into a normalized multiclass
# result_semantics block. Mirrors _materialize_binary_result_semantics'
# independent re-validation and "never blocks the whole contract" pattern.
_MULTICLASS_RESULT_SEMANTICS_SCHEMA_VERSION = "multiclass-result-semantics.v1"
_MULTICLASS_RESULT_SEMANTICS_MINIMUM_CLASS_COUNT = 3
_MULTICLASS_SEMANTIC_INTENT_SCHEMA_VERSION = "dataset-semantic-intent.v2"
_MULTICLASS_SEMANTIC_INTENT_TASK_TYPE = "multiclass_classification"


def _validate_multiclass_classes(
    classes: Any,
) -> tuple[list[dict[str, str]] | None, str | None]:
    """Defensively re-validate an ordered multiclass class declaration.

    Returns `(validated_classes, None)` preserving authored order exactly,
    or `(None, reason)`. Never trusts the schema's `uniqueItems` alone --
    duplicate `class_id` values are rejected explicitly here, since
    object-level uniqueness does not guarantee `class_id` uniqueness (two
    entries could share a `class_id` with different `display_label`s).
    """
    if not isinstance(classes, list) or len(classes) < _MULTICLASS_RESULT_SEMANTICS_MINIMUM_CLASS_COUNT:
        return None, (
            "semantic_intent.target_semantics.classes must be a list with at least "
            f"{_MULTICLASS_RESULT_SEMANTICS_MINIMUM_CLASS_COUNT} entries"
        )
    seen_ids: set[str] = set()
    validated: list[dict[str, str]] = []
    for entry in classes:
        if not isinstance(entry, dict):
            return None, "each semantic_intent.target_semantics.classes entry must be an object"
        class_id = entry.get("class_id")
        display_label = entry.get("display_label")
        if not isinstance(class_id, str) or not class_id.strip():
            return None, "each semantic_intent.target_semantics.classes entry requires a non-empty class_id"
        if not isinstance(display_label, str) or not display_label.strip():
            return None, (
                "each semantic_intent.target_semantics.classes entry requires a non-empty display_label"
            )
        if class_id in seen_ids:
            return None, f"duplicate class_id in semantic_intent.target_semantics.classes: {class_id!r}"
        seen_ids.add(class_id)
        validated.append({"class_id": class_id, "display_label": display_label})
    return validated, None


def _materialize_multiclass_result_semantics(
    modeling_intent: dict[str, Any],
    semantic_intent: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Return (result_semantics_or_None, materialization_evidence) for the
    multiclass variant (Project Spec S0207).

    Requires an approved, independently re-validated
    `multiclass_result_semantics_intent` AND a valid
    `dataset-semantic-intent.v2` declaring `task_type ==
    "multiclass_classification"` with a governed, ordered class array.
    Classes are sourced only from `semantic_intent.target_semantics.classes`
    and copied in authored order -- never sorted, re-derived, or duplicated
    from the modeling intent itself. Never raises; every rejection is a
    normal, reportable `(None, evidence)` outcome.
    """

    def _blocked(reviewed_source_intent_present: bool, reason: str) -> tuple[None, dict[str, Any]]:
        return None, {
            "reviewed_source_intent_present": reviewed_source_intent_present,
            "classes": None,
            "class_count": None,
            "primary_output": None,
            "probability_output": None,
            "decision_strategy": None,
            "no_defaults_inferred": True,
            "readiness": "not_materialized",
            "blocking_reasons": [reason],
        }

    intent = modeling_intent.get("multiclass_result_semantics_intent")
    if not isinstance(intent, dict):
        return _blocked(
            False, "multiclass_result_semantics_intent is absent from the dataset modeling intent"
        )

    review_status = intent.get("review_status")
    if review_status != "approved":
        return _blocked(
            True,
            f"multiclass_result_semantics_intent.review_status is {review_status!r}, "
            "not 'approved'",
        )

    try:
        rebuilt = build_multiclass_result_semantics_intent(
            review_status=review_status,
            problem_type=intent.get("problem_type"),
            primary_output=intent.get("primary_output"),
            probability_output=intent.get("probability_output"),
            decision_strategy=intent.get("decision_strategy"),
            review_notes=intent.get("review_notes"),
        )
    except ValueError as exc:
        return _blocked(
            True,
            f"multiclass_result_semantics_intent failed independent re-validation: {exc}",
        )

    if not isinstance(semantic_intent, dict):
        return _blocked(
            True,
            "multiclass materialization requires a dataset-semantic-intent.v2 semantic_intent",
        )
    semantic_schema_version = semantic_intent.get("schema_version")
    if semantic_schema_version != _MULTICLASS_SEMANTIC_INTENT_SCHEMA_VERSION:
        return _blocked(
            True,
            f"semantic_intent.schema_version is {semantic_schema_version!r}, not "
            f"{_MULTICLASS_SEMANTIC_INTENT_SCHEMA_VERSION!r}",
        )

    target_semantics = semantic_intent.get("target_semantics")
    if not isinstance(target_semantics, dict):
        return _blocked(True, "semantic_intent.target_semantics is missing or malformed")
    task_type = target_semantics.get("task_type")
    if task_type != _MULTICLASS_SEMANTIC_INTENT_TASK_TYPE:
        return _blocked(
            True,
            f"semantic_intent.target_semantics.task_type is {task_type!r}, not "
            f"{_MULTICLASS_SEMANTIC_INTENT_TASK_TYPE!r}",
        )

    validated_classes, class_error = _validate_multiclass_classes(target_semantics.get("classes"))
    if class_error:
        return _blocked(True, class_error)

    result_semantics = {
        "schema_version": _MULTICLASS_RESULT_SEMANTICS_SCHEMA_VERSION,
        "problem_type": rebuilt["problem_type"],
        "classes": [dict(entry) for entry in validated_classes],
        "primary_output": rebuilt["primary_output"],
        "probability_output": rebuilt["probability_output"],
        "decision": {"strategy": rebuilt["decision_strategy"]},
    }
    evidence = {
        "reviewed_source_intent_present": True,
        "classes": [dict(entry) for entry in validated_classes],
        "class_count": len(validated_classes),
        "primary_output": result_semantics["primary_output"],
        "probability_output": result_semantics["probability_output"],
        "decision_strategy": rebuilt["decision_strategy"],
        "no_defaults_inferred": True,
        "readiness": "materialized",
        "blocking_reasons": [],
    }
    return result_semantics, evidence


# Project Spec S0223: materialize a reviewed, approved
# continuous_regression_result_semantics_intent, requiring a valid
# dataset-semantic-intent.v3 governed single-target continuous-regression
# declaration, into a normalized continuous-regression result_semantics
# block. Mirrors _materialize_multiclass_result_semantics' independent
# re-validation and "never blocks the whole contract" pattern.
_CONTINUOUS_REGRESSION_RESULT_SEMANTICS_SCHEMA_VERSION = "continuous-regression-result-semantics.v1"
_CONTINUOUS_REGRESSION_SEMANTIC_INTENT_SCHEMA_VERSION = "dataset-semantic-intent.v3"
_CONTINUOUS_REGRESSION_TASK_TYPE = "continuous_regression"
_CONTINUOUS_REGRESSION_TARGET_VALUE_KIND = "continuous_numeric"


def _materialize_continuous_regression_result_semantics(
    modeling_intent: dict[str, Any],
    semantic_intent: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Return (result_semantics_or_None, materialization_evidence) for the
    continuous-regression variant (Project Spec S0223).

    Requires an approved, independently re-validated
    `continuous_regression_result_semantics_intent` AND a valid
    `dataset-semantic-intent.v3` declaring `task_type ==
    "continuous_regression"` with `target_value_kind ==
    "continuous_numeric"` and a non-empty `target_field_name` that matches
    `modeling_intent.target_intent.target_column`. When
    `modeling_intent.target_intent.task_type` is present, it must also be
    `continuous_regression`. Materializes only the bounded normalized output
    shape -- never target_field_name, review status/notes, training policy,
    metric values, observed target distribution/statistics, units, public
    labels, model family, or model artifact metadata. Never raises; every
    rejection is a normal, reportable `(None, evidence)` outcome.
    """

    def _blocked(reviewed_source_intent_present: bool, reason: str) -> tuple[None, dict[str, Any]]:
        return None, {
            "reviewed_source_intent_present": reviewed_source_intent_present,
            "target_field_name": None,
            "primary_output": None,
            "output_value_kind": None,
            "semantic_intent_schema_version": None,
            "no_defaults_inferred": True,
            "readiness": "not_materialized",
            "blocking_reasons": [reason],
        }

    intent = modeling_intent.get("continuous_regression_result_semantics_intent")
    if not isinstance(intent, dict):
        return _blocked(
            False,
            "continuous_regression_result_semantics_intent is absent from the dataset modeling intent",
        )

    review_status = intent.get("review_status")
    if review_status != "approved":
        return _blocked(
            True,
            f"continuous_regression_result_semantics_intent.review_status is {review_status!r}, "
            "not 'approved'",
        )

    try:
        rebuilt = build_continuous_regression_result_semantics_intent(
            review_status=review_status,
            problem_type=intent.get("problem_type"),
            primary_output=intent.get("primary_output"),
            output_value_kind=intent.get("output_value_kind"),
            review_notes=intent.get("review_notes"),
        )
    except ValueError as exc:
        return _blocked(
            True,
            f"continuous_regression_result_semantics_intent failed independent re-validation: {exc}",
        )

    if not isinstance(semantic_intent, dict):
        return _blocked(
            True,
            "continuous-regression materialization requires a dataset-semantic-intent.v3 semantic_intent",
        )
    semantic_schema_version = semantic_intent.get("schema_version")
    if semantic_schema_version != _CONTINUOUS_REGRESSION_SEMANTIC_INTENT_SCHEMA_VERSION:
        return _blocked(
            True,
            f"semantic_intent.schema_version is {semantic_schema_version!r}, not "
            f"{_CONTINUOUS_REGRESSION_SEMANTIC_INTENT_SCHEMA_VERSION!r}",
        )

    target_semantics = semantic_intent.get("target_semantics")
    if not isinstance(target_semantics, dict):
        return _blocked(True, "semantic_intent.target_semantics is missing or malformed")

    task_type = target_semantics.get("task_type")
    if task_type != _CONTINUOUS_REGRESSION_TASK_TYPE:
        return _blocked(
            True,
            f"semantic_intent.target_semantics.task_type is {task_type!r}, not "
            f"{_CONTINUOUS_REGRESSION_TASK_TYPE!r}",
        )

    target_value_kind = target_semantics.get("target_value_kind")
    if target_value_kind != _CONTINUOUS_REGRESSION_TARGET_VALUE_KIND:
        return _blocked(
            True,
            f"semantic_intent.target_semantics.target_value_kind is {target_value_kind!r}, not "
            f"{_CONTINUOUS_REGRESSION_TARGET_VALUE_KIND!r}",
        )

    target_field_name = target_semantics.get("target_field_name")
    if not isinstance(target_field_name, str) or not target_field_name.strip():
        return _blocked(
            True, "semantic_intent.target_semantics.target_field_name must be a non-empty string"
        )

    target_intent = modeling_intent.get("target_intent") or {}
    modeling_target_column = target_intent.get("target_column")
    if modeling_target_column != target_field_name:
        return _blocked(
            True,
            f"modeling_intent.target_intent.target_column {modeling_target_column!r} does not "
            f"match semantic_intent.target_semantics.target_field_name {target_field_name!r}",
        )

    modeling_task_type = target_intent.get("task_type")
    if modeling_task_type is not None and modeling_task_type != _CONTINUOUS_REGRESSION_TASK_TYPE:
        return _blocked(
            True,
            f"modeling_intent.target_intent.task_type is {modeling_task_type!r}, not "
            f"{_CONTINUOUS_REGRESSION_TASK_TYPE!r}",
        )

    result_semantics = {
        "schema_version": _CONTINUOUS_REGRESSION_RESULT_SEMANTICS_SCHEMA_VERSION,
        "problem_type": rebuilt["problem_type"],
        "primary_output": rebuilt["primary_output"],
        "output_value_kind": rebuilt["output_value_kind"],
    }
    evidence = {
        "reviewed_source_intent_present": True,
        "target_field_name": target_field_name,
        "primary_output": result_semantics["primary_output"],
        "output_value_kind": result_semantics["output_value_kind"],
        "semantic_intent_schema_version": semantic_schema_version,
        "no_defaults_inferred": True,
        "readiness": "materialized",
        "blocking_reasons": [],
    }
    return result_semantics, evidence


def _result_semantics_status_and_reason(
    intent_present: bool, readiness: str, blocking_reasons: list[str]
) -> tuple[str, str | None]:
    """Derive the closed-dispatch status/reason pair from one variant's own
    readiness/blocking_reasons (Project Spec S0207 desired change L)."""
    if not intent_present:
        return "omitted", None
    if readiness == "materialized":
        return "materialized", None
    return "rejected", "; ".join(blocking_reasons) if blocking_reasons else None


def _materialize_result_semantics(
    modeling_intent: dict[str, Any],
    semantic_intent: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Closed result-semantics dispatch (Project Spec S0207, extended by S0223).

    Exactly one variant materializer may ever run per execution contract, as
    a closed three-way selection over
    `binary_result_semantics_intent`/`multiclass_result_semantics_intent`/
    `continuous_regression_result_semantics_intent`: exactly one present
    selects that variant's materializer; none present omits result_semantics
    entirely (the existing, unchanged behavior); more than one present fails
    closed with an explicit conflict rather than silently preferring any
    intent. Never infers the variant from dataset slug, feature names,
    target dtype/cardinality, model family, estimator class, or capability
    support status alone.

    The returned evidence always preserves every existing
    `_materialize_binary_result_semantics` evidence key verbatim (so
    pre-S0207 callers/tests observing `result_semantics_materialization`
    for a binary-only or absent-intent contract see identical fields), and
    adds the common `requested_variant`/`materialized_schema_version`/
    `problem_type`/`status`/`reason` keys on top.
    """
    binary_intent_present = isinstance(modeling_intent.get("binary_result_semantics_intent"), dict)
    multiclass_intent_present = isinstance(
        modeling_intent.get("multiclass_result_semantics_intent"), dict
    )
    continuous_regression_intent_present = isinstance(
        modeling_intent.get("continuous_regression_result_semantics_intent"), dict
    )
    present_count = sum(
        (binary_intent_present, multiclass_intent_present, continuous_regression_intent_present)
    )

    if present_count > 1:
        present_names = [
            name
            for name, present in (
                ("binary_result_semantics_intent", binary_intent_present),
                ("multiclass_result_semantics_intent", multiclass_intent_present),
                (
                    "continuous_regression_result_semantics_intent",
                    continuous_regression_intent_present,
                ),
            )
            if present
        ]
        return None, {
            "requested_variant": "conflict",
            "materialized_schema_version": None,
            "problem_type": None,
            "status": "rejected",
            "reason": (
                "more than one result-semantics intent is present "
                f"({', '.join(present_names)}); only one result-semantics variant may "
                "materialize per execution contract"
            ),
        }

    if continuous_regression_intent_present:
        result_semantics, continuous_regression_evidence = (
            _materialize_continuous_regression_result_semantics(modeling_intent, semantic_intent)
        )
        status, reason = _result_semantics_status_and_reason(
            True,
            continuous_regression_evidence["readiness"],
            continuous_regression_evidence["blocking_reasons"],
        )
        evidence = dict(continuous_regression_evidence)
        evidence["requested_variant"] = "continuous_regression"
        evidence["materialized_schema_version"] = (
            result_semantics["schema_version"] if result_semantics else None
        )
        evidence["problem_type"] = result_semantics["problem_type"] if result_semantics else None
        evidence["status"] = status
        evidence["reason"] = reason
        return result_semantics, evidence

    if multiclass_intent_present:
        result_semantics, multiclass_evidence = _materialize_multiclass_result_semantics(
            modeling_intent, semantic_intent
        )
        status, reason = _result_semantics_status_and_reason(
            True, multiclass_evidence["readiness"], multiclass_evidence["blocking_reasons"]
        )
        evidence = dict(multiclass_evidence)
        evidence["class_ids"] = (
            [entry["class_id"] for entry in multiclass_evidence["classes"]]
            if multiclass_evidence["classes"] is not None
            else None
        )
        evidence["requested_variant"] = "multiclass"
        evidence["materialized_schema_version"] = (
            result_semantics["schema_version"] if result_semantics else None
        )
        evidence["problem_type"] = result_semantics["problem_type"] if result_semantics else None
        evidence["status"] = status
        evidence["reason"] = reason
        return result_semantics, evidence

    # Binary intent present, or neither present -- _materialize_binary_result_semantics
    # already reports the "absent" case on its own, unchanged from before S0207.
    result_semantics, binary_evidence = _materialize_binary_result_semantics(modeling_intent)
    status, reason = _result_semantics_status_and_reason(
        binary_intent_present, binary_evidence["readiness"], binary_evidence["blocking_reasons"]
    )
    evidence = dict(binary_evidence)
    evidence["requested_variant"] = "binary" if binary_intent_present else "none"
    evidence["materialized_schema_version"] = (
        result_semantics["schema_version"] if result_semantics else None
    )
    evidence["problem_type"] = result_semantics["problem_type"] if result_semantics else None
    evidence["status"] = status
    evidence["reason"] = reason
    return result_semantics, evidence


def _build_execution_contract(
    modeling_intent: dict[str, Any],
    discovery_evidence: dict[str, Any],
    preparation_recipe: dict[str, Any] | None,
    semantic_intent: dict[str, Any] | None = None,
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

    # Project Spec S0108/S0207: materialize a reviewed, approved binary OR
    # multiclass result-semantics intent (never both) into a normalized
    # result_semantics block via the closed dispatcher. Omitted entirely
    # (never present-but-null) when absent, pending, invalid, or in
    # conflict -- this is what "blocks executable materialization" means
    # for this optional, backward-compatible field.
    result_semantics, _result_semantics_evidence = _materialize_result_semantics(
        modeling_intent, semantic_intent
    )

    # Project Spec S0223: a requested continuous-regression result intent
    # can never inherit the legacy binary/multiclass classification training
    # defaults below -- it must fail closed before the historical fallback
    # policy is ever applied, requiring an explicit approved
    # training_policy_intent instead. This check only looks at whether a
    # continuous_regression_result_semantics_intent object is present on the
    # modeling intent (not whether it is approved or materializes), and
    # never affects binary/multiclass callers, which retain the historical
    # default-policy path unchanged.
    if (
        isinstance(modeling_intent.get("continuous_regression_result_semantics_intent"), dict)
        and modeling_intent.get("training_policy_intent") is None
    ):
        raise TrainingPolicyValidationError(
            [
                "continuous_regression_result_semantics_intent is present but "
                "training_policy_intent is absent: continuous regression requires an "
                "explicit approved training policy and cannot inherit legacy "
                "classification training defaults"
            ]
        )

    # Project Spec S0216: a reviewed, approved training_policy_intent
    # replaces the repository-standard execution-only policy defaults below
    # wholesale (never field-by-field) once it passes strict validation.
    # Absence preserves the historical Telco-derived defaults unchanged
    # (Desired Change F); `_materialize_training_policy_fields` raises
    # `TrainingPolicyValidationError` for a present-but-invalid policy
    # rather than silently falling back to these defaults.
    training_policy_fields = _materialize_training_policy_fields(modeling_intent)

    if training_policy_fields is not None:
        categorical_encoding_policy = training_policy_fields["categorical_encoding_policy"]
        numeric_handling = training_policy_fields["numeric_handling"]
        allowed_transformations = training_policy_fields["allowed_transformations"]
        split_policy = training_policy_fields["split_policy"]
        primary_metric = training_policy_fields["primary_metric"]
        secondary_metrics = training_policy_fields["secondary_metrics"]
        modeling_constraints = training_policy_fields["modeling_constraints"]
    else:
        categorical_encoding_policy = "onehot"
        numeric_handling = "standardize"
        allowed_transformations = ["passthrough"]
        split_policy = {
            "strategy": "stratified",
            "train_ratio": 0.7,
            "val_ratio": 0.15,
            "test_ratio": 0.15,
        }
        primary_metric = "roc_auc"
        secondary_metrics = ["f1", "pr_auc"]
        modeling_constraints = {
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
        }

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
        "categorical_encoding_policy": categorical_encoding_policy,
        "numeric_handling": numeric_handling,
        "allowed_transformations": allowed_transformations,
        "split_policy": split_policy,
        "random_seed": seed if isinstance(seed, int) else None,
        "primary_metric": primary_metric,
        "secondary_metrics": secondary_metrics,
        "modeling_constraints": modeling_constraints,
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
    semantic_intent: dict[str, Any] | None = None,
    semantic_intent_relative_path: str | Path | None = None,
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

    # Project Spec S0108/S0207: independently re-derived (never trusted from
    # hidden state set during _build_execution_contract), mirroring the
    # categorical domain re-derivation convention above. Uses the same
    # closed result-semantics dispatcher as _build_execution_contract.
    _result_semantics, result_semantics_evidence = _materialize_result_semantics(
        modeling_intent, semantic_intent
    )

    # Project Spec S0216: independently re-derived (never trusted from
    # hidden state set during _build_execution_contract), mirroring the
    # categorical-domain/result-semantics re-derivation convention above.
    training_policy_intent_present = modeling_intent.get("training_policy_intent") is not None
    training_policy_materialization = {
        "reviewed_source_intent_present": training_policy_intent_present,
        "materialized": training_policy_intent_present
        and _materialize_training_policy_fields(modeling_intent) is not None,
    }

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
            "semantic_intent_ref": (
                str(semantic_intent_relative_path) if semantic_intent_relative_path else None
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
        "policy_defaults_requiring_future_review": (
            [] if training_policy_intent_present else list(_POLICY_DEFAULT_FIELDS)
        ),
        "training_policy_materialization": training_policy_materialization,
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
    semantic_intent: dict[str, Any] | None = None,
    semantic_intent_relative_path: str | Path | None = None,
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
        modeling_intent, discovery_evidence, preparation_recipe, semantic_intent=semantic_intent
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
        semantic_intent=semantic_intent,
        semantic_intent_relative_path=semantic_intent_relative_path,
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


# ---------------------------------------------------------------------------
# Capability-aware source-contract projection (Project Spec S0167)
#
# Bridges a capability-aware pipeline/source-contract-input.schema.json
# instance (authoring_manifest_ref + capability_profile_id/version/ref +
# authoring_generation_id, all additive/optional -- see that schema) into
# the existing, unchanged runtime->public projection above, gated by the
# Project Spec S0166 authoring boundary (pipeline/authoring_contracts.py)
# and the resolved capability profile's own support_status/artifact-role
# applicability. Never derives execution/runtime/public contract semantics
# for a capability this module has no explicit, evidenced projection code
# for -- an unsupported (or merely representable-but-unimplemented)
# capability profile fails closed with a typed CapabilityProjectionResult,
# never a fabricated contract. Contains no dataset-slug or dataset-name
# conditional anywhere: the one capability_profile_id this module currently
# knows how to project is an architecture-level capability identity, never
# a dataset identity.
# ---------------------------------------------------------------------------

CURRENTLY_SUPPORTED_CAPABILITY_PROFILE_ID = "binary-predictive-classification"
_CAPABILITY_SUPPORT_STATUS_OPERATIONAL = "current_supported"
# Project Spec S0209: closed set/map of capability_profile_ids this module
# has explicit contract-projection implementation code for. Preserves
# CURRENTLY_SUPPORTED_CAPABILITY_PROFILE_ID's own value/meaning (still the
# sole binary-classification identity) for existing callers/tests; the
# projection gate below checks membership in this set, never equality
# against the single binary constant alone. multiclass-predictive-
# classification is structurally represented here, but the real committed
# profile (pipeline/capabilities/multiclass-predictive-classification.v1.json)
# still declares support_status: requires_future_contract_evolution, so real
# multiclass projection remains rejected below regardless of this set's
# membership -- only a synthetic support_status: current_supported profile
# clone reaches acceptance.
CONTRACT_PROJECTION_SUPPORTED_CAPABILITY_PROFILE_IDS = frozenset({
    CURRENTLY_SUPPORTED_CAPABILITY_PROFILE_ID,
    "multiclass-predictive-classification",
})

# Rejection phases, mirroring this module's existing _rejection()/
# rejection_phase convention used by the runtime->public CLI flow above.
CAPABILITY_REJECTION_PHASE_MANIFEST_READ = "authoring_manifest_read"
CAPABILITY_REJECTION_PHASE_PROFILE_READ = "capability_profile_read"
CAPABILITY_REJECTION_PHASE_INTEGRITY = "governed_reference_integrity"
CAPABILITY_REJECTION_PHASE_BOUNDARY = "authoring_boundary_validation"
CAPABILITY_REJECTION_PHASE_IDENTITY = "capability_profile_identity_mismatch"
CAPABILITY_REJECTION_PHASE_UNSUPPORTED = "capability_unsupported"
CAPABILITY_REJECTION_PHASE_PROJECTION = "runtime_public_projection"


@dataclass(frozen=True)
class CapabilityProjectionResult:
    """Deterministic, typed result of one capability-aware source-contract
    projection attempt (Project Spec S0167).

    `status` is `"accepted"` only when: the authoring manifest and
    capability profile governed references hash-verify and parse; the
    S0166 authoring boundary (`validate_authoring_contracts`) passes; the
    source-contract-input's own declared capability identity agrees with
    the validated boundary's resolved identity; the resolved capability
    profile's `support_status` is `"current_supported"` AND its
    `capability_profile_id` is one this module has explicit projection
    code for; and the existing runtime->public projection succeeds against
    the schema-valid runtime contract at `source_contract_ref`. Every other
    outcome is `"rejected"` with a typed `rejection_phase`/`rejection_reason`
    -- this function never raises for a normal validation, integrity, or
    unsupported-capability outcome.
    """

    status: str
    dataset_slug: str | None
    capability_profile_id: str | None
    capability_profile_version: str | None
    capability_support_status: str | None
    authoring_boundary_valid: bool | None
    rejection_phase: str | None
    rejection_reason: str | None
    runtime_contract: dict[str, Any] | None
    public_contract: dict[str, Any] | None


def _sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _resolve_repo_relative(repo_root: Path, relative_path: str) -> Path | None:
    """Resolve relative_path beneath repo_root, following symlinks, and
    return None if the resolved location escapes repo_root (path or
    symlink-based escape). Mirrors
    pipeline.authoring_contracts._resolve_within_root -- checked
    independently here even though the schema's own safe-relative-reference
    pattern already constrains these paths, matching that module's
    defense-in-depth convention."""
    candidate = (repo_root / relative_path).resolve()
    try:
        candidate.relative_to(repo_root)
    except ValueError:
        return None
    return candidate


def _load_governed_reference(
    repo_root: Path, ref: dict[str, Any], *, label: str
) -> tuple[dict[str, Any] | None, str | None]:
    """Load and hash-verify a `{"path", "sha256"}` governed reference
    relative to repo_root. Returns `(document, error_message)` -- exactly
    one is non-None. Never reads outside repo_root."""
    resolved = _resolve_repo_relative(repo_root, ref["path"])
    if resolved is None:
        return None, f"{label} path escapes repository root: {ref['path']!r}"
    if not resolved.is_file():
        return None, f"{label} not found at referenced path: {ref['path']!r}"
    raw = resolved.read_bytes()
    observed_sha256 = _sha256_of_bytes(raw)
    if observed_sha256 != ref["sha256"]:
        return None, (
            f"{label} SHA-256 mismatch: declared={ref['sha256']} "
            f"observed={observed_sha256} path={ref['path']!r}"
        )
    try:
        return json.loads(raw.decode("utf-8")), None
    except json.JSONDecodeError as exc:
        return None, f"{label} is not valid JSON: {exc}"


def resolve_manifest_role_reference(
    manifest: dict[str, Any], role_name: str
) -> dict[str, Any] | None:
    """Return the `artifact_references[]` entry for `role_name` from an
    already schema-valid dataset-integration authoring manifest, or None
    when the role is absent. This is how semantic intent, source
    verification, preparation policy, and modeled/runtime evidence are
    reached by governed reference rather than duplicated as separate
    source-contract-input fields (Project Spec S0167 desired-change A)."""
    for entry in manifest.get("artifact_references", []):
        if entry.get("role") == role_name:
            return entry
    return None


def project_capability_aware_source_contract(
    source_input: dict[str, Any],
    *,
    repo_root: str | Path,
) -> CapabilityProjectionResult:
    """Project a capability-aware `source-contract-input.v1` instance (the
    additive `authoring_manifest_ref`/`capability_profile_*` fields,
    Project Spec S0167) into execution/runtime/public contract semantics,
    gated by the resolved capability profile.

    Reuses `pipeline.authoring_contracts.validate_authoring_contracts`
    (Project Spec S0166) as the sole authoring-boundary validator -- this
    function never re-implements manifest/profile/semantic-intent
    cross-checks. For the currently supported binary predictive-
    classification capability, reuses the existing, unchanged
    `_derive_public_contract`/`_validate_schema`/`_check_safety`
    runtime->public projection above once capability gating passes -- this
    function only gates that existing path, it never changes its behavior.

    Never fabricates target semantics, thresholds, risk bands, public
    inference fields, or placeholder model evidence for an unsupported or
    not-yet-implemented capability. Contains no dataset-slug or
    dataset-name conditional. Caller must supply a `source_input` that
    already declares all five capability-aware fields together (the
    schema's own `dependentRequired` enforces this before this function is
    ever reached).
    """
    resolved_repo_root = Path(repo_root).expanduser().resolve()
    dataset_slug = source_input.get("dataset_slug")

    def _rejected(phase: str, reason: str, **overrides: Any) -> CapabilityProjectionResult:
        fields: dict[str, Any] = {
            "status": "rejected",
            "dataset_slug": dataset_slug,
            "capability_profile_id": source_input.get("capability_profile_id"),
            "capability_profile_version": source_input.get("capability_profile_version"),
            "capability_support_status": None,
            "authoring_boundary_valid": None,
            "rejection_phase": phase,
            "rejection_reason": reason,
            "runtime_contract": None,
            "public_contract": None,
        }
        fields.update(overrides)
        return CapabilityProjectionResult(**fields)

    manifest, manifest_err = _load_governed_reference(
        resolved_repo_root, source_input["authoring_manifest_ref"], label="authoring manifest"
    )
    if manifest_err:
        return _rejected(CAPABILITY_REJECTION_PHASE_MANIFEST_READ, manifest_err)

    profile, profile_err = _load_governed_reference(
        resolved_repo_root, source_input["capability_profile_ref"], label="capability profile"
    )
    if profile_err:
        return _rejected(CAPABILITY_REJECTION_PHASE_PROFILE_READ, profile_err)

    semantic_intent = None
    semantic_intent_entry = resolve_manifest_role_reference(manifest, "semantic_intent")
    if semantic_intent_entry is not None:
        semantic_intent, semantic_err = _load_governed_reference(
            resolved_repo_root,
            {"path": semantic_intent_entry["path"], "sha256": semantic_intent_entry["sha256"]},
            label="semantic intent",
        )
        if semantic_err:
            return _rejected(CAPABILITY_REJECTION_PHASE_INTEGRITY, semantic_err)

    boundary_result = validate_authoring_contracts(
        manifest,
        profile,
        semantic_intent=semantic_intent,
        artifact_root=resolved_repo_root,
        expected_dataset_slug=dataset_slug,
    )
    if not boundary_result.valid:
        reason = "; ".join(
            f"{failure.code}: {failure.message}" for failure in boundary_result.failures
        ) or "authoring boundary invalid"
        return _rejected(
            CAPABILITY_REJECTION_PHASE_BOUNDARY,
            reason,
            authoring_boundary_valid=False,
        )

    # Defense in depth: the source-contract-input's own direct capability
    # identity/version must agree with what the already cross-validated
    # manifest/profile pair actually declares -- never trusted implicitly
    # just because boundary_result.valid is True.
    declared_id = source_input.get("capability_profile_id")
    declared_version = source_input.get("capability_profile_version")
    if (
        declared_id != boundary_result.capability_profile_id
        or declared_version != boundary_result.capability_profile_version
    ):
        return _rejected(
            CAPABILITY_REJECTION_PHASE_IDENTITY,
            (
                f"source-contract-input capability_profile {declared_id!r}/{declared_version!r} "
                "does not agree with the validated authoring boundary's resolved capability "
                f"{boundary_result.capability_profile_id!r}/{boundary_result.capability_profile_version!r}"
            ),
            authoring_boundary_valid=True,
        )

    support_status = profile.get("support_status")
    resolved_profile_id = profile.get("capability_profile_id")

    if (
        support_status != _CAPABILITY_SUPPORT_STATUS_OPERATIONAL
        or resolved_profile_id not in CONTRACT_PROJECTION_SUPPORTED_CAPABILITY_PROFILE_IDS
    ):
        return _rejected(
            CAPABILITY_REJECTION_PHASE_UNSUPPORTED,
            (
                f"capability {resolved_profile_id!r} (support_status={support_status!r}) is not "
                "currently, operationally supported for contract projection"
            ),
            capability_support_status=support_status,
            authoring_boundary_valid=True,
        )

    # Currently supported: binary predictive classification. Reuse the
    # existing, unchanged runtime->public projection unconditionally --
    # the same source_contract_ref mechanism source-contract-input.v1
    # already used, now reached only after capability gating.
    source_contract_ref = source_input.get("source_contract_ref")
    runtime_ref_path = (
        _resolve_repo_relative(resolved_repo_root, source_contract_ref)
        if source_contract_ref
        else None
    )
    if runtime_ref_path is None or not runtime_ref_path.is_file():
        return _rejected(
            CAPABILITY_REJECTION_PHASE_PROJECTION,
            f"runtime contract not found at source_contract_ref: {source_contract_ref!r}",
            capability_support_status=support_status,
            authoring_boundary_valid=True,
        )

    runtime_contract, parse_err = _load_json(str(runtime_ref_path))
    if parse_err:
        return _rejected(
            CAPABILITY_REJECTION_PHASE_PROJECTION,
            f"could not parse runtime contract: {parse_err}",
            capability_support_status=support_status,
            authoring_boundary_valid=True,
        )

    runtime_schema = json.loads(RUNTIME_SCHEMA_PATH.read_text(encoding="utf-8"))
    runtime_errors = _validate_schema(runtime_contract, runtime_schema)
    if runtime_errors:
        first = runtime_errors[0]
        reason = (
            first if len(runtime_errors) == 1 else f"{len(runtime_errors)} validation errors: {first}"
        )
        return _rejected(
            CAPABILITY_REJECTION_PHASE_PROJECTION,
            f"runtime contract fails schema validation: {reason}",
            capability_support_status=support_status,
            authoring_boundary_valid=True,
        )

    public_contract = _derive_public_contract(runtime_contract)
    public_schema = json.loads(PUBLIC_SCHEMA_PATH.read_text(encoding="utf-8"))
    public_errors = _validate_schema(public_contract, public_schema)
    if public_errors:
        first = public_errors[0]
        reason = (
            first if len(public_errors) == 1 else f"{len(public_errors)} validation errors: {first}"
        )
        return _rejected(
            CAPABILITY_REJECTION_PHASE_PROJECTION,
            f"derived public contract fails schema validation (pipeline bug): {reason}",
            capability_support_status=support_status,
            authoring_boundary_valid=True,
        )

    safety_violations = _check_safety(public_contract)
    if safety_violations:
        return _rejected(
            CAPABILITY_REJECTION_PHASE_PROJECTION,
            f"public contract safety check failed: {'; '.join(safety_violations)}",
            capability_support_status=support_status,
            authoring_boundary_valid=True,
        )

    return CapabilityProjectionResult(
        status="accepted",
        dataset_slug=dataset_slug,
        capability_profile_id=resolved_profile_id,
        capability_profile_version=profile.get("capability_profile_version"),
        capability_support_status=support_status,
        authoring_boundary_valid=True,
        rejection_phase=None,
        rejection_reason=None,
        runtime_contract=runtime_contract,
        public_contract=public_contract,
    )


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
