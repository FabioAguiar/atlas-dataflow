# Atlas DataFlow — Step Specification: contract.conformity_report v1

## 1. Propósito

Este documento define a **especificação formal e canônica do Step `contract.conformity_report` (v1)**
no Atlas DataFlow.

O objetivo deste Step é **avaliar a conformidade entre o dataset efetivo e o Internal Contract**,
produzindo um **relatório diagnóstico explícito**, estruturado e auditável, **sem realizar qualquer
mutação nos dados**.

Este Step estabelece a base para:

- decisões explícitas (*decision required*)
- coerções seguras (em Steps posteriores)
- auditoria semântica
- erros acionáveis e padronizados
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
- **não falha automaticamente o pipeline**

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
- **não tentar coerção**
- **não inferir conversões**

---

### 5.3 Conformidade Categórica

Para colunas categóricas:

- identificar categorias fora do domínio declarado
- reportar categorias novas ou inválidas
- preservar valores observados para rastreabilidade

---

## 6. Payload de Saída (Diagnóstico)

O Step deve produzir um payload **estruturado, serializável e determinístico**
contendo, no mínimo:

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
    decision_required: true
```

### Regras

- `severity = error` indica **potencial bloqueio do pipeline**
- todo item em `decisions_required` **DEVE ter `decision_required = true`**
- nenhuma decisão é tomada automaticamente
- nenhuma correção é aplicada neste Step

---

## 7. Integração com Schema de Erros

Quando aplicável, o payload de conformidade **DEVE ser compatível**
com o schema definido em:

- `docs/spec/errors.schema.v1.md`

Este Step **não levanta exceções**, mas fornece dados suficientes para que
o Engine ou Steps posteriores possam:

- falhar explicitamente
- solicitar decisão humana
- registrar erros acionáveis no Manifest

---

## 8. Integração com Manifest

O Step deve registrar no Manifest:

- status do Step
- payload completo de conformidade
- warnings e erros diagnósticos
- timestamps e duração

Eventos esperados:

- `step_started`
- `step_finished`

---

## 9. Política de Falha

- O Step **não falha o pipeline automaticamente**
- Divergências são reportadas como **dados diagnósticos**
- Bloqueio do pipeline é responsabilidade do Engine/config
- Qualquer correção automática **viola o domínio do Atlas**

---

## 10. Testes Obrigatórios

Implementações devem possuir testes cobrindo, no mínimo:

1. coluna obrigatória ausente
2. coluna extra
3. dtype divergente
4. categoria fora do domínio
5. payload `decisions_required` consistente e determinístico
6. compatibilidade com `errors.schema.v1`

---

## 11. Integração com Outros Documentos

Este documento deve ser usado em conjunto com:

- `docs/spec/internal_contract.v1.md`
- `docs/spec/contract.load.v1.md`
- `docs/spec/errors.schema.v1.md`
- `docs/engine.md`
- `docs/traceability.md`
- `docs/manifest.schema.v1.md`
- `docs/testing.md`

---

## 12. Regra de Ouro

Se divergências semânticas:

- não forem detectadas,
- não forem explicitadas,
- não forem marcadas como *decision required*,
- ou forem corrigidas silenciosamente,

**o pipeline viola o domínio do Atlas DataFlow.**