"""Canonical preparation-rule vocabulary.

One identity per preparation capability, shared by native candidate
preparation (``pipeline.prepare_candidate``), scientific reproduction
(``pipeline.scientific_reproduction``), and dataset-integration authoring
policies. Rules are fully parametric: the dataset's column names, condition
values, and replacements always come from the caller's contract/policy, never
from this module.

``conditional_blank_numeric_fill``
    Fill blank (empty or whitespace-only) values of a numeric ``column`` with
    ``replacement`` -- but only when every blank row satisfies
    ``condition_column == condition_value``; any blank row that fails the
    condition blocks preparation (no row dropping, no broad imputation, no
    indicator column). Non-blank values are converted to numbers.

Historical names for the same capability are accepted only through the
explicit, deprecated alias table below (they appear in already-written
authoring provenance); new authoring must use the canonical kind.
"""

from __future__ import annotations

from typing import Any, Mapping

CONDITIONAL_BLANK_NUMERIC_FILL = "conditional_blank_numeric_fill"

PREPARATION_RULE_KINDS = frozenset({CONDITIONAL_BLANK_NUMERIC_FILL})

# Deprecated names of a canonical rule kind. "conditional_blank_to_zero" is
# the operation name recorded in the Telco authoring generation
# telco-authoring-v2 (pipeline/authoring/telco-customer-churn/
# preparation-recipe.json, sha256-pinned by its immutable authoring
# manifest); that artifact is provenance only and is never rewritten.
DEPRECATED_RULE_KIND_ALIASES: Mapping[str, str] = {
    "conditional_blank_to_zero": CONDITIONAL_BLANK_NUMERIC_FILL,
}

CONDITIONAL_BLANK_NUMERIC_FILL_PARAMETERS = ("column", "condition_column", "condition_value", "replacement")


class PreparationRuleError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def canonical_rule_kind(kind: str) -> str:
    """Resolve a rule kind (canonical or deprecated alias) to its canonical
    identity; unknown kinds fail closed."""
    if kind in PREPARATION_RULE_KINDS:
        return kind
    if kind in DEPRECATED_RULE_KIND_ALIASES:
        return DEPRECATED_RULE_KIND_ALIASES[kind]
    raise PreparationRuleError("unsupported_preparation_rule", f"unknown preparation rule kind {kind!r}")


def conditional_blank_numeric_fill_rule(
    *, column: str, condition_column: str, condition_value: Any, replacement: Any,
) -> dict[str, Any]:
    """Canonical, parametric declaration of a conditional blank numeric fill."""
    for name, value in (("column", column), ("condition_column", condition_column)):
        if not isinstance(value, str) or not value:
            raise PreparationRuleError("invalid_preparation_rule", f"{name} must be a non-empty column name")
    return {
        "kind": CONDITIONAL_BLANK_NUMERIC_FILL,
        "column": column,
        "condition_column": condition_column,
        "condition_value": condition_value,
        "replacement": replacement,
    }


def normalize_rule(rule: Mapping[str, Any]) -> dict[str, Any]:
    """Return the canonical form of a rule declaration.

    Accepts the canonical shape (``kind`` + canonical parameters) and the
    deprecated authoring shape ``{"field", "operation":
    "conditional_blank_to_zero", "when": {"field", "equals"}, "otherwise":
    "reject_blank"}`` (whose implied replacement is 0 and whose ``otherwise``
    is the canonical blocking behavior).
    """
    if "kind" in rule:
        kind = canonical_rule_kind(str(rule["kind"]))
        missing = [name for name in CONDITIONAL_BLANK_NUMERIC_FILL_PARAMETERS if name not in rule]
        if missing:
            raise PreparationRuleError("invalid_preparation_rule", f"{kind} is missing parameters: {missing}")
        normalized = conditional_blank_numeric_fill_rule(
            column=rule["column"],
            condition_column=rule["condition_column"],
            condition_value=rule["condition_value"],
            replacement=rule["replacement"],
        )
        return {**dict(rule), **normalized}
    operation = rule.get("operation")
    if operation is None:
        raise PreparationRuleError("invalid_preparation_rule", "rule declares neither kind nor operation")
    if DEPRECATED_RULE_KIND_ALIASES.get(str(operation)) != CONDITIONAL_BLANK_NUMERIC_FILL:
        raise PreparationRuleError("invalid_preparation_rule", f"unsupported legacy operation {operation!r}")
    when = rule.get("when") or {}
    if rule.get("otherwise", "reject_blank") != "reject_blank":
        raise PreparationRuleError(
            "invalid_preparation_rule", f"{operation} only supports otherwise='reject_blank'"
        )
    return conditional_blank_numeric_fill_rule(
        column=rule.get("field"),
        condition_column=when.get("field"),
        condition_value=when.get("equals"),
        replacement=0,
    )
