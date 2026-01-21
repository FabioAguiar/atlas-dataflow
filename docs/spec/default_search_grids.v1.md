# 📄 default_search_grids — Grids Canônicos de Busca (v1)

## Visão Geral

Esta spec define o componente **DefaultSearchGrids v1** do **Atlas DataFlow**, responsável por
centralizar **grids de busca de hiperparâmetros**, **métrica de scoring padrão** e
**configuração de cross-validation**, de forma **determinística e explícita**.

No Atlas, **nenhuma busca começa de forma implícita**: todo espaço de busca deve ser
declarado, auditável e alinhado ao domínio.

---

## Objetivo

- Definir grids de hiperparâmetros por modelo
- Garantir compatibilidade entre grid e estimador
- Estabelecer scoring e CV padrão
- Servir como base para GridSearchCV / RandomizedSearchCV

---

## Natureza do Componente

- **ID:** `default_search_grids`
- **Tipo:** Registry / Search
- **Milestone:** M5 — Modelagem & Avaliação
- **Caráter:** Determinístico, sem dependência de dados

---

## Relação com o ModelRegistry

O DefaultSearchGrids **depende semanticamente** do `ModelRegistry`:

- todo `model_id` referenciado deve existir no `ModelRegistry`
- todo parâmetro do grid deve existir no estimador correspondente

---

## Estrutura Canônica

Interface mínima esperada:

```python
grids.get(model_id) -> SearchSpec
```

Onde `SearchSpec` contém:
- `param_grid`
- `scoring`
- `cv`

---

## Grids Suportados (v1)

### 1) Logistic Regression

- **model_id:** `logistic_regression`
- **param_grid:**
```python
{
  "C": [0.01, 0.1, 1.0, 10.0],
  "class_weight": [None, "balanced"]
}
```
- **scoring:** `f1`
- **cv:** `StratifiedKFold(n_splits=5, shuffle=True, random_state=42)`

---

### 2) Random Forest

- **model_id:** `random_forest`
- **param_grid:**
```python
{
  "n_estimators": [100, 200, 500],
  "max_depth": [None, 10, 20],
  "min_samples_split": [2, 5, 10]
}
```
- **scoring:** `f1`
- **cv:** `StratifiedKFold(n_splits=5, shuffle=True, random_state=42)`

---

### 3) K-Nearest Neighbors

- **model_id:** `knn`
- **param_grid:**
```python
{
  "n_neighbors": [3, 5, 7, 11],
  "weights": ["uniform", "distance"]
}
```
- **scoring:** `accuracy`
- **cv:** `StratifiedKFold(n_splits=5, shuffle=True, random_state=42)`

---

## Invariantes

- Grids são **conservadores** (baseline)
- Nenhum parâmetro inexistente no estimador
- Scoring explícito
- CV reprodutível (seed fixa)
- Falha explícita para `model_id` inválido

---

## Falhas Explícitas

O componente deve falhar quando:

- `model_id` não existir
- `param_grid` referenciar parâmetro inválido
- scoring não for reconhecido
- configuração de CV for inválida

---

## Testes Esperados

Os testes unitários devem cobrir:

- estrutura válida do grid
- compatibilidade grid ↔ estimador
- existência de scoring
- existência de CV
- falha explícita para `model_id` inválido

---

## Fora de Escopo (v1)

- AutoML
- Busca bayesiana
- Hyperband
- Execução da busca
- Persistência de resultados

---

## Evolução Futura

Possíveis extensões:

- Grids por tipo de problema (binário / multiclasse)
- RandomizedSearch default
- Suporte a regressão
- Versionamento semântico de grids

---

## Referências

- `docs/spec/model_registry.v1.md`
- `docs/pipeline_elements.md`
- `docs/engine.md`
- `docs/traceability.md`
- `docs/testing.md`
