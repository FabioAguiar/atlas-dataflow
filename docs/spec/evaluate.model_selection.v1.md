# 📄 evaluate.model_selection — Seleção de Modelo Campeão (v1)

## Visão Geral

Esta spec define o Step **evaluate.model_selection v1** do **Atlas DataFlow**, responsável por
**selecionar explicitamente o modelo campeão** após a avaliação padronizada de métricas.

No Atlas, a decisão de promoção de modelo é **um ato explícito e auditável**, nunca um efeito
colateral do treino ou da busca.

---

## Objetivo

- Selecionar o modelo campeão com base em **métrica alvo configurável**
- Registrar critério, ranking e decisão no Manifest
- Garantir decisão **determinística e reprodutível**

---

## Natureza do Step

- **ID:** `evaluate.model_selection`
- **Kind:** `evaluate`
- **Milestone:** M5 — Modelagem & Avaliação
- **Caráter:** Decisório (não treina nem avalia novamente)

---

## Dependências

O Step depende semanticamente de:

- `evaluate.metrics`
- Múltiplos modelos avaliados no mesmo contexto
- Métricas comparáveis (mesmo dataset/split)

---

## Configuração Esperada

```yaml
steps:
  evaluate.model_selection:
    enabled: true
    target_metric: f1
    direction: maximize   # maximize | minimize
```

Campos obrigatórios:
- `target_metric`
- `direction`

---

## Comportamento Canônico

O Step deve:

1. Validar a existência da métrica alvo em todos os candidatos
2. Ordenar modelos conforme `direction`
3. Resolver empates de forma determinística
4. Selecionar o **campeão**
5. Registrar ranking completo e decisão final

---

## Payload Esperado (mínimo)

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

---

## Regras de Determinismo

- Empates devem ser resolvidos por regra explícita (ex.: ordem estável de execução)
- Mesmos inputs → mesmo campeão
- Nenhuma métrica é inferida automaticamente

---

## Falhas Explícitas

O Step deve falhar quando:

- nenhuma métrica estiver disponível
- `target_metric` não existir
- direção inválida
- candidatos não comparáveis

---

## Testes Esperados

Os testes unitários devem cobrir:

- seleção correta do campeão
- respeito à métrica alvo
- resolução determinística de empates
- payload consistente
- falha explícita para configuração inválida

---

## Fora de Escopo (v1)

- Seleção multiobjetivo
- Ensemble
- Pareto frontier
- Visualizações

---

## Evolução Futura

Possíveis extensões:

- Seleção multi-métrica
- Regras customizadas de desempate
- Integração com leaderboard
- Persistência de decisões

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
