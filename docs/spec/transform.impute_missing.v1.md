# 📄 transform.impute_missing — Imputação Guiada por Contrato (v1)

## Visão Geral

O Step **`transform.impute_missing`** aplica **imputação explícita de valores ausentes**, baseada **exclusivamente nas regras declaradas no contrato interno**, no contexto do **Milestone M3 — Preparação Supervisionada** do Atlas DataFlow.

No Atlas, **imputação nunca é automática**: toda substituição de valores ausentes representa uma **decisão semântica**, que deve ser:
- declarada
- rastreável
- auditável

---

## Objetivo

- Eliminar valores ausentes **somente onde explicitamente autorizado**
- Suportar imputação **numérica e categórica**
- Garantir que **colunas mandatórias** não contenham `NaN`
- Registrar auditoria detalhada de impacto

---

## Natureza do Step

- **ID:** `transform.impute_missing`
- **Kind:** `TRANSFORM`
- **Categoria:** Preparação Supervisionada
- **Milestone:** M3 — Preparação Supervisionada
- **Caráter:** Mutação controlada e auditável

---

## Dependências Semânticas

Este Step pressupõe:

- contrato interno carregado (`contract.load`)
- tipagem coerida (`transform.cast_types_safe`)
- normalização categórica aplicada, se configurada (`transform.categorical_standardize`)

---

## Fonte de Dados

O Step consome:

```
data.raw_rows
```

E atualiza o mesmo artifact **somente após auditoria registrada**.

---

## Regras Contratuais Esperadas

Exemplo de configuração no contrato:

```yaml
contract:
  imputation:
    age:
      strategy: median
      mandatory: true
    income:
      strategy: mean
      mandatory: false
    country:
      strategy: most_frequent
      mandatory: false
```

### Estratégias suportadas (v1)

#### Numéricas
- `mean`
- `median`
- `constant` (valor explícito)

#### Categóricas
- `most_frequent`
- `constant` (valor explícito)

Nenhuma estratégia é inferida automaticamente.

---

## Estratégia de Execução

Para cada coluna configurada:

1. Verificar existência da coluna no dataset
2. Verificar presença de valores ausentes
3. Aplicar estratégia declarada
4. Verificar colunas mandatórias
5. Registrar auditoria de impacto
6. Atualizar o dataset

---

## Auditoria de Impacto (Payload v1)

```yaml
payload:
  impact:
    columns_affected: [string]
    strategy_by_column:
      column: strategy
    values_imputed:
      column: int
```

### Invariantes

- Payload sempre serializável
- Auditoria gerada mesmo quando nenhum valor é imputado
- Falha explícita se coluna mandatória permanecer com `NaN`

---

## Falhas Explícitas

O Step retorna **`FAILED`** quando:

- regra de imputação está ausente ou malformada
- coluna configurada não existe
- estratégia inválida
- imputação não elimina `NaN` em coluna mandatória

---

## Ordem Canônica de Execução

1. Ler contrato
2. Validar regras de imputação
3. Ler dataset
4. Aplicar imputações declaradas
5. Verificar colunas mandatórias
6. Registrar auditoria
7. Atualizar dataset
8. Emitir `StepResult`

---

## Testes Esperados

Os testes unitários devem cobrir:

- Imputação numérica por média/mediana
- Imputação categórica por moda
- Estratégia constante
- Falha em coluna mandatória
- Dataset não alterado quando não configurado

---

## Fora de Escopo (v1)

- Imputação por modelos preditivos
- Interpolação temporal
- Forward/backward fill implícito
- Inferência automática de estratégia

---

## Evolução Futura

Possíveis extensões:

- Estratégias condicionais
- Imputação dependente de grupo
- Integração com métricas de missingness
- Feedback para enriquecimento do contrato

---

## Referências

- `docs/spec/contract.internal.v1.md`
- `docs/pipeline_elements.md`
- `docs/engine.md`
- `docs/traceability.md`
- `docs/manifest.schema.v1.md`
- `docs/testing.md`
