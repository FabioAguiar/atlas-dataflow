# 📄 model_registry — Catálogo Canônico de Modelos (v1)

## Visão Geral

Esta spec define o **ModelRegistry v1** do **Atlas DataFlow** — um catálogo determinístico,
explícito e contrato-dirigido que centraliza:

- modelos supervisionados suportados
- parâmetros padrão (default params)
- parâmetros expostos para UI / experimentação controlada

O objetivo é **eliminar decisões implícitas na modelagem**, garantindo que qualquer modelo
utilizado no pipeline seja:

- conhecido
- rastreável
- configurável apenas dentro de limites declarados

---

## Objetivo

- Centralizar a definição de modelos suportados
- Separar claramente **default params** de **ui params**
- Garantir consistência entre treino, validação e inferência
- Permitir extensão **explícita** do catálogo sem inferência automática

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
- **Default params:**
  - `penalty: "l2"`
  - `C: 1.0`
  - `solver: "lbfgs"`
  - `max_iter: 1000`
- **UI params:**
  - `C` → float (min: 0.001, max: 100.0)
  - `penalty` → enum: [`"l2"`]
  - `class_weight` → enum: [`"balanced"`, null]

---

### 2) Random Forest
- **model_id:** `random_forest`
- **Classe:** `sklearn.ensemble.RandomForestClassifier`
- **Default params:**
  - `n_estimators: 200`
  - `max_depth: null`
  - `random_state: 42`
- **UI params:**
  - `n_estimators` → int (min: 50, max: 1000)
  - `max_depth` → int | null (min: 2, max: 50)
  - `min_samples_split` → int (min: 2, max: 20)

---

### 3) K-Nearest Neighbors
- **model_id:** `knn`
- **Classe:** `sklearn.neighbors.KNeighborsClassifier`
- **Default params:**
  - `n_neighbors: 5`
  - `weights: "uniform"`
- **UI params:**
  - `n_neighbors` → int (min: 1, max: 50)
  - `weights` → enum: [`"uniform"`, `"distance"`]

---

## Interface Canônica

O ModelRegistry deve expor, no mínimo:

```python
registry.list() -> List[str]
registry.get(model_id: str) -> ModelSpec
registry.build(model_id: str, overrides: dict | None = None) -> Estimator
registry.register(spec: ModelSpec) -> None
```

Onde `ModelSpec` contém:

- `model_id: str`
- `estimator_cls: type`
- `default_params: dict`
- `ui_params: dict[str, ParamSpec]`

---

## Extensão do Catálogo (Adição de Novos Modelos)

### Princípio Fundamental

> **Nenhum modelo pode ser inferido automaticamente.**  
> A extensão do catálogo ocorre **somente por registro explícito**.

Adicionar um novo modelo **não exige modificar código interno do Registry**.
Basta declarar um novo `ModelSpec` e registrá-lo manualmente.

### Exemplo: adicionando um novo modelo

```python
from sklearn.svm import SVC
from atlas_dataflow.modeling.model_registry import ModelRegistry, ModelSpec, ParamSpec

svc_spec = ModelSpec(
    model_id="svc",
    estimator_cls=SVC,
    default_params={
        "C": 1.0,
        "kernel": "rbf",
        "probability": True,
    },
    ui_params={
        "C": ParamSpec(type="float", min=0.001, max=100.0),
        "kernel": ParamSpec(type="enum", choices=["linear", "rbf", "poly"]),
    },
)

registry = ModelRegistry.v1()
registry.register(svc_spec)
```

### Regras de Extensão

- O `model_id` deve ser único
- Todos os parâmetros devem ser explicitamente declarados
- Nenhum parâmetro oculto pode ser exposto à UI
- O Registry **não valida dados**, apenas estrutura
- Nenhuma descoberta automática de modelos é permitida

---

## Invariantes

- Nenhum modelo é inferido dinamicamente
- Todo `model_id` é único
- Default params são seguros e determinísticos
- UI params não executam tuning automaticamente
- Falhas são explícitas e imediatas

---

## Falhas Explícitas

O Registry deve falhar quando:

- `model_id` não existe
- um modelo duplicado é registrado
- parâmetros default inválidos são fornecidos
- UI params mal definidos

---

## Testes Esperados

Os testes unitários devem cobrir:

- listagem de modelos suportados
- recuperação por `model_id`
- coerência de default params
- exposição correta de ui params
- registro explícito de novos modelos
- falha explícita para `model_id` inválido

---

## Fora de Escopo (v1)

- AutoML
- Tuning automático
- Persistência de modelos
- Métricas de avaliação
- Descoberta dinâmica de modelos

---

## Evolução Futura

Possíveis extensões:

- Modelos de regressão (Linear, Ridge, Lasso)
- Gradient Boosting / XGBoost
- Versionamento de `ModelSpec`
- Validação cruzada integrada (M6)

---

## Referências

- `docs/pipeline_elements.md`
- `docs/engine.md`
- `docs/traceability.md`
- `docs/testing.md`
