"""Canonical metric identity for the pipeline layer.

The single authority is the declarative registry
``contracts/metric-identity-registry.json`` (shared with the API layer, which
reads the same file through ``api/metric_identity.py`` because the API image
does not ship ``pipeline/``). This module only reads it; it never keeps its
own metric table.

A metric's canonical ``metric_id`` is the identifier execution contracts use
for ``primary_metric``/``secondary_metrics``. Aliases map that identity to the
names each layer writes: native training, scientific reproduction, and the
public API projection.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Mapping

REGISTRY_RELATIVE_PATH = "contracts/metric-identity-registry.json"
REGISTRY_SCHEMA_VERSION = "metric-identity-registry.v1"
HIGHER_IS_BETTER = "higher_is_better"
LOWER_IS_BETTER = "lower_is_better"

# Tabular problem types governed by execution_contract.v1.
TABULAR_PROBLEM_TYPES = frozenset({
    "binary_classification",
    "multiclass_classification",
    "continuous_regression",
})


class MetricIdentityError(ValueError):
    """Raised for an unknown metric or a malformed registry."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class MetricIdentity:
    metric_id: str
    direction: str
    problem_types: frozenset[str]
    sklearn_scorer: str | None
    display_label: str
    training_aliases: tuple[str, ...]
    scientific_aliases: tuple[str, ...]
    public_key: str | None
    public_input_aliases: tuple[str, ...]

    @property
    def lower_is_better(self) -> bool:
        return self.direction == LOWER_IS_BETTER

    def applies_to(self, problem_type: str) -> bool:
        return problem_type in self.problem_types


def _registry_path() -> Path:
    return Path(__file__).resolve().parent.parent / REGISTRY_RELATIVE_PATH


@lru_cache(maxsize=1)
def metric_identities() -> Mapping[str, MetricIdentity]:
    """All canonical metric identities, keyed by metric_id, in registry order."""
    payload = json.loads(_registry_path().read_text(encoding="utf-8"))
    if payload.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        raise MetricIdentityError(
            "invalid_metric_identity_registry",
            f"{REGISTRY_RELATIVE_PATH} must declare schema_version {REGISTRY_SCHEMA_VERSION!r}",
        )
    identities: dict[str, MetricIdentity] = {}
    for entry in payload["metrics"]:
        aliases = entry["aliases"]
        identity = MetricIdentity(
            metric_id=entry["metric_id"],
            direction=entry["direction"],
            problem_types=frozenset(entry["problem_types"]),
            sklearn_scorer=entry["sklearn_scorer"],
            display_label=entry["display_label"],
            training_aliases=tuple(aliases["training"]),
            scientific_aliases=tuple(aliases["scientific"]),
            public_key=aliases["public"],
            public_input_aliases=tuple(aliases["public_input"]),
        )
        if identity.direction not in (HIGHER_IS_BETTER, LOWER_IS_BETTER):
            raise MetricIdentityError(
                "invalid_metric_identity_registry",
                f"metric {identity.metric_id!r} has an unknown direction {identity.direction!r}",
            )
        if identity.metric_id in identities:
            raise MetricIdentityError(
                "invalid_metric_identity_registry",
                f"metric {identity.metric_id!r} is declared more than once",
            )
        identities[identity.metric_id] = identity
    _require_unambiguous(identities.values(), "training_aliases")
    _require_unambiguous(identities.values(), "scientific_aliases")
    return identities


def _require_unambiguous(identities: Iterable[MetricIdentity], attribute: str) -> None:
    seen: dict[str, str] = {}
    for identity in identities:
        for alias in getattr(identity, attribute):
            if alias in seen and seen[alias] != identity.metric_id:
                raise MetricIdentityError(
                    "invalid_metric_identity_registry",
                    f"{attribute} alias {alias!r} maps to both {seen[alias]!r} and {identity.metric_id!r}",
                )
            seen[alias] = identity.metric_id


def resolve_training_metric(name: str) -> MetricIdentity:
    """Resolve an execution-contract / native-training metric name."""
    for identity in metric_identities().values():
        if name in identity.training_aliases:
            return identity
    raise MetricIdentityError("unknown_metric", f"unknown training metric {name!r}")


def resolve_scientific_metric(name: str) -> MetricIdentity:
    for identity in metric_identities().values():
        if name in identity.scientific_aliases:
            return identity
    raise MetricIdentityError("unknown_metric", f"unknown scientific metric {name!r}")


def training_metric_vocabulary(problem_types: Iterable[str]) -> frozenset[str]:
    """Every native-training metric name applicable to any of problem_types."""
    wanted = frozenset(problem_types)
    return frozenset(
        alias
        for identity in metric_identities().values()
        if identity.problem_types & wanted
        for alias in identity.training_aliases
    )


def lower_is_better_training_metrics() -> frozenset[str]:
    return frozenset(
        alias
        for identity in metric_identities().values()
        if identity.lower_is_better
        for alias in identity.training_aliases
    )


def native_to_scientific_metric_aliases() -> dict[str, str]:
    """Native-training names whose scientific-reproduction name differs."""
    mapping: dict[str, str] = {}
    for identity in metric_identities().values():
        if not identity.scientific_aliases:
            continue
        scientific = identity.scientific_aliases[0]
        for alias in identity.training_aliases:
            if alias != scientific:
                mapping[alias] = scientific
    return mapping


def sklearn_scorer_for_training_metric(name: str, problem_type: str) -> str:
    """The scikit-learn scorer for a contract metric, validated against the
    problem type it is being used for. Fails closed when the metric does not
    apply to the problem type or has no built-in scorer."""
    identity = resolve_training_metric(name)
    if not identity.applies_to(problem_type):
        raise MetricIdentityError(
            "metric_not_applicable",
            f"metric {name!r} does not apply to problem type {problem_type!r}",
        )
    if identity.sklearn_scorer is None:
        raise MetricIdentityError(
            "metric_has_no_scorer",
            f"metric {name!r} has no scikit-learn scorer",
        )
    return identity.sklearn_scorer
