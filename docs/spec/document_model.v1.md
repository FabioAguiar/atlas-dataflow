
# Document Model Specification — v1

## Status

- **Versão:** v1
- **Estado:** Proposta
- **Categoria:** Reporting / Presentation
- **Milestone associada:** M# — Apresentação & Artefatos
- **Não bloqueia:** M7 — Reporting (MD/PDF)

---

## Motivação

No Atlas DataFlow, o **Manifest** é a fonte de verdade absoluta da execução.
O `report.md` (M7-01) foi definido como o artefato humano-canônico,
e o `report.pdf` (M7-02) como sua materialização portátil.

Entretanto, certos cenários exigem uma camada intermediária **mais estruturada**
do que Markdown, capaz de representar documentos complexos sem introduzir
semântica nova ou inferências.

O **Document Model** surge como essa camada intermediária explícita.

---

## Objetivo

Definir um **modelo documental canônico**, determinístico e serializável,
derivado exclusivamente do Manifest, capaz de:

- representar documentos humanos estruturados
- servir como base para múltiplos formatos finais (PDF, HTML, DOCX, etc.)
- separar conteúdo estruturado de renderização

---

## Princípios Fundamentais

O Document Model **DEVE**:

- ser derivado exclusivamente do Manifest
- ser determinístico (mesmo Manifest → mesmo modelo)
- ser serializável (JSON-safe)
- não inferir, recalcular ou reinterpretar dados
- não depender de layout, estilo ou engine

O Document Model **NÃO DEVE**:

- substituir o Manifest
- substituir o `report.md`
- conter lógica de apresentação visual
- conter decisões de negócio

---

## Posição na Arquitetura

Fluxo canônico:

```
Manifest
   ↓
Document Model
   ↓
Engine de Renderização
   ↓
Artefato Final (PDF / HTML / DOCX)
```

O Document Model **não executa renderização**.
Ele apenas descreve **o que deve existir no documento**, não como deve parecer.

---

## Estrutura Geral do Modelo

### Document

Representa um documento completo.

```python
Document(
    id="execution-report",
    title="Execution Report",
    sections=[...],
    metadata={...}
)
```

Campos:

| Campo | Tipo | Obrigatório | Descrição |
|------|-----|-------------|-----------|
| `id` | str | sim | Identificador estável do documento |
| `title` | str | sim | Título principal |
| `sections` | list[Section] | sim | Seções do documento |
| `metadata` | dict | não | Metadados auxiliares (ex.: run_id) |

---

### Section

Representa uma seção lógica do documento.

```python
Section(
    id="metrics",
    title="Metrics",
    blocks=[...]
)
```

Campos:

| Campo | Tipo | Obrigatório | Descrição |
|------|-----|-------------|-----------|
| `id` | str | sim | Identificador estável |
| `title` | str | sim | Título da seção |
| `blocks` | list[Block] | sim | Conteúdo da seção |

---

### Block (conceito base)

Blocos são unidades mínimas de conteúdo.
Cada bloco possui um tipo explícito.

Tipos esperados (v1):

- `paragraph`
- `list`
- `table`
- `code`
- `key_value`

Exemplo base:

```python
Block(
    type="paragraph",
    content=...
)
```

---

### ParagraphBlock

```python
Block(
    type="paragraph",
    content="Texto livre, sem markup"
)
```

---

### ListBlock

```python
Block(
    type="list",
    content=[
        "item 1",
        "item 2"
    ]
)
```

---

### TableBlock

```python
Block(
    type="table",
    content={
        "headers": ["metric", "value"],
        "rows": [
            ["accuracy", 0.91],
            ["recall", 0.87]
        ]
    }
)
```

---

### KeyValueBlock

```python
Block(
    type="key_value",
    content={
        "engine": "simple",
        "bytes": 12034
    }
)
```

---

## Derivação a partir do Manifest

A construção do Document Model:

- **consome exclusivamente** o Manifest final
- utiliza apenas campos explícitos:
  - steps
  - payloads
  - artifacts
  - metadata de execução
- falha explicitamente se dados obrigatórios estiverem ausentes

Nenhum acesso a datasets, modelos ou artefatos fora do Manifest é permitido.

---

## Versionamento

- O Document Model é versionado independentemente
- Alterações estruturais exigem:
  - bump de versão (`v2`, `v3`, ...)
  - compatibilidade explícita entre versões
- Engines devem declarar quais versões suportam

---

## Testabilidade

O Document Model deve permitir:

- snapshot tests estruturais
- comparação JSON determinística
- validação por schema (futuro)

---

## Fora de Escopo (v1)

- estilos visuais
- paginação
- templates
- internacionalização
- interatividade

---

## Considerações Finais

O Document Model não substitui o `report.md`.
Ele introduz uma **segunda via de materialização**, voltada à apresentação formal,
sem comprometer os invariantes fundamentais do Atlas DataFlow.

Ele existe para **expandir possibilidades**, não para antecipar necessidades.
