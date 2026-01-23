"""
Inference Bundle — artefato autocontido para inferência (v1).

Este módulo define as estruturas canônicas para:
- persistência (joblib) de um bundle autocontido
- carregamento isolado (round-trip) do bundle
- execução de inferência (predict / predict_proba)
- validação explícita de payload contra contrato congelado (Internal Contract v1)

Alinhado a:
- docs/spec/export.inference_bundle.v1.md
- docs/spec/internal_contract.v1.md
- docs/traceability.md

Limites explícitos (v1):
- Não faz serving HTTP
- Não aplica defaults por heurística
- Não recalcula preprocess
- Não treina/re-treina modelos
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence, Union

import hashlib
import io
import json

try:
    import joblib  # type: ignore
except Exception as e:  # pragma: no cover
    joblib = None  # type: ignore
    _JOBLIB_IMPORT_ERROR = e
else:
    _JOBLIB_IMPORT_ERROR = None


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _contract_feature_names(contract: Dict[str, Any]) -> List[str]:
    feats = contract.get("features")
    if not isinstance(feats, list) or not all(isinstance(x, dict) for x in feats):
        raise ValueError("Invalid contract: features must be list[dict]")
    names: List[str] = []
    for f in feats:
        name = f.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Invalid contract: feature.name must be a non-empty string")
        names.append(name.strip())
    return names


def _contract_feature_dtypes(contract: Dict[str, Any]) -> Dict[str, str]:
    feats = contract.get("features")
    if not isinstance(feats, list) or not all(isinstance(x, dict) for x in feats):
        raise ValueError("Invalid contract: features must be list[dict]")
    out: Dict[str, str] = {}
    for f in feats:
        name = f.get("name")
        dtype = f.get("dtype")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Invalid contract: feature.name must be a non-empty string")
        if not isinstance(dtype, str) or not dtype.strip():
            raise ValueError(f"Invalid contract: feature.dtype is required for {name!r}")
        out[name.strip()] = dtype.strip()
    return out


def _validate_value_dtype(expected: str, v: Any) -> bool:
    """
    Validação explícita (v1) de compatibilidade de tipos.

    Importante:
    - Não faz coerções silenciosas.
    - Strings "1"/"true" NÃO são aceitas para int/bool (isso seria heurística).
    """
    if v is None:
        return False

    exp = expected.strip().lower()
    if exp == "int":
        return isinstance(v, int) and not isinstance(v, bool)
    if exp == "float":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if exp == "bool":
        return isinstance(v, bool)
    if exp == "string":
        return isinstance(v, str)
    if exp == "category":
        # categoria v1: representada como string (sem inferência de aliases)
        return isinstance(v, str)
    # fallback explícito: other
    return True


def validate_payload_against_contract(*, payload: Union[Dict[str, Any], List[Dict[str, Any]]], contract: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Valida payload (single-row ou batch) contra o contrato congelado.

    Regras (v1):
    - payload deve ser dict (1 linha) ou list[dict] (batch)
    - deve conter exatamente as features do contrato (sem colunas extras)
    - não aceita campos faltantes
    - valida tipos conforme feature.dtype (validação estrita)

    Returns:
        Uma lista de dicts (normalizada) para consumo por DataFrame.
    """
    if isinstance(payload, dict):
        rows = [payload]
    elif isinstance(payload, list) and all(isinstance(r, dict) for r in payload):
        rows = payload
    else:
        raise ValueError("Invalid payload: expected dict or list[dict]")

    expected_cols = _contract_feature_names(contract)
    expected_set = set(expected_cols)

    dtypes = _contract_feature_dtypes(contract)

    for i, row in enumerate(rows):
        keys = set(row.keys())
        missing = sorted(expected_set - keys)
        extra = sorted(keys - expected_set)
        if missing:
            raise ValueError(f"Invalid payload: missing columns at row {i}: {missing}")
        if extra:
            raise ValueError(f"Invalid payload: extra columns at row {i}: {extra}")

        # dtype checks (estrito)
        for col in expected_cols:
            exp = dtypes.get(col, "other")
            if not _validate_value_dtype(exp, row.get(col)):
                raise ValueError(f"Invalid payload: incompatible dtype for column={col!r} expected={exp!r} at row {i}")

    # garante estabilidade de colunas (ordem)
    normalized: List[Dict[str, Any]] = []
    for row in rows:
        normalized.append({c: row[c] for c in expected_cols})
    return normalized


@dataclass(frozen=True)
class InferenceBundleV1:
    """
    Bundle de inferência autocontido (v1).

    Conteúdo mínimo:
    - preprocess: objeto sklearn já fitado (ex.: ColumnTransformer)
    - model: estimador treinado (campeão)
    - contract: dict do Internal Contract v1 congelado
    - metrics: dict de métricas finais do campeão
    - metadata: metadados forenses (hashes, run_id, timestamps, etc.)
    """
    preprocess: Any
    model: Any
    contract: Dict[str, Any]
    metrics: Dict[str, Any]
    metadata: Dict[str, Any]

    def predict(self, payload: Union[Dict[str, Any], List[Dict[str, Any]]]):
        rows = validate_payload_against_contract(payload=payload, contract=self.contract)

        try:
            import pandas as pd  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError("pandas is required for inference bundle predict") from e

        X = pd.DataFrame(rows)

        if not hasattr(self.preprocess, "transform"):
            raise ValueError("Invalid bundle: preprocess has no transform()")

        Xt = self.preprocess.transform(X)

        if not hasattr(self.model, "predict"):
            raise ValueError("Invalid bundle: model has no predict()")

        return self.model.predict(Xt)

    def predict_proba(self, payload: Union[Dict[str, Any], List[Dict[str, Any]]]):
        if not hasattr(self.model, "predict_proba"):
            raise AttributeError("Model does not support predict_proba()")

        rows = validate_payload_against_contract(payload=payload, contract=self.contract)

        try:
            import pandas as pd  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError("pandas is required for inference bundle predict_proba") from e

        X = pd.DataFrame(rows)
        Xt = self.preprocess.transform(X)
        return self.model.predict_proba(Xt)


def save_inference_bundle_v1(*, bundle: InferenceBundleV1, path: Union[str, Path]) -> Dict[str, Any]:
    """
    Persiste o bundle em joblib (arquivo único).
    Retorna metadata com hash do arquivo.
    """
    if joblib is None:  # pragma: no cover
        raise RuntimeError("joblib is required for inference bundle persistence") from _JOBLIB_IMPORT_ERROR

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    # Persistimos um dict estável, não a instância (reduz risco de incompatibilidade).
    payload = {
        "version": "v1",
        "preprocess": bundle.preprocess,
        "model": bundle.model,
        "contract": bundle.contract,
        "metrics": bundle.metrics,
        "metadata": bundle.metadata,
    }
    joblib.dump(payload, p)

    file_hash = _sha256_file(p)
    return {"bundle_path": str(p), "bundle_hash": file_hash, "format": "joblib", "version": "v1"}


def load_inference_bundle(*, path: Union[str, Path]) -> InferenceBundleV1:
    """
    Carrega o bundle de inferência (v1) de forma isolada.
    """
    if joblib is None:  # pragma: no cover
        raise RuntimeError("joblib is required for inference bundle load") from _JOBLIB_IMPORT_ERROR

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(str(p))

    obj = joblib.load(p)
    if not isinstance(obj, dict):
        raise ValueError("Invalid bundle: expected dict payload")

    ver = obj.get("version")
    if ver != "v1":
        raise ValueError(f"Unsupported inference bundle version: {ver!r}")

    return InferenceBundleV1(
        preprocess=obj.get("preprocess"),
        model=obj.get("model"),
        contract=obj.get("contract") if isinstance(obj.get("contract"), dict) else {},
        metrics=obj.get("metrics") if isinstance(obj.get("metrics"), dict) else {},
        metadata=obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {},
    )


__all__ = [
    "InferenceBundleV1",
    "save_inference_bundle_v1",
    "load_inference_bundle",
    "validate_payload_against_contract",
]
