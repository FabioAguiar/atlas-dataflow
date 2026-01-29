"""Step canônico: train.search (v1).

Executa busca explícita de hiperparâmetros via:
- GridSearchCV
- RandomizedSearchCV

Princípios do Atlas:
- Estratégia declarada (search_type) — nada inferido.
- Fonte de grid declarada (grid_source) — nada inferido.
- Determinismo via seed explícita.
- Resultados auditáveis (best_params, best_score, best_estimator + resumo de cv_results_).
- Sem persistência do modelo treinado (fora de escopo v1).

Config esperada (exemplos):

steps:
  train.search:
    enabled: true
    model_id: random_forest
    search_type: grid         # grid | random
    grid_source: default      # default | paste | bank
    seed: 42
    n_iter: 10                # apenas quando search_type=random
    grid_paste: {...}         # apenas quando grid_source=paste
    grid_bank:
      root_dir: grids
      grid_name: rf_small_v1.yaml

Artifacts esperados (entrada):
- data.train: list[dict]
- data.test: list[dict]
- preprocess.joblib persistido no run_dir (ctx.meta[run_dir]/artifacts/preprocess.joblib)

Artifacts produzidos (saída):
- model.best_estimator: melhor estimador encontrado (não serializável; guardado apenas no RunContext)

Referências:
- docs/spec/train.search.v1.md
- docs/spec/model_registry.v1.md
- docs/spec/default_search_grids.v1.md
- docs/traceability.md
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.core.pipeline.step import Step
from atlas_dataflow.core.pipeline.types import StepKind, StepResult, StepStatus
from atlas_dataflow.modeling.default_search_grids import DefaultSearchGrids
from atlas_dataflow.modeling.model_registry import ModelRegistry
from atlas_dataflow.persistence.preprocess_store import PreprocessStore


def _get_step_cfg(ctx: RunContext, step_id: str) -> Dict[str, Any]:
    steps = ctx.config.get("steps", {}) if isinstance(ctx.config, dict) else {}
    cfg = steps.get(step_id, {}) if isinstance(steps, dict) else {}
    return cfg if isinstance(cfg, dict) else {}


def _require_str(cfg: Dict[str, Any], key: str) -> str:
    v = cfg.get(key)
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"Invalid config: {key} is required")
    return v.strip()


def _require_int(cfg: Dict[str, Any], key: str) -> int:
    v = cfg.get(key)
    if v is None:
        raise ValueError(f"Invalid config: {key} is required")
    if not isinstance(v, int):
        raise ValueError(f"Invalid config: {key} must be an int")
    return int(v)


def _get_run_dir(ctx: RunContext) -> str:
    md = ctx.meta if isinstance(ctx.meta, dict) else {}
    run_dir = md.get("run_dir") or md.get("tmp_path")
    if run_dir is None:
        raise ValueError("Missing required meta: run_dir (or tmp_path)")
    return str(run_dir)


def _get_dataset_parts(ctx: RunContext) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    if not ctx.has_artifact("data.train"):
        raise ValueError("Missing required artifact: data.train")
    if not ctx.has_artifact("data.test"):
        raise ValueError("Missing required artifact: data.test")

    train_rows = ctx.get_artifact("data.train")
    test_rows = ctx.get_artifact("data.test")
    if not isinstance(train_rows, list) or not all(isinstance(r, dict) for r in train_rows):
        raise ValueError("Invalid artifact: data.train must be a list[dict]")
    if not isinstance(test_rows, list) or not all(isinstance(r, dict) for r in test_rows):
        raise ValueError("Invalid artifact: data.test must be a list[dict]")
    return train_rows, test_rows


def _json_safe(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_json_safe(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    return str(obj)


def _apply_seed_if_supported(estimator: Any, seed: int) -> Any:
    try:
        params = estimator.get_params(deep=False)
    except Exception:
        return estimator

    if "random_state" in params:
        try:
            estimator.set_params(random_state=seed)
        except Exception:
            raise ValueError("Estimator does not accept random_state seed")
    return estimator


def _validate_grid_params(estimator: Any, grid: Dict[str, Any], *, model_id: str) -> None:
    if not isinstance(grid, dict):
        raise ValueError("Invalid grid: must be a mapping/dict")
    try:
        est_params = estimator.get_params(deep=True)
    except Exception:
        est_params = {}
    for p in grid.keys():
        if p not in est_params:
            raise ValueError(f"grid param '{p}' not found in estimator params for model_id '{model_id}'")


def _load_grid_from_bank(*, root_dir: str, model_id: str, grid_name: str) -> Dict[str, Any]:
    # Nenhuma descoberta automática: caminho é explícito.
    base = Path(root_dir)
    path = base / model_id / grid_name
    if not path.exists():
        raise FileNotFoundError(str(path))

    try:
        import yaml  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("pyyaml is required for grid_source=bank") from e

    grid_obj = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(grid_obj, dict):
        raise ValueError("Invalid grid bank file: must load to a mapping/dict")
    return grid_obj


def _resolve_grid(cfg: Dict[str, Any], *, model_id: str, grids: DefaultSearchGrids) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
    """Resolve grid_source -> (grid_source, grid, source_meta)."""
    source = cfg.get("grid_source", "default")
    if not isinstance(source, str):
        raise ValueError("Invalid config: grid_source must be a string")
    source = source.strip().lower() or "default"

    if source == "default":
        spec = grids.get(model_id)
        return "default", dict(spec.param_grid), {"grid_source": "default"}

    if source == "paste":
        grid = cfg.get("grid_paste")
        if not isinstance(grid, dict):
            raise ValueError("Invalid config: grid_paste must be a mapping when grid_source=paste")
        return "paste", dict(grid), {"grid_source": "paste"}

    if source == "bank":
        gb = cfg.get("grid_bank")
        if not isinstance(gb, dict):
            raise ValueError("Invalid config: grid_bank must be a mapping when grid_source=bank")
        root_dir = gb.get("root_dir")
        grid_name = gb.get("grid_name")
        if not isinstance(root_dir, str) or not root_dir.strip():
            raise ValueError("Invalid config: grid_bank.root_dir is required")
        if not isinstance(grid_name, str) or not grid_name.strip():
            raise ValueError("Invalid config: grid_bank.grid_name is required")
        grid = _load_grid_from_bank(root_dir=str(root_dir), model_id=model_id, grid_name=str(grid_name))
        return "bank", dict(grid), {"grid_source": "bank", "grid_bank": {"root_dir": str(root_dir), "grid_name": str(grid_name)}}

    raise ValueError("Invalid config: grid_source must be one of: default, paste, bank")


def _build_search(
    *,
    search_type: str,
    estimator: Any,
    param_grid: Dict[str, Any],
    scoring: str,
    cv: Any,
    seed: int,
    n_iter: int,
) -> Any:
    try:
        from sklearn.model_selection import GridSearchCV, RandomizedSearchCV  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("scikit-learn is required for train.search") from e

    if search_type == "grid":
        return GridSearchCV(
            estimator=estimator,
            param_grid=param_grid,
            scoring=scoring,
            cv=cv,
            refit=True,
            n_jobs=None,
        )

    if search_type == "random":
        return RandomizedSearchCV(
            estimator=estimator,
            param_distributions=param_grid,
            n_iter=n_iter,
            scoring=scoring,
            cv=cv,
            refit=True,
            random_state=seed,
            n_jobs=None,
        )

    raise ValueError("Invalid config: search_type must be one of: grid, random")


def _summarize_cv_results(cv_results: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Resumo serializável e compacto de cv_results_."""
    rows: List[Dict[str, Any]] = []
    params_list = cv_results.get("params", [])
    mean = cv_results.get("mean_test_score", [])
    std = cv_results.get("std_test_score", [])
    rank = cv_results.get("rank_test_score", [])

    n = len(params_list)
    for i in range(n):
        rows.append(
            {
                "mean_test_score": float(mean[i]) if i < len(mean) else None,
                "std_test_score": float(std[i]) if i < len(std) else None,
                "rank_test_score": int(rank[i]) if i < len(rank) else None,
                "params": _json_safe(params_list[i]) if i < len(params_list) else {},
            }
        )
    return rows


@dataclass
class TrainSearchStep(Step):
    """Busca de hiperparâmetros (Grid/Random) com grids explícitos (default/paste/bank)."""

    id: str = "train.search"
    kind: StepKind = StepKind.TRAIN
    depends_on: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.depends_on is None:
            self.depends_on = [
                "train.single",  # semântico (baseline pronto) — não impede execução isolada em testes
            ]

    def run(self, ctx: RunContext) -> StepResult:
        try:
            cfg = _get_step_cfg(ctx, self.id)
            if cfg.get("enabled") is False:
                return StepResult(
                    step_id=self.id,
                    kind=self.kind,
                    status=StepStatus.SUCCESS,
                    summary="train.search skipped (disabled in config)",
                    metrics={},
                    warnings=[],
                    artifacts={},
                    payload={"skipped": True},
                )

            model_id = _require_str(cfg, "model_id")
            seed = _require_int(cfg, "seed")
            search_type = _require_str(cfg, "search_type").lower()
            if search_type not in {"grid", "random"}:
                raise ValueError("Invalid config: search_type must be one of: grid, random")

            n_iter = int(cfg.get("n_iter", 10))
            if search_type == "random":
                if not isinstance(n_iter, int) or n_iter <= 0:
                    raise ValueError("Invalid config: n_iter must be a positive int when search_type=random")

            # ---- inputs ----
            train_rows, test_rows = _get_dataset_parts(ctx)
            run_dir = _get_run_dir(ctx)

            # ---- contract / target ----
            contract = ctx.contract or {}
            target = contract.get("target") if isinstance(contract, dict) else None
            if not isinstance(target, dict):
                raise ValueError("Invalid contract: target must be a mapping")
            target_name = target.get("name")
            if not isinstance(target_name, str) or not target_name.strip():
                raise ValueError("Invalid contract: target.name is required")
            target_col = target_name.strip()

            # ---- pandas ----
            try:
                import pandas as pd  # type: ignore
            except Exception as e:  # pragma: no cover
                raise RuntimeError("pandas is required for train.search") from e

            df_train = pd.DataFrame(train_rows)
            df_test = pd.DataFrame(test_rows)

            if target_col not in df_train.columns:
                raise ValueError(f"Target column not found in train data: {target_col}")
            if target_col not in df_test.columns:
                raise ValueError(f"Target column not found in test data: {target_col}")

            y_train = df_train[target_col]
            X_train = df_train.drop(columns=[target_col])
            X_test = df_test.drop(columns=[target_col])  # noqa: F841 (mantido para simetria / debug)

            # ---- preprocess ----
            preprocess = PreprocessStore(run_dir=run_dir).load()

            # Fit somente uma vez no treino (v1).
            preprocess.fit(X_train)
            Xtr = preprocess.transform(X_train)

            # ---- model + grids ----
            registry = ModelRegistry.v1()
            try:
                estimator = registry.build(model_id)
            except KeyError as e:
                raise ValueError(str(e).replace("'", ""))

            estimator = _apply_seed_if_supported(estimator, seed)

            grids = DefaultSearchGrids.v1()
            grid_source, param_grid, grid_meta = _resolve_grid(cfg, model_id=model_id, grids=grids)
            _validate_grid_params(estimator, param_grid, model_id=model_id)

            spec = grids.get(model_id)
            scoring = str(spec.scoring)
            cv = spec.cv.build(seed=seed)

            search = _build_search(
                search_type=search_type,
                estimator=estimator,
                param_grid=param_grid,
                scoring=scoring,
                cv=cv,
                seed=seed,
                n_iter=n_iter,
            )

            search.fit(Xtr, y_train)

            best_estimator = search.best_estimator_
            best_params = _json_safe(getattr(search, "best_params_", {}))
            best_score = float(getattr(search, "best_score_", 0.0))

            cv_results = getattr(search, "cv_results_", {}) or {}
            cv_summary = _summarize_cv_results(cv_results)

            # ---- artifacts ----
            ctx.set_artifact("model.best_estimator", best_estimator)

            payload = {
                "model_id": model_id,
                "search_type": search_type,
                "grid_source": grid_source,
                "seed": seed,
                "scoring": scoring,
                "cv": spec.cv.to_dict(),
                "best_params": best_params,
                "best_score": best_score,
                "cv_results": cv_summary,
            }
            payload.update(grid_meta)

            ctx.log(
                step_id=self.id,
                level="info",
                message="train.search completed",
                model_id=model_id,
                search_type=search_type,
                grid_source=grid_source,
                best_score=best_score,
            )

            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.SUCCESS,
                summary="train.search completed",
                metrics={"best_score": best_score},
                warnings=[],
                artifacts={"model.best_estimator": "model.best_estimator"},
                payload=payload,
            )

        except Exception as e:
            ctx.log(
                step_id=self.id,
                level="error",
                message="train.search failed",
                error_type=e.__class__.__name__,
                error_message=str(e) or "error",
            )
            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.FAILED,
                summary=str(e) or "train.search failed",
                metrics={},
                warnings=[],
                artifacts={},
                payload={"error": {"type": e.__class__.__name__, "message": str(e) or "error"}},
            )


__all__ = ["TrainSearchStep"]
