# Spec — report.md v1

## Visão Geral

O `report.md` é um **relatório automatizado**, determinístico e auditável, gerado a partir das
**fontes de verdade do Atlas DataFlow**.

Seu objetivo é consolidar, em um único artefato legível por humanos:

- o que foi executado
- quais decisões foram tomadas
- quais evidências sustentam essas decisões
- quais artefatos foram produzidos

O `report.md` **não interpreta**, **não recalcula** e **não infere** informações.
Ele apenas **organiza e apresenta fatos registrados** no Manifest.

---

## Escopo (v1)

Incluído:

- Relatório em **Markdown**
- Consolidação guiada por `manifest`
- Uso de métricas, payloads e artifacts já registrados
- Estrutura mínima padronizada

Excluído (fora de escopo):

- Geração de PDF
- Visualizações gráficas
- Análises interpretativas ou narrativas livres
- Inferência de informações ausentes
- Customização visual

---

## Fonte de Verdade

O `report.md` deve ser gerado **exclusivamente** a partir de:

- `manifest` final
- `metrics` registradas nos Steps
- `artifacts` e `payloads` dos Steps
- `meta` de execução

Nenhuma informação pode ser obtida fora dessas fontes.

---

## Estrutura Canônica

O arquivo **DEVE** seguir a estrutura abaixo, nesta ordem:

```md
# Execution Report

## Executive Summary
## Pipeline Overview
## Decisions & Outcomes
## Metrics
## Generated Artifacts
## Traceability
## Limitations
## Execution Metadata
```

A ausência de qualquer seção invalida o report v1.

---

## Conteúdo por Seção

### Executive Summary

Resumo de alto nível do run:

- objetivo do pipeline (se disponível no Manifest)
- decisão principal (ex.: modelo campeão)
- principais métricas

Conteúdo deve ser **sintético** e **fact-based**.

---

### Pipeline Overview

Descrição sequencial dos Steps executados:

- ordem de execução
- status final de cada Step
- tempo de execução (quando disponível)

---

### Decisions & Outcomes

Registro explícito das decisões tomadas:

- modelo selecionado
- parâmetros escolhidos (se registrados)
- critérios de seleção (ex.: métrica usada)

---

### Metrics

Listagem das métricas finais:

- nome da métrica
- valor
- Step de origem

---

### Generated Artifacts

Lista dos artefatos produzidos:

- nome
- path relativo
- hash (quando disponível)
- Step de origem

---

### Traceability

Referências cruzadas:

- run_id
- relação Step → artifacts
- relação Step → decisões

---

### Limitations

Lista explícita de limitações conhecidas do report v1:

- ausência de visualizações
- ausência de interpretação humana
- dependência exclusiva do Manifest

Conteúdo **fixo e padronizado**.

---

### Execution Metadata

Metadados técnicos do run:

- run_id
- timestamps relevantes
- versão do Atlas (se disponível)
- ambiente (se registrado)

---

## Determinismo

Para um Manifest fixo:

- o conteúdo do `report.md` **DEVE ser idêntico**
- a ordem das seções **DEVE ser estável**
- listas **DEVEM ser ordenadas** quando aplicável

---

## Erros e Falhas

O gerador do `report.md` **DEVE falhar explicitamente** quando:

- `manifest` estiver ausente
- estrutura mínima do Manifest estiver corrompida
- seções obrigatórias não puderem ser preenchidas

Falhas devem ser claras e não silenciosas.

---

## Versionamento

- Esta especificação define o **report.md v1**
- Mudanças estruturais exigem nova versão (`v2`, etc.)
- Versão deve ser registrada no próprio report

---

## Referências

- `docs/spec/model_card.v1.md`
- `docs/spec/export.inference_bundle.v1.md`
- `docs/spec/evaluate.metrics.v1.md`
- `docs/traceability.md`
- `docs/manifest.schema.v1.md`
- `docs/pipeline_elements.md`
- `docs/engine.md`