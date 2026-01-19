"""Schema canônico — Internal Contract v1.

Alinhado a `docs/spec/internal_contract.v1.md`.

Esta implementação evita dependências externas (ex.: Pydantic) para manter
o core leve durante os milestones iniciais.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .errors import ContractValidationError


_ALLOWED_PROBLEM_TYPES = {"classification", "regression", "clustering", "other"}
_ALLOWED_TARGET_DTYPES = {"int", "float", "category", "bool"}
_ALLOWED_FEATURE_ROLES = {"numerical", "categorical", "boolean", "text", "other"}
_ALLOWED_FEATURE_DTYPES = {"int", "float", "category", "bool", "string"}
_ALLOWED_NORM_TYPES = {"map", "lower", "upper", "none"}


def _is_non_empty_str(x: Any) -> bool:
    return isinstance(x, str) and bool(x.strip())


def _expect(cond: bool, msg: str) -> None:
    if not cond:
        raise ContractValidationError(msg)


@dataclass(frozen=True)
class InternalContractV1:
    """Representação interna explícita do Internal Contract v1."""

    contract_version: str
    problem: Dict[str, Any]
    target: Dict[str, Any]
    features: List[Dict[str, Any]]
    defaults: Dict[str, Any]
    categories: Dict[str, Any]
    imputation: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "problem": dict(self.problem),
            "target": dict(self.target),
            "features": [dict(f) for f in self.features],
            "defaults": dict(self.defaults),
            "categories": dict(self.categories),
            "imputation": dict(self.imputation),
        }


def validate_internal_contract_v1(data: Any) -> InternalContractV1:
    """Valida e materializa um Internal Contract v1.

    Args:
        data: dicionário carregado de YAML/JSON.

    Returns:
        InternalContractV1: contrato validado.

    Raises:
        ContractValidationError: se inválido.
    """
    _expect(isinstance(data, dict), "Internal Contract must be a mapping/dict")

    cv = data.get("contract_version")
    _expect(_is_non_empty_str(cv), "contract_version is required")
    _expect(str(cv) == "1.0", "contract_version must be '1.0' in v1")

    problem = data.get("problem")
    _expect(isinstance(problem, dict), "problem must be a mapping")
    _expect(_is_non_empty_str(problem.get("name")), "problem.name is required")
    ptype = problem.get("type")
    _expect(_is_non_empty_str(ptype), "problem.type is required")
    _expect(ptype in _ALLOWED_PROBLEM_TYPES, f"problem.type must be one of {sorted(_ALLOWED_PROBLEM_TYPES)}")

    target = data.get("target")
    _expect(isinstance(target, dict), "target must be a mapping")
    _expect(_is_non_empty_str(target.get("name")), "target.name is required")
    tdtype = target.get("dtype")
    _expect(_is_non_empty_str(tdtype), "target.dtype is required")
    _expect(tdtype in _ALLOWED_TARGET_DTYPES, f"target.dtype must be one of {sorted(_ALLOWED_TARGET_DTYPES)}")
    allowed_null = target.get("allowed_null")
    _expect(allowed_null is False, "target.allowed_null must be false in v1")

    features = data.get("features")
    _expect(isinstance(features, list), "features must be a list")
    _expect(len(features) > 0, "features must not be empty")

    seen_names: set[str] = set()
    normalized_features: List[Dict[str, Any]] = []
    for i, f in enumerate(features):
        _expect(isinstance(f, dict), f"features[{i}] must be a mapping")
        name = f.get("name")
        _expect(_is_non_empty_str(name), f"features[{i}].name is required")
        _expect(name not in seen_names, f"duplicate feature name: {name}")
        seen_names.add(name)

        role = f.get("role")
        _expect(_is_non_empty_str(role), f"features[{i}].role is required")
        _expect(role in _ALLOWED_FEATURE_ROLES, f"features[{i}].role must be one of {sorted(_ALLOWED_FEATURE_ROLES)}")

        dtype = f.get("dtype")
        _expect(_is_non_empty_str(dtype), f"features[{i}].dtype is required")
        _expect(dtype in _ALLOWED_FEATURE_DTYPES, f"features[{i}].dtype must be one of {sorted(_ALLOWED_FEATURE_DTYPES)}")

        required = f.get("required")
        _expect(isinstance(required, bool), f"features[{i}].required must be boolean")
        allowed_null_f = f.get("allowed_null")
        _expect(isinstance(allowed_null_f, bool), f"features[{i}].allowed_null must be boolean")

        normalized_features.append(
            {
                "name": name,
                "role": role,
                "dtype": dtype,
                "required": required,
                "allowed_null": allowed_null_f,
            }
        )

    defaults = data.get("defaults") or {}
    _expect(isinstance(defaults, dict), "defaults must be a mapping")
    for col in defaults.keys():
        _expect(col in seen_names, f"defaults references unknown feature: {col}")

    categories = data.get("categories") or {}
    _expect(isinstance(categories, dict), "categories must be a mapping")
    for col, spec in categories.items():
        _expect(col in seen_names, f"categories references unknown feature: {col}")
        _expect(isinstance(spec, dict), f"categories.{col} must be a mapping")
        allowed = spec.get("allowed")
        _expect(isinstance(allowed, list), f"categories.{col}.allowed must be a list")
        norm = spec.get("normalization")
        if norm is not None:
            _expect(isinstance(norm, dict), f"categories.{col}.normalization must be a mapping")
            ntype = norm.get("type", "none")
            _expect(_is_non_empty_str(ntype), f"categories.{col}.normalization.type must be a string")
            _expect(ntype in _ALLOWED_NORM_TYPES, f"normalization.type must be one of {sorted(_ALLOWED_NORM_TYPES)}")
            if ntype == "map":
                mapping = norm.get("mapping")
                _expect(isinstance(mapping, dict), f"categories.{col}.normalization.mapping must be a mapping when type=map")

    imputation = data.get("imputation") or {}
    _expect(isinstance(imputation, dict), "imputation must be a mapping")
    for col, spec in imputation.items():
        _expect(col in seen_names, f"imputation references unknown feature: {col}")
        _expect(isinstance(spec, dict), f"imputation.{col} must be a mapping")
        allowed = spec.get("allowed")
        _expect(isinstance(allowed, bool), f"imputation.{col}.allowed must be boolean")

    return InternalContractV1(
        contract_version=str(cv),
        problem=dict(problem),
        target=dict(target),
        features=normalized_features,
        defaults=dict(defaults),
        categories=dict(categories),
        imputation=dict(imputation),
    )
