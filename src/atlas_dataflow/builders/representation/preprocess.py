"""Builder canônico: representation.preprocess (v1).

Constrói um `sklearn.compose.ColumnTransformer` de forma **determinística** e
**declarativa**, guiado exclusivamente por **contrato interno** e **configuração**.

Fonte de verdade (spec): `docs/spec/representation.preprocess.v1.md`.

Regras (v1):
- Não infere colunas: `numeric.columns` e `categorical.columns` devem ser
  explicitamente informadas.
- Valida colunas contra o contrato (roles esperados).
- Suporta opções explícitas:
  - Numéricas: StandardScaler | MinMaxScaler | null (passthrough)
  - Categóricas: OneHotEncoder (handle_unknown, drop)
- O Builder **não executa** fit/transform.

Config esperada (exemplo):

representation:
  preprocess:
    numeric:
      columns: [age, income]
      scaler: standard
    categorical:
      columns: [country, gender]
      encoder: onehot
      handle_unknown: ignore
      drop: null

Compatibilidade:
- O contrato interno v1 já define `features` com `role`.
- O Builder valida que colunas em numeric.columns tenham role "numerical" e
  colunas em categorical.columns tenham role "categorical".

Limites explícitos:
- Fora de escopo: feature selection, feature engineering, inferência de tipos.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class PreprocessSpec:
    """Especificação normalizada do preprocess (após validação)."""

    numeric_columns: List[str]
    categorical_columns: List[str]
    numeric_scaler: Optional[str]
    categorical_encoder: str
    handle_unknown: str
    drop: Optional[str]


def _is_non_empty_str(x: Any) -> bool:
    return isinstance(x, str) and bool(x.strip())


def _expect(cond: bool, msg: str) -> None:
    if not cond:
        raise ValueError(msg)


def _extract_features_roles(contract: Dict[str, Any]) -> Dict[str, str]:
    features = contract.get("features")
    _expect(isinstance(features, list), "Invalid contract: features must be a list")
    roles: Dict[str, str] = {}
    for i, f in enumerate(features):
        _expect(isinstance(f, dict), f"Invalid contract: features[{i}] must be a mapping")
        name = f.get("name")
        role = f.get("role")
        _expect(_is_non_empty_str(name), f"Invalid contract: features[{i}].name is required")
        _expect(_is_non_empty_str(role), f"Invalid contract: features[{i}].role is required")
        roles[str(name)] = str(role)
    return roles


def _get_representation_cfg(cfg: Dict[str, Any]) -> Dict[str, Any]:
    rep = cfg.get("representation") if isinstance(cfg, dict) else None
    rep = rep if isinstance(rep, dict) else {}
    pre = rep.get("preprocess") if isinstance(rep, dict) else None
    return pre if isinstance(pre, dict) else {}


def _normalize_spec(contract: Dict[str, Any], config: Dict[str, Any]) -> PreprocessSpec:
    pre = _get_representation_cfg(config)

    numeric = pre.get("numeric")
    numeric = numeric if isinstance(numeric, dict) else {}
    categorical = pre.get("categorical")
    categorical = categorical if isinstance(categorical, dict) else {}

    num_cols = numeric.get("columns")
    cat_cols = categorical.get("columns")
    _expect(isinstance(num_cols, list), "Invalid config: representation.preprocess.numeric.columns must be a list")
    _expect(isinstance(cat_cols, list), "Invalid config: representation.preprocess.categorical.columns must be a list")

    num_cols_norm = [str(c).strip() for c in num_cols if _is_non_empty_str(c)]
    cat_cols_norm = [str(c).strip() for c in cat_cols if _is_non_empty_str(c)]

    _expect(len(num_cols_norm) == len(num_cols), "Invalid config: numeric.columns must contain only non-empty strings")
    _expect(len(cat_cols_norm) == len(cat_cols), "Invalid config: categorical.columns must contain only non-empty strings")

    scaler = numeric.get("scaler")
    if scaler is None:
        scaler_norm: Optional[str] = None
    else:
        _expect(_is_non_empty_str(scaler), "Invalid config: numeric.scaler must be a string or null")
        scaler_norm = str(scaler).strip().lower()
        _expect(scaler_norm in {"standard", "minmax", "none"}, "Invalid config: numeric.scaler must be standard|minmax|none|null")
        if scaler_norm == "none":
            scaler_norm = None

    encoder = categorical.get("encoder", "onehot")
    _expect(_is_non_empty_str(encoder), "Invalid config: categorical.encoder must be a string")
    encoder_norm = str(encoder).strip().lower()
    _expect(encoder_norm == "onehot", "Invalid config: categorical.encoder must be onehot in v1")

    handle_unknown = categorical.get("handle_unknown", "ignore")
    _expect(_is_non_empty_str(handle_unknown), "Invalid config: categorical.handle_unknown must be a string")
    handle_unknown_norm = str(handle_unknown).strip()

    drop = categorical.get("drop")
    if drop is None:
        drop_norm: Optional[str] = None
    else:
        _expect(_is_non_empty_str(drop), "Invalid config: categorical.drop must be a string or null")
        drop_norm = str(drop).strip()

    # ---- contract validation (no inference) ----
    roles = _extract_features_roles(contract)

    for c in num_cols_norm:
        _expect(c in roles, f"Invalid config: numeric column not found in contract.features: {c}")
        _expect(roles[c] == "numerical", f"Invalid config: column {c} is not numerical in contract (role={roles[c]})")

    for c in cat_cols_norm:
        _expect(c in roles, f"Invalid config: categorical column not found in contract.features: {c}")
        _expect(roles[c] == "categorical", f"Invalid config: column {c} is not categorical in contract (role={roles[c]})")

    overlap = set(num_cols_norm).intersection(set(cat_cols_norm))
    _expect(len(overlap) == 0, f"Invalid config: columns present in both numeric and categorical: {sorted(overlap)}")

    return PreprocessSpec(
        numeric_columns=num_cols_norm,
        categorical_columns=cat_cols_norm,
        numeric_scaler=scaler_norm,
        categorical_encoder=encoder_norm,
        handle_unknown=handle_unknown_norm,
        drop=drop_norm,
    )


def _build_numeric_pipeline(spec: PreprocessSpec):
    try:
        from sklearn.pipeline import Pipeline  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("scikit-learn is required for representation.preprocess") from e

    if spec.numeric_scaler is None:
        return Pipeline(steps=[("passthrough", "passthrough")])

    if spec.numeric_scaler == "standard":
        from sklearn.preprocessing import StandardScaler  # type: ignore

        scaler = StandardScaler()
    elif spec.numeric_scaler == "minmax":
        from sklearn.preprocessing import MinMaxScaler  # type: ignore

        scaler = MinMaxScaler()
    else:  # pragma: no cover
        raise ValueError(f"Unsupported numeric scaler: {spec.numeric_scaler}")

    return Pipeline(steps=[("scaler", scaler)])


def _build_categorical_pipeline(spec: PreprocessSpec):
    try:
        from sklearn.pipeline import Pipeline  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("scikit-learn is required for representation.preprocess") from e

    if spec.categorical_encoder != "onehot":  # pragma: no cover
        raise ValueError(f"Unsupported categorical encoder: {spec.categorical_encoder}")

    try:
        from sklearn.preprocessing import OneHotEncoder  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("scikit-learn is required for OneHotEncoder") from e

    # sklearn >= 1.2 usa sparse_output; versões antigas usam sparse
    kwargs: Dict[str, Any] = {
        "handle_unknown": spec.handle_unknown,
    }
    if spec.drop is not None:
        kwargs["drop"] = spec.drop

    # Preferimos saída densa para facilitar testes e consistência.
    try:
        enc = OneHotEncoder(sparse_output=False, **kwargs)
    except TypeError:
        enc = OneHotEncoder(sparse=False, **kwargs)

    return Pipeline(steps=[("encoder", enc)])


def build_representation_preprocess(*, contract: Dict[str, Any], config: Dict[str, Any]):
    """Constrói o ColumnTransformer canônico de pré-processamento.

    Args:
        contract: Internal Contract v1 (dict).
        config: Config efetiva (dict), contendo `representation.preprocess`.

    Returns:
        sklearn.compose.ColumnTransformer
    """
    spec = _normalize_spec(contract, config)

    try:
        from sklearn.compose import ColumnTransformer  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("scikit-learn is required for ColumnTransformer") from e

    num_pipe = _build_numeric_pipeline(spec)
    cat_pipe = _build_categorical_pipeline(spec)

    transformers: List[Tuple[str, Any, List[str]]] = []
    if spec.numeric_columns:
        transformers.append(("numeric", num_pipe, list(spec.numeric_columns)))
    if spec.categorical_columns:
        transformers.append(("categorical", cat_pipe, list(spec.categorical_columns)))

    # remainder='drop' para garantir que nenhuma coluna fora do contrato/config passe.
    return ColumnTransformer(transformers=transformers, remainder="drop")


__all__ = ["build_representation_preprocess", "PreprocessSpec"]
