# M7-04 — [Runtime/Templates] Repositório de Templates Estáticos (v1)

**Milestone:** M7 — OCR Controlado (Templates estáticos)  
**Labels:** runtime, ocr, assets

---

## Contexto

No Milestone M7, o OCR do FGMU Remaster passa a operar de forma **controlada** e **determinística**,
baseado exclusivamente em:

- regiões explícitas (M7-03)
- templates estáticos versionados
- confirmação humana posterior (review)

Para garantir rastreabilidade, previsibilidade e auditabilidade, é necessário
introduzir um repositório canônico de templates, desacoplado de:

- heurísticas implícitas
- geração automática
- aprendizado incremental (reservado ao M8)

Esta issue formaliza o **Template Repository v1**, que será a única fonte
permitida de templates utilizados pelo OCR Engine nesta milestone.

---

## Objetivo

Criar um repositório explícito, versionado e imutável de templates estáticos,
consumível pelo Runtime OCR Engine de forma determinística.

---

## Escopo

### 1) Estrutura canônica do repositório de templates

Introduzir no repositório uma árvore padronizada:

```text
templates/
  sf6/
    characters/
      ryu/
        ryu_v1.png
        ryu_v2.png
      ken/
        ken_v1.png
    ui/
      versus_bar.png
```

**Regras estruturais:**

- Templates organizados por `game_id`
- Subpastas semânticas explícitas (ex.: `characters`, `ui`)
- Cada entidade (ex.: personagem) possui seu próprio namespace

### 2) Regras obrigatórias de templates

Templates devem ser:

- versionados explicitamente (`_v1`, `_v2`, etc.)
- imutáveis após commit
- referenciáveis por ID estável

Exemplo de `template_id`:

- `sf6.character.ryu.v1`

Nenhum template pode ser:

- sobrescrito
- atualizado “in-place”
- criado automaticamente pelo Runtime nesta milestone

### 3) Template Repository Loader (v1)

Implementar um loader determinístico que:

- varre a árvore `templates/`
- valida nomes e versões
- constrói um índice interno contendo:
  - `template_id`
  - `path`
  - `hash` (sha256)
  - dimensões
  - `game_id`
  - categoria (`character` / `ui` / etc.)

**Falhas devem gerar erros explícitos de inicialização**, não falhas silenciosas em runtime.

### 4) Integração com OCR Engine

O OCR Engine deve:

- consumir templates apenas via `template_id`
- nunca acessar o filesystem diretamente
- registrar no `OCRResult` qual `template_id` foi aplicado

### 5) Documentação canônica

Documentar:

- convenções de naming
- regras de versionamento
- exemplos válidos e inválidos
- política de imutabilidade
- relação com OCR Regions (M7-03)

---

## Critérios de Aceite

- [ ] Estrutura `templates/` criada e versionada
- [ ] Loader determinístico implementado e testado
- [ ] Templates acessíveis por `template_id` (sem ambiguidade)
- [ ] OCR Engine consegue referenciar templates via repositório (sem leitura direta de FS)
- [ ] Nenhuma criação automática de templates em M7
- [ ] Documentação criada e referenciada

---

## Diretrizes Técnicas

- Templates são **assets versionados**, não modelos treináveis
- Zero heurística implícita
- Falha explícita > fallback silencioso
- Compatível com Docker / Windows / Linux
- Preparado para evolução no M8 (aprendizado incremental)

---

## Fora de Escopo (v1)

- Geração automática de templates
- Substituição ou “melhoria” de templates existentes
- Aprendizado humano-no-loop
- Templates para outros jogos além de SF6

---

## Referências

- 📄 docs/spec/runtime.ocr.controlled.v1.md
- 📄 docs/spec/game.profile.v1.md
- 📄 docs/spec/ocr.result.v1.md
- 📄 docs/spec/runtime.incremental.learning.v1.md (a criar — M8)
- 📄 docs/adr/0015-runtime-enrichment-pipeline.md

---

## Observação Final

Esta issue estabelece o chão sólido do OCR controlado:

**templates são fatos congelados, não suposições aprendidas**

Ela prepara o sistema para que, no M8, o aprendizado incremental
possa ocorrer com segurança, rastreabilidade e reversibilidade,
sem jamais corromper o passado.
