# Spec — report.pdf v1

## Visão Geral

O `report.pdf` é um **artefato de apresentação** gerado a partir do `report.md`,
com o objetivo de fornecer uma versão **portátil, distribuível e arquivável**
do relatório de execução do Atlas DataFlow.

O `report.pdf` **não adiciona semântica**, **não interpreta conteúdo** e
**não altera decisões**. Ele é uma **representação visual** fiel do
`report.md`, mantendo a rastreabilidade com o Manifest.

---

## Escopo (v1)

Incluído:

- Conversão de `report.md` para `report.pdf`
- Preservação da estrutura e hierarquia do Markdown
- Registro do PDF como artefato no Manifest
- Execução determinística para um `report.md` fixo

Excluído (fora de escopo):

- Customização visual avançada
- Templates ricos ou branding
- Visualizações interativas
- Assinatura digital
- Publicação externa

---

## Fonte de Verdade

O `report.pdf` deve ser gerado **exclusivamente** a partir de:

- `report.md` (artefato gerado no M7-01)
- configurações explícitas da engine de conversão
- metadata de execução registrada

Nenhuma informação adicional pode ser inferida ou recalculada.

---

## Engine de Conversão

A conversão **DEVE** ser realizada por uma engine **pluggable e configurável**.

### Regras

- Nenhuma engine pode ser assumida como padrão implícito
- A engine utilizada deve ser declarada em configuração
- A engine **não pertence ao core semântico** do Atlas

### Exemplos de Engines Aceitáveis

- `pandoc`
- `weasyprint`
- `wkhtmltopdf`
- outras engines CLI ou library-based, desde que configuradas explicitamente

---

## Estrutura Esperada

### Entrada

- `artifacts/report.md`

### Saída

- `artifacts/report.pdf`

O conteúdo do PDF deve refletir fielmente o conteúdo do Markdown de origem.

---

## Rastreabilidade via Manifest

O Step de exportação para PDF **DEVE registrar** no Manifest, no mínimo:

- path do arquivo `report.pdf`
- tamanho do arquivo (bytes)
- engine utilizada
- versão da spec (`report.pdf.v1`)
- Step de origem (`export.report_md`)

---

## Determinismo

Para um `report.md` fixo e uma configuração fixa:

- o `report.pdf` gerado **DEVE ser idêntico**
- o tamanho do arquivo **DEVE ser estável** (salvo metadata técnica irrelevante)
- nenhuma variação visual não determinística é permitida

---

## Erros e Falhas

O Step **DEVE falhar explicitamente** quando:

- `report.md` estiver ausente
- engine de conversão não estiver configurada
- a engine falhar durante a conversão
- o arquivo PDF não puder ser gerado

Falhas não podem ser silenciosas.

---

## Versionamento

- Esta especificação define o **report.pdf v1**
- Mudanças estruturais exigem nova versão (`v2`, etc.)
- A versão deve ser registrada no Manifest

---

## Referências

- `docs/spec/report.md.v1.md`
- `docs/spec/model_card.v1.md`
- `docs/spec/export.inference_bundle.v1.md`
- `docs/traceability.md`
- `docs/manifest.schema.v1.md`
- `docs/pipeline_elements.md`
- `docs/engine.md`