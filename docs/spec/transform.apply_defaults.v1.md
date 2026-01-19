# Atlas DataFlow — Step Specification: transform.apply_defaults v1

## 1. Propósito

Este documento define a **especificação formal e canônica do Step `transform.apply_defaults` (v1)** no Atlas DataFlow.

O objetivo deste Step é **materializar defaults explicitamente declarados no contrato**, de forma controlada, auditável e semanticamente segura.

Defaults não são inferidos, não são heurísticos e nunca sobrescrevem dados válidos.

---

## 2. Papel do Step no Pipeline

O Step `transform.apply_defaults`:

- é um **Step do tipo `transform`**
- deve ser executado **após `transform.cast_types_safe`**
- modifica o dataset de forma limitada e explícita
- encerra o ciclo mínimo de normalização contratual

---

## 3. Identidade do Step

```yaml
step_id: transform.apply_defaults
kind: transform
depends_on:
  - transform.cast_types_safe
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

O contrato deve declarar explicitamente:
- `default`
- `required`

---

## 5. Regras de Aplicação de Defaults

### 5.1 Defaults em colunas existentes

Para colunas existentes no dataset:

- aplicar default **apenas** quando:
  - valor é `null` / `NaN`
- valores não nulos **nunca** devem ser sobrescritos

---

### 5.2 Criação de colunas ausentes permitidas

Se o contrato declarar:

```yaml
required: false
default: <valor>
```

E a coluna não existir:

- a coluna deve ser criada
- todos os valores devem receber o default
- a criação deve ser auditada

---

### 5.3 Restrições

O Step **não pode**:

- criar colunas não declaradas no contrato
- inferir defaults
- aplicar defaults condicionais
- modificar tipos de dados (isso é responsabilidade de `cast_types_safe`)

---

## 6. Payload de Auditoria

O Step deve produzir um payload estruturado contendo, no mínimo:

```yaml
impact:
  column_name:
    default_value: any
    values_filled: int
    column_created: bool
```

Regras:
- todos os campos são obrigatórios
- payload deve ser serializável
- payload deve ser registrado no Manifest

---

## 7. Integração com Manifest

O Step deve registrar no Manifest:

- status do Step
- payload de impacto por coluna
- warnings e erros (se houver)
- timestamps e duração

Eventos esperados:
- `step_started`
- `step_finished`

---

## 8. Política de Falha

- Ausência de default para coluna `required = true` **não é tratada aqui**
  - isso deve ter sido diagnosticado em `contract.conformity_report`
- Falhas inesperadas interrompem o Step e devem ser rastreáveis

---

## 9. Testes Obrigatórios

Implementações devem possuir testes para:

1. default aplicado apenas em valores nulos
2. valor válido não sobrescrito
3. coluna ausente permitida criada
4. payload de auditoria consistente
5. nenhuma aplicação fora do contrato

---

## 10. Integração com Outros Documentos

Este documento deve ser usado em conjunto com:

- `docs/spec/internal_contract.v1.md`
- `docs/spec/transform.cast_types_safe.v1.md`
- `docs/spec/contract.conformity_report.v1.md`
- `docs/contract.md`
- `docs/config.md`
- `docs/engine.md`
- `docs/traceability.md`
- `docs/manifest.schema.v1.md`
- `docs/testing.md`

---

## 11. Regra de Ouro

Se um default:
- não estiver declarado no contrato,
- sobrescrever um valor válido,
- ou não for auditado,

**o pipeline viola o domínio do Atlas DataFlow.**
