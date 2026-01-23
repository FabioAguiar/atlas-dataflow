# 📄 train.search — Treinamento com Busca de Hiperparâmetros (v1)

## Visão Geral

Esta spec define o Step **`train.search v1`** do **Atlas DataFlow**, responsável por executar
**busca explícita e controlada de hiperparâmetros** utilizando **GridSearchCV** ou
**RandomizedSearchCV**, garantindo **determinismo**, **auditabilidade** e **rastreabilidade**.

No Atlas, **a busca nunca é implícita**: estratégia, grid, scoring e cross-validation
devem ser declarados de forma explícita.

---

## Objetivo

- Executar busca de hiperparâmetros de forma controlada
- Suportar GridSearch e RandomizedSearch
- Permitir múltiplas fontes explícitas de grid
- Produzir resultados auditáveis
- Garantir reprodutibilidade

---

## Natureza do Step

- **ID:** `train.search`
- **Kind:** `train`
- **Milestone:** M5 — Modelagem & Avaliação
- **Caráter:** Transformacional (gera modelo treinado via search)

---

## Dependências

O Step depende semanticamente de:

- `ModelRegistry v1`
- `DefaultSearchGrids v1`
- `representation.preprocess`
- Dataset já dividido (train/test)

Nenhuma dessas dependências pode ser inferida automaticamente.

---

## Fontes de Grid (Grid Source)

O Step suporta **somente fontes explícitas**, definidas via configuração.

### 1) `default`
- Usa o grid retornado por:
  ```python
  DefaultSearchGrids.get(model_id)
  ```

### 2) `paste`
- Usa grid fornecido diretamente via config (YAML/JSON)
- O conteúdo colado é considerado **fonte única de verdade**

### 3) `bank` (GridBank file-based)
- Usa grid carregado de arquivo declarativo
- Arquivo referenciado explicitamente por nome
- Nenhuma descoberta automática é permitida

---

## Execução da Busca

O Step deve:

1. Resolver o estimador via `ModelRegistry`
2. Resolver o grid conforme a fonte configurada
3. Executar explicitamente:
   - `GridSearchCV`, ou
   - `RandomizedSearchCV`
4. Ajustar (`fit`) **somente** nos dados de treino

O Step **não deve**:
- inferir grids
- modificar grids
- persistir modelos treinados (v1)

---

## Resultados Produzidos

O Step deve produzir, no mínimo:

- `best_estimator`
- `best_params`
- `best_score`
- resumo serializável de `cv_results_`, contendo:
  - `mean_test_score`
  - `std_test_score`
  - `rank_test_score`
  - `params`

---

## Determinismo

Para garantir reprodutibilidade, o Step deve:

- aceitar `seed` explícita
- usar CV com seed fixa (quando aplicável)
- registrar no Manifest:
  - seed
  - scoring
  - CV
  - fonte do grid utilizada

---

## Configuração Canônica (exemplo)

```yaml
steps:
  train.search:
    enabled: true
    model_id: random_forest
    search_type: grid        # grid | random
    grid_source: bank        # default | paste | bank
    grid_bank:
      root_dir: grids
      grid_name: rf_small_v1.yaml
    seed: 42
```

---

## Invariantes

- Nenhuma inferência automática
- Grid sempre explícito
- Execução determinística
- Resultados auditáveis
- Falhas explícitas

---

## Falhas Explícitas

O Step deve falhar quando:

- `model_id` inválido
- grid inexistente
- grid com parâmetros inválidos
- configuração ambígua ou incompleta

---

## Testes Esperados

Os testes unitários devem cobrir:

- execução com dataset pequeno
- produção de `best_estimator`
- resumo correto de `cv_results_`
- determinismo com seed fixa
- uso de grid default / paste / bank
- falha explícita para configurações inválidas

---

## Fora de Escopo (v1)

- AutoML
- Busca bayesiana
- Hyperband
- Persistência de modelos treinados
- Visualização avançada

---

## Referências

- `docs/spec/model_registry.v1.md`
- `docs/spec/default_search_grids.v1.md`
- `docs/spec/train.single.v1.md`
- `docs/pipeline_elements.md`
- `docs/engine.md`
- `docs/traceability.md`
- `docs/manifest.schema.v1.md`
- `docs/testing.md`
