# Atlas DataFlow — Pipeline Elements Canonical Catalog

## 1. Propósito do Documento

Este documento define o **catálogo canônico de elementos do pipeline** do **Atlas DataFlow**.  
Ele descreve **etapas (steps)**, seus papéis semânticos, contratos de entrada/saída e **payloads de auditoria**.

Este documento deve ser tratado como **fonte de verdade operacional** para:
- implementação do core do pipeline
- definição de use cases internos
- desenho de APIs e adapters
- validação de testes e manifest

Qualquer elemento implementado que **não esteja descrito aqui** deve ser considerado **incompleto ou experimental**.

---

## 2. Conceitos Fundamentais

### 2.1 Step

Um **Step** é a menor unidade executável do pipeline.

Cada Step possui:
- identidade semântica estável (`step_id`)
- responsabilidade única
- entradas e saídas explícitas
- payload de auditoria obrigatório

Steps **não compartilham estado implícito**.

---

### 2.2 Classificação de Steps

| Kind | Descrição |
|-----|-----------|
| `diagnostic` | Inspeção reversível, sem mutação |
| `transform` | Mutação irreversível do dataset |
| `train` | Ajuste de modelos |
| `evaluate` | Avaliação e comparação |
| `export` | Persistência e empacotamento |

---

## 3. Contrato de um Step

Todo Step deve declarar explicitamente:

```text
step_id: string (slug estável)
kind: diagnostic | transform | train | evaluate | export
depends_on: [step_id]
inputs: [artefatos]
outputs: [artefatos]
payload: auditoria estruturada
```

Nenhum Step pode:
- inferir silenciosamente dados
- acessar filesystem diretamente (exceto `export`)
- depender da ordem física do notebook

---

## 4. Payload Canônico de Auditoria

Todo Step deve produzir um payload com a seguinte estrutura mínima:

```yaml
step_id: audit.schema_types
kind: diagnostic
status: success | skipped | failed
summary: string
metrics:
  key: value
warnings:
  - string
artifacts:
  - name: string
    path: string
```

Payloads são:
- serializáveis
- agregáveis no manifest
- consumíveis por UI e relatórios

---

## 5. Catálogo Canônico de Steps (v1)

### 5.1 Ingestão

#### `ingest.load`
- **Kind**: diagnostic
- **Responsabilidade**: carregar dataset bruto
- **Outputs**: `raw_dataframe`
- **Auditoria**:
  - origem do dado
  - hash/checksum
  - shape inicial

---

### 5.2 Qualidade Estrutural

#### `audit.profile_baseline`
- **Kind**: diagnostic
- **Outputs**: `profile_report`
- **Auditoria**:
  - linhas, colunas
  - missing global
  - cardinalidade

#### `audit.schema_types`
- **Kind**: diagnostic
- **Auditoria**:
  - dtype por coluna
  - divergências vs contrato

#### `audit.duplicates`
- **Kind**: diagnostic
- **Auditoria**:
  - contagem de duplicados
  - chaves afetadas

---

### 5.3 Transformações Estruturais

#### `transform.cast_types_safe`
- **Kind**: transform
- **Responsabilidade**: coerção segura de tipos
- **Auditoria**:
  - valores impactados
  - novos nulos

#### `transform.apply_defaults`
- **Kind**: transform
- **Auditoria**:
  - defaults aplicados
  - colunas afetadas

#### `transform.deduplicate`
- **Kind**: transform
- **Auditoria**:
  - linhas removidas

---

### 5.4 Preparação Supervisionada

#### `split.train_test`
- **Kind**: transform
- **Outputs**: `X_train`, `X_test`, `y_train`, `y_test`
- **Auditoria**:
  - seed
  - proporção

#### `transform.impute_missing`
- **Kind**: transform
- **Auditoria**:
  - estratégia por coluna
  - impacto

#### `transform.categorical_standardize`
- **Kind**: transform
- **Auditoria**:
  - mapeamentos
  - categorias novas

---

### 5.5 Representação

#### `representation.preprocess`
- **Kind**: transform
- **Outputs**: `X_train_rep`, `X_test_rep`
- **Auditoria**:
  - colunas finais
  - encoders/scalers usados

---

### 5.6 Modelagem

#### `train.single`
- **Kind**: train
- **Auditoria**:
  - modelo
  - parâmetros
  - métricas

#### `train.search`
- **Kind**: train
- **Auditoria**:
  - grid/random
  - melhor estimador
  - métricas

---

### 5.7 Avaliação

#### `evaluate.metrics`
- **Kind**: evaluate
- **Auditoria**:
  - métricas padrão
  - matriz de confusão

#### `evaluate.model_selection`
- **Kind**: evaluate
- **Auditoria**:
  - critério de escolha
  - modelo campeão

---

### 5.8 Exportação

#### `export.inference_bundle`
- **Kind**: export
- **Outputs**:
  - pipeline final
  - contrato congelado
- **Auditoria**:
  - paths
  - hashes

---

## 6. Regras de Evolução

- Novos Steps exigem:
  - atualização deste documento
  - nova issue
  - testes dedicados
- Steps não podem ser removidos sem depreciação explícita
- Mudanças semânticas exigem bump de versão

---

## 7. Regra de Ouro

Se um Step:
- não está neste catálogo
- não produz payload
- não aparece no manifest

**ele não existe para o Atlas DataFlow.**
