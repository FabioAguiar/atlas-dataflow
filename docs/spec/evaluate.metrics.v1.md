# 📄 evaluate.metrics — Avaliação Padronizada de Métricas (v1)

## Visão Geral

Esta spec define o Step **evaluate.metrics v1** do **Atlas DataFlow**, responsável por
**avaliar modelos treinados de forma padronizada**, garantindo métricas
**consistentes, comparáveis e auditáveis** ao longo do pipeline.

No Atlas, avaliação **não é implícita nem acoplada ao treino**: ela ocorre em um Step
dedicado, com payload estável e regras explícitas.

---

## Objetivo

- Calcular métricas padronizadas de classificação
- Gerar confusion matrix estruturada
- Garantir consistência entre execuções
- Registrar resultados de avaliação no Manifest

---

## Natureza do Step

- **ID:** `evaluate.metrics`
- **Kind:** `evaluate`
- **Milestone:** M5 — Modelagem & Avaliação
- **Caráter:** Diagnóstico (não altera dados nem modelos)

---

## Dependências

O Step depende semanticamente de:

- `train.single` **ou** `train.search`
- Modelo treinado disponível no RunContext
- Dataset de avaliação (test/validation)

---

## Configuração Esperada

```yaml
steps:
  evaluate.metrics:
    enabled: true
```

Nenhum parâmetro opcional é inferido implicitamente.

---

## Métricas Calculadas (v1)

### Obrigatórias

- `accuracy`
- `precision`
- `recall`
- `f1`

### Condicional

- `roc_auc`
  - calculada **apenas quando aplicável**
  - classificação binária
  - scores/probabilidades disponíveis

---

## Confusion Matrix

O Step deve gerar:

- matriz de confusão completa
- formato serializável
- labels explícitos

Formato mínimo esperado:

```yaml
confusion_matrix:
  labels: [0, 1]
  matrix:
    - [tn, fp]
    - [fn, tp]
```

---

## Payload Esperado (mínimo)

```yaml
payload:
  metrics:
    accuracy: float
    precision: float
    recall: float
    f1: float
    roc_auc: float | null
  confusion_matrix:
    labels: list
    matrix: list[list[int]]
```

---

## Invariantes

- Métricas sempre presentes (exceto `roc_auc`)
- Nomes e formatos estáveis
- Nenhuma métrica inferida automaticamente
- Nenhuma mutação de dados ou modelo

---

## Falhas Explícitas

O Step deve falhar quando:

- modelo treinado não existir
- dados de avaliação não estiverem disponíveis
- formatos de input forem inválidos

---

## Testes Esperados

Os testes unitários devem cobrir:

- presença das métricas obrigatórias
- ausência de `roc_auc` quando não aplicável
- cálculo correto da confusion matrix
- payload serializável e consistente
- falha explícita para inputs inválidos

---

## Fora de Escopo (v1)

- Curvas ROC / PR
- Métricas customizadas
- Visualizações
- Persistência de resultados

---

## Evolução Futura

Possíveis extensões:

- Métricas por classe
- Curvas ROC/PR
- Métricas customizadas por domínio
- Integração com leaderboard

---

## Referências

- `docs/spec/train.single.v1.md`
- `docs/spec/train.search.v1.md`
- `docs/pipeline_elements.md`
- `docs/engine.md`
- `docs/traceability.md`
- `docs/manifest.schema.v1.md`
- `docs/testing.md`
