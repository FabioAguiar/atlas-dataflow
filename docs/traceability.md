# Atlas DataFlow — Traceability Canonical Rules

## 1. Propósito do Documento

Este documento define as **regras canônicas de rastreabilidade** do Atlas DataFlow.  
Ele estabelece como **manifest**, **artefatos**, **auditorias** e **relatórios**
devem ser produzidos, persistidos e consumidos **ao longo de uma execução completa (full run)**.

Este documento é **fonte de verdade** para:
- implementação do manifest e event log
- persistência de artefatos (modelos, preprocess, relatórios)
- critérios de auditoria por step
- integração com APIs e adapters
- definição de testes de qualidade, reprodutibilidade e **E2E**

---

## 2. Conceitos-Chave

### 2.1 Manifest

O **manifest** é o registro forense de uma execução completa do pipeline (**full run**).

Ele contém:
- identidade do run
- snapshot de config e contrato
- lista ordenada de steps executados
- builders obrigatórios executados
- decisões registradas
- warnings e erros
- artefatos gerados

O manifest deve permitir:
- reproduzir a execução
- explicar resultados
- depurar falhas
- auditar decisões de ponta a ponta

---

### 2.2 Auditoria

Auditoria é a evidência estruturada produzida por cada etapa do pipeline.

Ela pode ser gerada por:
- **Steps canônicos**
- **Builders obrigatórios** (quando não existe Step)

Toda auditoria deve:
- ser serializável
- ser agregável no manifest
- ser consumível por UI e relatórios
- incluir impacto quando houver transformação

---

### 2.3 Artefatos

Artefatos são arquivos persistidos produzidos durante um run, como:
- preprocessadores
- modelos treinados
- bundles de inferência
- métricas e resultados
- relatórios MD/PDF

Todo artefato **só é considerado válido** se estiver:
- persistido em diretório do run
- referenciado no manifest
- com hash/checksum registrado

---

## 3. Rastreabilidade Full Run

### 3.1 Definição de Full Run

Um **full run** é uma execução que:

- inicia na ingestão de dados
- percorre todas as etapas declaradas do pipeline
- executa builders obrigatórios intermediários
- produz artefatos finais consumíveis
- gera um manifest completo e consistente

A rastreabilidade **full run** garante que **nenhuma decisão crítica**
ocorra fora do escopo auditável.

---

### 3.2 Papel da Suíte E2E

A suíte de testes **End-to-End (E2E)** é o mecanismo canônico que **prova**
a rastreabilidade full run.

Os testes E2E devem garantir que:
- o manifest final existe
- todos os steps executados estão registrados
- builders obrigatórios estão representados
- todos os artefatos finais estão referenciados
- não existem gaps de auditoria

Sem E2E, a rastreabilidade é considerada **incompleta**.

---

## 4. Regras Canônicas do Manifest

### 4.1 Identidade do Run

Todo run deve possuir:
- `run_id` único
- timestamp de início e fim
- versão do Atlas DataFlow
- hash do contrato e da config
- origem do dataset (path lógico + hash)

---

### 4.2 Registro de Steps e Builders

Para cada **Step** executado, o manifest deve registrar:
- `step_id`
- `kind`
- `status` (success | skipped | failed)
- timestamps e duração
- summary
- warnings e erros
- artefatos gerados

Para cada **Builder obrigatório** (ex.: preprocess):
- identificação explícita no manifest
- etapa lógica no pipeline (before/after)
- artefatos produzidos
- hash correspondente

---

### 4.3 Snapshot de Config e Contrato

O manifest deve conter:
- config efetiva (após merge)
- contrato efetivo
- hashes dos conteúdos
- versões associadas

---

## 5. Estrutura Canônica do Diretório de Execução

Cada full run deve produzir um diretório isolado:

```text
<run_dir>/
 ├── manifest.json
 ├── config.effective.json
 ├── contract.frozen.yaml
 ├── artifacts/
 │   ├── preprocess.joblib
 │   ├── model.joblib
 │   ├── inference_bundle.joblib
 │   ├── metrics.json
 │   └── report.md
 └── payloads/
     ├── ingest.load.json
     ├── contract.validate.json
     ├── train.single.json
     └── ...
```

Regras:
- nenhum run sobrescreve outro
- todos os paths são relativos ao run
- todo arquivo relevante é rastreável

---

## 6. Regras Canônicas de Auditoria

### 6.1 Payload mínimo obrigatório

Toda auditoria deve conter:

```yaml
step_id: string
kind: step | builder
status: success | skipped | failed
summary: string
metrics: {}
warnings: []
artifacts: []
```

### 6.2 Transformações exigem before/after

Etapas que transformam dados devem registrar:
- shape antes e depois
- colunas afetadas
- contagens relevantes
- regra aplicada

---

## 7. Integração com Testes E2E

Os testes E2E devem validar explicitamente que:
- o manifest final existe
- todos os artefatos esperados estão listados no manifest
- hashes correspondem aos arquivos reais
- não existem steps ou builders executados fora do manifest

Falhas em qualquer ponto **invalidam a rastreabilidade**.

---

## 8. Regra de Ouro

Se:
- um artefato não está no manifest,
- um builder obrigatório não está registrado,
- um step executou sem auditoria,

**a execução não é rastreável e deve ser considerada inválida.**
