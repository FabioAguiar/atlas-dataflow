# 📄 train.search — Treinamento com Busca de Hiperparâmetros (v1)

## Visão Geral

Esta spec define o Step **train.search v1** do **Atlas DataFlow**, responsável por executar
**busca explícita de hiperparâmetros** utilizando `GridSearchCV` ou `RandomizedSearchCV`,
de forma **determinística, auditável e reprodutível**.

O Step evolui naturalmente após `train.single`, mantendo o rigor do Atlas:
nenhuma busca ocorre sem grids, scoring e CV previamente declarados.

---

## Objetivo

- Executar busca de hiperparâmetros de forma controlada
- Suportar GridSearch e RandomizedSearch
- Produzir `best_estimator` e métricas resumidas
- Garantir reprodutibilidade via seed explícita
- Registrar resultados no Manifest

---

## Natureza do Step

- **ID:** `train.search`
- **Kind:** `train`
- **Milestone:** M5 — Modelagem & Avaliação
- **Caráter:** Transformacional (gera modelo treinado)

---

## Dependências

O Step depende semanticamente de:

- `ModelRegistry v1`
- `DefaultSearchGrids v1`
- `representation.preprocess`
- Dataset dividido (train / validation)

---

## Configuração Esperada

```yaml
steps:
  train.search:
    enabled: true
    model_id: random_forest
    search_type: grid   # grid | random
    seed: 42
```

Campos obrigatórios:
- `model_id`
- `search_type`
- `seed`

---

## Comportamento Canônico

O Step deve:

1. Validar `model_id` no `ModelRegistry`
2. Obter grid, scoring e CV do `DefaultSearchGrids`
3. Instanciar o estimador base
4. Executar:
   - `GridSearchCV` ou
   - `RandomizedSearchCV` (conforme configuração)
5. Ajustar o search nos dados de treino
6. Extrair:
   - `best_estimator`
   - `best_params`
   - `best_score`
7. Gerar resumo serializável de `cv_results_`
8. Registrar tudo no Manifest

---

## Resultados Esperados

### Payload mínimo

```yaml
payload:
  model_id: string
  search_type: grid | random
  seed: int
  best_params: dict
  best_score: float
  cv_results_summary:
    - params: dict
      mean_test_score: float
      std_test_score: float
      rank_test_score: int
```

---

## Determinismo

Regras:

- Seed obrigatória
- CV com shuffle e random_state fixo
- Resultados idênticos para dataset fixo

---

## Falhas Explícitas

O Step deve falhar quando:

- `model_id` não existir
- `search_type` for inválido
- grids não estiverem definidos
- preprocess não estiver disponível
- dados de treino não existirem

---

## Testes Esperados

Os testes unitários devem cobrir:

- execução em dataset pequeno
- produção de `best_estimator`
- estrutura válida de `cv_results_summary`
- determinismo com seed fixa
- falha explícita para configuração inválida

---

## Fora de Escopo (v1)

- AutoML
- Busca bayesiana
- Persistência do modelo treinado
- Avaliação avançada (curvas, explicabilidade)

---

## Evolução Futura

Possíveis extensões:

- Suporte a regressão
- Hyperband / Successive Halving
- Persistência integrada
- Visualização de resultados

---

## Referências

- `docs/spec/model_registry.v1.md`
- `docs/spec/default_search_grids.v1.md`
- `docs/spec/train.single.v1.md`
- `docs/pipeline_elements.md`
- `docs/engine.md`
- `docs/traceability.md`
- `docs/testing.md`
