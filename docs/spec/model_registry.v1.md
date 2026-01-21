# 📄 model_registry — Catálogo Canônico de Modelos (v1)

## Visão Geral

Esta spec define o **ModelRegistry v1** do **Atlas DataFlow** — um catálogo determinístico e contrato-dirigido
que centraliza **modelos suportados**, **parâmetros padrão** e **parâmetros expostos para UI/experimentação**.

O objetivo é eliminar decisões implícitas na modelagem e fornecer um **ponto único de verdade** para seleção
e configuração inicial de modelos supervisionados.

---

## Objetivo

- Centralizar a definição de modelos suportados
- Separar **default params** de **ui params**
- Garantir consistência e previsibilidade na criação de modelos
- Facilitar integração com UI e pipelines de avaliação

---

## Natureza do Componente

- **ID:** `model_registry`
- **Tipo:** Registry
- **Milestone:** M5 — Modelagem & Avaliação
- **Caráter:** Determinístico, sem dependência de dados

---

## Modelos Suportados (v1)

### 1) Logistic Regression
- **model_id:** `logistic_regression`
- **Classe:** `sklearn.linear_model.LogisticRegression`
- **Default params (exemplo):**
  - `penalty: "l2"`
  - `C: 1.0`
  - `solver: "lbfgs"`
  - `max_iter: 1000`
- **UI params:**
  - `C` (float, min: 0.001, max: 100.0)
  - `penalty` (enum: ["l2"])
  - `class_weight` (enum: ["balanced", null])

---

### 2) Random Forest
- **model_id:** `random_forest`
- **Classe:** `sklearn.ensemble.RandomForestClassifier`
- **Default params (exemplo):**
  - `n_estimators: 200`
  - `max_depth: null`
  - `random_state: 42`
- **UI params:**
  - `n_estimators` (int, min: 50, max: 1000)
  - `max_depth` (int | null, min: 2, max: 50)
  - `min_samples_split` (int, min: 2, max: 20)

---

### 3) K-Nearest Neighbors
- **model_id:** `knn`
- **Classe:** `sklearn.neighbors.KNeighborsClassifier`
- **Default params (exemplo):**
  - `n_neighbors: 5`
  - `weights: "uniform"`
- **UI params:**
  - `n_neighbors` (int, min: 1, max: 50)
  - `weights` (enum: ["uniform", "distance"])

---

## Interface Canônica

O Registry deve expor, no mínimo:

```python
registry.list() -> List[str]
registry.get(model_id: str) -> ModelSpec
```

Onde `ModelSpec` contém:
- classe do modelo
- default params
- ui params

---

## Invariantes

- Nenhum modelo é inferido dinamicamente
- Todo `model_id` é único
- Default params são **seguros e coerentes**
- UI params **não executam tuning automaticamente**
- Falhas para `model_id` inválido são explícitas

---

## Falhas Explícitas

O Registry deve falhar quando:
- `model_id` não existe
- definição do modelo está incompleta
- parâmetros default inválidos

---

## Testes Esperados

Os testes unitários devem cobrir:
- listagem de modelos suportados
- recuperação de cada `model_id`
- existência e coerência de default params
- exposição correta de ui params
- falha explícita para `model_id` inválido

---

## Fora de Escopo (v1)

- AutoML
- Tuning automático
- Persistência de modelos
- Métricas de avaliação

---

## Evolução Futura

Possíveis extensões:
- Regressão (Linear, Ridge, Lasso)
- Gradient Boosting / XGBoost
- Versionamento de specs
- Compatibilidade com modelos externos

---

## Referências

- `docs/pipeline_elements.md`
- `docs/engine.md`
- `docs/traceability.md`
- `docs/testing.md`
