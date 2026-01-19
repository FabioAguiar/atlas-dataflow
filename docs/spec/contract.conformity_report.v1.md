# Atlas DataFlow — Step Specification: contract.conformity_report v1

## 1. Propósito

Este documento define a **especificação formal e canônica do Step `contract.conformity_report` (v1)** no Atlas DataFlow.

O objetivo deste Step é **avaliar a conformidade entre o dataset efetivo e o Internal Contract**, produzindo um **relatório diagnóstico explícito**, sem realizar qualquer mutação nos dados.

Este Step estabelece a base para:
- decisões explícitas
- coerções seguras
- auditoria semântica
- evolução controlada do pipeline

---

## 2. Papel do Step no Pipeline

O Step `contract.conformity_report`:

- é um **Step do tipo `diagnostic`**
- deve ser executado **após `contract.load`**
- consome:
  - dataset efetivo
  - contrato validado no `RunContext`
- **não modifica** o dataset
- **não corrige** divergências

---

## 3. Identidade do Step

```yaml
step_id: contract.conformity_report
kind: diagnostic
depends_on:
  - contract.load
```

---

## 4. Entradas

### 4.1 Dataset

- dataset tabular presente no `RunContext`
- formato esperado: DataFrame (pandas ou equivalente)

---

### 4.2 Contrato

- Internal Contract v1 já validado
- disponível em `RunContext.contract`

---

## 5. Análises Realizadas

### 5.1 Conformidade de Colunas

O Step deve identificar:

- **colunas obrigatórias ausentes**
- **colunas extras**
  - presentes no dataset, mas não declaradas no contrato

---

### 5.2 Conformidade de Tipos

Para cada coluna declarada:

- comparar dtype real × dtype esperado
- identificar divergências
- não tentar coerção

---

### 5.3 Conformidade Categórica

Para colunas categóricas:

- identificar categorias fora do domínio declarado
- reportar categorias novas ou inválidas

---

## 6. Payload de Saída

O Step deve produzir um payload estruturado contendo, no mínimo:

```yaml
summary:
  total_issues: int
  blocking_issues: int

missing_columns: []
extra_columns: []

dtype_issues:
  - column: string
    expected: string
    observed: string

category_issues:
  - column: string
    invalid_values: []

decisions_required:
  - code: string
    severity: info | warning | error
    description: string
    affected_columns: []
    suggested_actions: []
```

Regras:
- `severity = error` indica potencial bloqueio do pipeline
- nenhuma decisão é tomada automaticamente

---

## 7. Integração com Manifest

O Step deve registrar no Manifest:

- status do Step
- payload de conformidade
- warnings e erros (se houver)
- timestamps e duração

Eventos esperados:
- `step_started`
- `step_finished`

---

## 8. Política de Falha

- O Step **não falha o pipeline automaticamente**
- Divergências são reportadas como dados
- Bloqueio do pipeline é decisão do Engine/config em versões futuras

---

## 9. Testes Obrigatórios

Implementações devem possuir testes para:

1. coluna obrigatória ausente
2. coluna extra
3. dtype divergente
4. categoria fora do domínio
5. payload `decisions_required` consistente

---

## 10. Integração com Outros Documentos

Este documento deve ser usado em conjunto com:

- `docs/spec/internal_contract.v1.md`
- `docs/spec/contract.load.v1.md`
- `docs/contract.md`
- `docs/config.md`
- `docs/engine.md`
- `docs/traceability.md`
- `docs/manifest.schema.v1.md`
- `docs/testing.md`

---

## 11. Regra de Ouro

Se divergências semânticas:
- não forem detectadas,
- não forem explicitadas,
- ou forem corrigidas silenciosamente,

**o pipeline viola o domínio do Atlas DataFlow.**
