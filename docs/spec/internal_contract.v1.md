# Atlas DataFlow — Internal Contract v1 (Canonical Specification)

## 1. Propósito do Documento

Este documento define a **especificação formal e canônica do Internal Contract v1** do Atlas DataFlow.

O Internal Contract é a **fonte de verdade semântica** do pipeline, descrevendo:
- o significado dos dados
- as expectativas estruturais
- as restrições semânticas permitidas

Ele é utilizado por Steps de:
- carregamento (`contract.load`)
- diagnóstico (`contract.conformity_report`)
- transformação segura (`transform.*`)
- inferência futura

Este documento é **normativo**: qualquer contrato que não o siga é considerado inválido.

---

## 2. Princípios Fundamentais

1. **Separação clara**
   - Contrato define *o que é válido*
   - Config define *como executar*

2. **Nada implícito**
   - Nenhuma regra pode ser inferida silenciosamente

3. **Versionamento explícito**
   - Quebras exigem bump de versão

4. **Auditável**
   - Toda decisão deve ser rastreável

---

## 3. Estrutura Raiz do Internal Contract

```yaml
contract_version: "1.0"

problem:
  name: string
  type: classification | regression | clustering | other

target:
  name: string
  dtype: int | float | category | bool
  allowed_null: false

features:
  - name: string
    role: numerical | categorical | boolean | text | other
    dtype: int | float | category | bool | string
    required: true | false
    allowed_null: true | false

defaults:
  column_name: value

categories:
  column_name:
    allowed: [value1, value2]
    normalization:
      type: map | lower | upper | none
      mapping: {}

imputation:
  column_name:
    allowed: true | false
```

---

## 4. Versionamento

### 4.1 Campo obrigatório

- `contract_version` é obrigatório
- formato: `"MAJOR.MINOR"`

### 4.2 Regras

- Alterações estruturais → bump de MAJOR
- Extensões compatíveis → bump de MINOR

---

## 5. Target

Regras:
- `target.name` deve existir no dataset
- `allowed_null` deve ser `false` em v1
- dtype deve ser explícito

---

## 6. Features

Para cada feature:

- `name` obrigatório
- `dtype` obrigatório
- `required` define se ausência é erro
- `allowed_null` define se null é permitido

Ausência de feature:
- `required = true` → erro
- `required = false` → permitido

---

## 7. Defaults

- Defaults são valores semânticos
- Só podem ser aplicados se:
  - coluna permitir ausência
  - coluna permitir null

Defaults **nunca**:
- sobrescrevem dado válido
- criam colunas não declaradas

---

## 8. Categorias e Normalização

- Categorias devem ser explicitamente declaradas
- Normalização é semântica (ex.: lowercase)
- Categorias fora do domínio devem ser reportadas

---

## 9. Regras de Imputação

O contrato apenas declara:
- se imputação é permitida por coluna

Estratégia de imputação:
- pertence à config
- não ao contrato

---

## 10. Validações Obrigatórias

Um Internal Contract v1 válido deve:

- conter `contract_version`
- definir `problem`, `target` e `features`
- não possuir features duplicadas
- não permitir defaults em colunas não declaradas

---

## 11. Integração com Outros Documentos

Este documento deve ser usado em conjunto com:

- `docs/contract.md`
- `docs/config.md`
- `docs/pipeline_elements.md`
- `docs/engine.md`
- `docs/traceability.md`
- `docs/testing.md`

---

## 12. Regra de Ouro

Se um dado:
- não está declarado no contrato,
- não pode ser validado,
- não pode ser auditado,

**ele não é confiável no Atlas DataFlow.**
