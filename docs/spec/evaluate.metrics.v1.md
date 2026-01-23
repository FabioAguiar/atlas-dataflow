# 📄 evaluate.metrics — Avaliação Padronizada de Métricas (v1)

## Visão Geral

Esta spec define o Step **evaluate.metrics v1** do **Atlas DataFlow**, responsável por
**avaliar modelos treinados de forma padronizada**, garantindo métricas
**consistentes, comparáveis e auditáveis** ao longo do pipeline.

No Atlas, avaliação **não é implícita nem acoplada ao treino**: ela ocorre em um Step
dedicado, com **payload estável** e regras explícitas.

---

## Objetivo

- Calcular métricas padronizadas de classificação
- Gerar confusion matrix estruturada
- (Quando aplicável) calcular `roc_auc`
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
- **Modelo treinado disponível no RunContext**
- **Preprocess persistido** (artefato joblib)
- Dataset de avaliação (test/validation)

### Artifacts esperados (entrada)

- **Modelo** (um dos dois, com preferência por `train.search`):
  - `model.best_estimator` *(preferencial)*
  - `model.trained` *(fallback)*
- **Dados de avaliação**:
  - `data.test`: `list[dict]` (linhas já serializadas)
- **Preprocess persistido**:
  - `artifacts/preprocess.joblib` (via `PreprocessStore` no `run_dir`)

> Nota: o Step **não** recalcula preprocess. Ele apenas **carrega** e aplica `transform()`.

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

Regras:
- métricas calculadas de forma determinística para dataset fixo
- `zero_division=0` em métricas que exigem divisão (evita exceções por classe ausente)

### Condicional

- `roc_auc`
  - calculada **apenas quando aplicável**
  - classificação binária
  - **scores/probabilidades disponíveis**, via:
    - `predict_proba` (preferencial) **ou**
    - `decision_function`

> Importante: `roc_auc` **não deve** ser inferida silenciosamente.  
> Quando não aplicável, o campo **pode ser omitido** do payload (preferencial) ou ser `null`.

---

## Confusion Matrix

O Step deve gerar:

- matriz de confusão completa
- formato serializável
- labels explícitos e estáveis

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
  model_artifact: string  # "model.best_estimator" | "model.trained"
  metrics:
    accuracy: float
    precision: float
    recall: float
    f1: float
    roc_auc: float | null  # condicional (pode ser omitido)
  confusion_matrix:
    labels: list
    matrix: list[list[int]]
```

### Artifact produzido (saída)

- `eval.metrics`: payload serializável (igual ao payload acima)

---

## Invariantes

- Métricas obrigatórias sempre presentes
- `roc_auc` apenas quando aplicável
- Nomes e formatos estáveis
- Nenhuma métrica adicional inferida automaticamente
- Nenhuma mutação de dados ou modelo
- Sem treino/retreino; sem recálculo de preprocess

---

## Falhas Explícitas

O Step deve falhar quando:

- modelo treinado não existir (`model.best_estimator` e `model.trained` ausentes)
- `data.test` não estiver disponível ou estiver em formato inválido
- preprocess persistido não existir no `run_dir`
- coluna target não existir nos dados de avaliação (conforme contrato)

---

## Testes Esperados

Os testes unitários devem cobrir:

- presença das métricas obrigatórias
- cálculo correto da confusion matrix
- `roc_auc` presente apenas quando aplicável
- payload serializável e consistente
- falha explícita para inputs inválidos

---

## Fora de Escopo (v1)

- Curvas ROC / PR
- Métricas customizadas por domínio
- Visualizações
- Persistência de resultados (além do registro canônico no Manifest)

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
- `docs/spec/representation.preprocess.v1.md`
- `docs/spec/persistence.preprocess.v1.md`
- `docs/pipeline_elements.md`
- `docs/engine.md`
- `docs/traceability.md`
- `docs/manifest.schema.v1.md`
- `docs/testing.md`
