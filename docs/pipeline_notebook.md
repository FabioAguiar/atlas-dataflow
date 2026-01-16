# Atlas DataFlow — Pipeline Notebook Canonical Narrative

## 1. Propósito do Documento

Este documento define a **narrativa operacional canônica** do **notebook template** do Atlas DataFlow.

Ele descreve **como o pipeline deve ser orquestrado, apresentado e interpretado**, sem introduzir regras de negócio ou decisões semânticas que pertençam ao core.

Este documento deve ser tratado como **referência obrigatória** para:
- construção do notebook template
- organização das células e seções narrativas
- integração com UI leve (renderização)
- alinhamento entre core, contratos e APIs

---

## 2. Papel do Notebook no Atlas DataFlow

O notebook **não é o pipeline**.

O notebook é:
- um **orquestrador narrativo**
- um **ambiente de inspeção e interpretação**
- um **adapter humano** para o core

O notebook **não pode**:
- conter regras de domínio
- tomar decisões semânticas
- alterar contratos
- executar lógica condicional complexa

Toda lógica deve residir no **core do Atlas DataFlow**.

---

## 3. Princípios da Narrativa Operacional

1. **Narrativa antes de implementação**
   - Cada fase do notebook explica *o que* será feito e *por quê*.

2. **Execução declarativa**
   - O notebook declara **quais steps executar**, não *como* executá-los.

3. **Separação entre cálculo e visualização**
   - Cálculo ocorre no core.
   - Notebook apenas renderiza payloads.

4. **Falhas são informativas**
   - Erros e “decisions required” devem ser exibidos, não ocultados.

---

## 4. Estrutura Canônica do Notebook Template

O notebook deve ser organizado em **fases narrativas**, que **não representam ordem técnica rígida**, mas sim **marcos de leitura**.

### Fase 0 — Contexto e Configuração

Conteúdo esperado:
- descrição do problema analítico
- carregamento de config (`defaults + local`)
- carregamento do contrato interno
- apresentação do escopo atual

Nenhum dado é processado aqui.

---

### Fase 1 — Ingestão

Objetivo:
- carregar dataset bruto
- registrar origem e metadados

Execução típica:
- `ingest.load`

Saída esperada:
- payload de ingestão
- preview controlado do dataset

---

### Fase 2 — Qualidade Estrutural

Objetivo:
- compreender estrutura e riscos do dataset

Execução típica:
- `audit.profile_baseline`
- `audit.schema_types`
- `audit.duplicates`

Saída esperada:
- diagnósticos claros
- possíveis “decisions required”

Nenhuma transformação ocorre nesta fase.

---

### Fase 3 — Conformidade ao Contrato

Objetivo:
- alinhar dataset ao contrato interno

Execução típica:
- `contract.conformity_report`
- `transform.cast_types_safe`
- `transform.apply_defaults`

Saída esperada:
- dataset conforme contrato
- auditoria explícita de impactos

---

### Fase 4 — Preparação Supervisionada

Objetivo:
- preparar dados para aprendizado estatístico

Execução típica:
- `split.train_test`
- `transform.impute_missing`
- `transform.categorical_standardize`

Saída esperada:
- conjuntos de treino/teste coerentes
- payloads de impacto

---

### Fase 5 — Representação

Objetivo:
- transformar dados em espaço vetorial

Execução típica:
- `representation.preprocess`

Saída esperada:
- matrizes finais
- descrição do preprocess

---

### Fase 6 — Modelagem

Objetivo:
- treinar e comparar modelos

Execução típica:
- `train.single` ou `train.search`
- `evaluate.metrics`
- `evaluate.model_selection`

Saída esperada:
- métricas claras
- modelo campeão explícito

---

### Fase 7 — Exportação de Artefatos

Objetivo:
- tornar resultados reutilizáveis

Execução típica:
- `export.inference_bundle`

Saída esperada:
- artefatos persistidos
- manifest final completo

---

### Fase 8 — Relatório Final

Objetivo:
- consolidar entendimento humano

Execução típica:
- geração de `report.md`
- opcional: export PDF

Saída esperada:
- relatório legível e auditável

---

## 5. Interação Humana e Decisões

O notebook deve:
- destacar decisões exigidas
- permitir intervenção explícita (config/contrato)
- nunca aplicar decisões automaticamente

Decisões devem resultar em:
- alteração de config ou contrato
- reexecução explícita do pipeline

---

## 6. Integração com APIs e Use Cases

O notebook deve espelhar a forma como:
- APIs futuras invocarão o core
- pipelines automatizados executarão steps

Ou seja:
- o notebook é um **ensaio controlado**
- APIs são **execução automatizada do mesmo core**

---

## 7. Regras de Evolução

- Novas fases exigem:
  - justificativa narrativa
  - atualização deste documento
- Fases não substituem steps
- Steps continuam sendo definidos apenas em `pipeline_elements.md`

---

## 8. Regra de Ouro

Se o notebook:
- executa lógica fora do core
- toma decisões implícitas
- mascara erros ou auditorias

**ele viola o Atlas DataFlow.**
