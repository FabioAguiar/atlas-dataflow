# 📄 evaluate.model_selection — Seleção de Modelo Campeão (v1)

## Visão Geral

Esta spec define o Step **evaluate.model_selection v1** do **Atlas DataFlow**, responsável por
**selecionar explicitamente o modelo campeão** após a avaliação padronizada de métricas.

No Atlas, a decisão de promoção de modelo é **um ato explícito e auditável**, nunca um efeito
colateral do treino, da busca ou de qualquer outro Step.

---

## Objetivo

- Selecionar o modelo campeão com base em **métrica alvo configurável**
- Registrar critério, ranking e decisão de forma **serializável e estável**
- Garantir decisão **determinística e reprodutível** para inputs fixos

---

## Natureza do Step

- **ID:** `evaluate.model_selection`
- **Kind:** `evaluate`
- **Milestone:** M5 — Modelagem & Avaliação
- **Caráter:** Decisório (não treina nem recalcula métricas)

---

## Dependências

O Step depende semanticamente de:

- `evaluate.metrics`
- Métricas comparáveis (mesmo split/dataset de avaliação)
- Conjunto de candidatos (um por modelo) disponível no RunContext

---

## Configuração Esperada

```yaml
steps:
  evaluate.model_selection:
    enabled: true
    target_metric: f1
    direction: maximize   # maximize | minimize
```

Campos:
- `enabled` (opcional, default: true)
- `target_metric` (obrigatório)
- `direction` (obrigatório: `maximize` | `minimize`)

---

## Entradas (Artifacts esperados)

O Step **não faz descoberta automática** de fontes de métricas. Ele suporta somente
artifacts explícitos, com formatos estáveis:

### A) `eval.metrics` como lista (recomendado)
Artifact: `eval.metrics`

```yaml
- model_id: logistic_regression
  metrics:
    f1: 0.81
    accuracy: 0.79
- model_id: random_forest
  metrics:
    f1: 0.83
    accuracy: 0.78
```

### B) `eval.metrics` como dict (caso unitário)
Artifact: `eval.metrics`

```yaml
model_id: logistic_regression
metrics:
  f1: 0.81
  accuracy: 0.79
```

### C) `eval.metrics_list` como lista (compat / alternativa explícita)
Artifact: `eval.metrics_list`  
Mesmo formato do item A.

> Regras de validação:
> - `model_id` é obrigatório em cada candidato (não-inferência).
> - `metrics` deve ser um mapping/dict.
> - `target_metric` deve existir em **todos** os candidatos.

---

## Comportamento Canônico

O Step deve:

1. Ler `target_metric` e `direction` da configuração
2. Carregar a lista de candidatos a partir de `eval.metrics_list` **ou** `eval.metrics`
3. Validar:
   - existência de `model_id`
   - presença de `metrics[target_metric]`
4. Produzir um **ranking** ordenado conforme `direction`
5. Resolver empates de forma **determinística**
6. Selecionar o primeiro do ranking como **campeão**
7. Persistir o payload final no artifact `eval.model_selection`
8. Registrar a decisão (critério + campeão) de forma rastreável no runtime/manifest

---

## Payload Esperado (mínimo)

Artifact gerado: `eval.model_selection`

```yaml
payload:
  selection:
    metric: string
    direction: maximize | minimize
    champion_model_id: string
    champion_score: float
    ranking:
      - model_id: string
        score: float
```

Regras:
- Payload **100% serializável**
- `ranking` deve ser **determinístico** e **estável**
- Nada é inferido automaticamente

---

## Regras de Determinismo (desempate)

Empates são resolvidos por regra explícita e estável:

1. Ordenação primária por `score`:
   - `maximize`: maior score primeiro
   - `minimize`: menor score primeiro
2. Em caso de empate, ordenar por `model_id` em ordem **lexicográfica crescente**

Assim:
- Mesmos inputs → mesmo campeão
- Decisão reproduzível em execuções distintas

---

## Falhas Explícitas

O Step deve falhar quando:

- nenhum artifact de métricas existir (`eval.metrics` ou `eval.metrics_list`)
- lista de candidatos estiver vazia
- `target_metric` não existir para algum candidato
- `direction` inválida
- `metrics` não for dict / score não for numérico

---

## Testes Esperados

Os testes unitários devem cobrir:

- seleção correta do campeão (`maximize` e `minimize`)
- respeito à métrica alvo
- desempate determinístico
- suporte a `eval.metrics` como lista e como dict
- falha explícita para configurações inválidas e inputs ausentes
- comportamento **skip** quando `enabled: false`

---

## Fora de Escopo (v1)

- Seleção multiobjetivo / Pareto
- Ensemble automático
- Visualizações / dashboards
- Persistência de modelos ou artefatos de treino (isso pertence a outras issues)

---

## Evolução Futura

Possíveis extensões:

- seleção multi-métrica (ex.: regra ponderada)
- critérios customizados (por domínio)
- integração com leaderboard persistente
- persistência do “campeão” como artefato versionado do run

---

## Referências

- `docs/spec/evaluate.metrics.v1.md`
- `docs/spec/train.single.v1.md`
- `docs/spec/train.search.v1.md`
- `docs/pipeline_elements.md`
- `docs/engine.md`
- `docs/traceability.md`
- `docs/manifest.schema.v1.md`
- `docs/testing.md`
