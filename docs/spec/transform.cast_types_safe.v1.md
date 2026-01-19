# Atlas DataFlow — Step Specification: transform.cast_types_safe v1

## 1. Propósito

Este documento define a **especificação formal e canônica do Step `transform.cast_types_safe` (v1)** no Atlas DataFlow.

Este Step é responsável por aplicar **coerções de tipo seguras**, estritamente guiadas pelo **Internal Contract**, garantindo que qualquer modificação no dataset seja:

- semanticamente autorizada
- tecnicamente segura
- totalmente auditável

Nenhuma coerção pode ocorrer de forma implícita.

---

## 2. Papel do Step no Pipeline

O Step `transform.cast_types_safe`:

- é um **Step do tipo `transform`**
- deve ser executado **após `contract.conformity_report`**
- modifica o dataset de forma controlada
- nunca cria ou remove colunas
- prepara os dados para etapas posteriores (defaults, treino, etc.)

---

## 3. Identidade do Step

```yaml
step_id: transform.cast_types_safe
kind: transform
depends_on:
  - contract.conformity_report
```

---

## 4. Entradas

### 4.1 Dataset

- dataset tabular presente no `RunContext`
- formato esperado: DataFrame (pandas ou equivalente)

---

### 4.2 Contrato

- Internal Contract v1 validado
- disponível em `RunContext.contract`

---

## 5. Regras de Coerção

### 5.1 Coerções Permitidas

Uma coerção só pode ocorrer se:

- o contrato declara explicitamente o `dtype` esperado
- a coerção não altera o significado semântico

Exemplos permitidos:
- `int` → `float`
- `string` numérica → `int` / `float`
- `string` → `category`

---

### 5.2 Coerções Proibidas

São proibidas coerções que:

- alterem significado semântico
- convertam categorias em valores numéricos
- ocultem erro estrutural

Exemplos proibidos:
- `category` → `numeric`
- `string` arbitrária → `numeric` sem validação

---

## 6. Tratamento de Falhas

Quando um valor não puder ser coerido:

- o valor deve se tornar `NaN` / `null`
- a linha deve ser preservada
- o evento deve ser contabilizado na auditoria

Nenhum valor inválido pode ser descartado silenciosamente.

---

## 7. Payload de Auditoria

O Step deve produzir um payload estruturado contendo, no mínimo:

```yaml
impact:
  column_name:
    before_dtype: string
    after_dtype: string
    total_values: int
    coerced_values: int
    null_after_cast: int
```

Regras:
- todos os campos são obrigatórios
- payload deve ser serializável
- payload deve ser registrado no Manifest

---

## 8. Integração com Manifest

O Step deve registrar no Manifest:

- status do Step
- payload de impacto por coluna
- warnings e erros (se houver)
- timestamps e duração

Eventos esperados:
- `step_started`
- `step_finished`

---

## 9. Política de Falha

- Falhas de coerção **não interrompem** o pipeline em v1
- O impacto deve ser comunicado via auditoria
- O Engine pode decidir bloquear o pipeline com base em config futura

---

## 10. Testes Obrigatórios

Implementações devem possuir testes para:

1. coerção válida de dtype
2. valores que se tornam `NaN`
3. preservação de colunas
4. payload de impacto consistente
5. ausência de coerções fora do contrato

---

## 11. Integração com Outros Documentos

Este documento deve ser usado em conjunto com:

- `docs/spec/internal_contract.v1.md`
- `docs/spec/contract.conformity_report.v1.md`
- `docs/contract.md`
- `docs/config.md`
- `docs/engine.md`
- `docs/traceability.md`
- `docs/manifest.schema.v1.md`
- `docs/testing.md`

---

## 12. Regra de Ouro

Se uma coerção:
- não foi autorizada pelo contrato,
- não teve impacto auditado,
- ou alterou o significado do dado,

**ela viola o domínio do Atlas DataFlow.**
