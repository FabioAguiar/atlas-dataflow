# Atlas DataFlow — Traceability Canonical Rules

## 1. Propósito do Documento

Este documento define as **regras canônicas de rastreabilidade** do Atlas DataFlow.  
Ele estabelece como **manifest**, **artefatos** e **auditorias** devem ser produzidos, persistidos e consumidos.

Este documento é **fonte de verdade** para:
- implementação do manifest e event log
- persistência de artefatos (modelos, preprocess, relatórios)
- critérios de auditoria por step
- integração com APIs e adapters
- definição de testes de qualidade e reprodutibilidade

---

## 2. Conceitos-Chave

### 2.1 Manifest

O **manifest** é o registro forense de uma execução do pipeline.

Ele contém:
- identidade do run
- snapshot de config e contrato
- lista de steps executados
- decisões registradas
- warnings e erros
- artefatos gerados

O manifest deve permitir:
- reproduzir a execução
- explicar resultados
- depurar falhas
- auditar decisões

---

### 2.2 Auditoria

Auditoria é a evidência estruturada produzida por cada step.

Toda auditoria deve:
- ser serializável
- ser agregável no manifest
- ser consumível por UI e relatórios
- incluir impacto quando houver transformação

---

### 2.3 Artefatos

Artefatos são arquivos persistidos produzidos pelo pipeline, como:
- preprocessadores
- modelos treinados
- bundles de inferência
- métricas e resultados de busca
- relatórios MD/PDF

---

## 3. Regras Canônicas do Manifest

### 3.1 Identidade do Run

Todo run deve ter:
- `run_id` único
- timestamp de início e fim
- versão do Atlas DataFlow (semântica)
- hash do contrato e da config
- origem do dataset (e hash/checksum)

---

### 3.2 Registro de Steps

Para cada step executado, o manifest deve registrar:
- `step_id`
- `kind`
- `status` (success | skipped | failed)
- timestamps (start/end) e duração
- resumo (`summary`)
- warnings e erros (se aplicável)
- paths e hashes de artefatos gerados
- referência ao payload de auditoria

---

### 3.3 Snapshot de Config e Contrato

O manifest deve conter:
- referência ao arquivo de config efetivo (defaults + local merge)
- referência ao contrato efetivo
- hashes dos conteúdos
- (opcional) cópia congelada no diretório de artifacts

---

## 4. Estrutura Canônica do Diretório de Execução

O pipeline deve produzir um diretório por run:

```text
artifacts/
 └── runs/
     └── <run_id>/
         ├── manifest.json
         ├── config.effective.json
         ├── contract.frozen.yaml
         ├── payloads/
         │   ├── ingest.load.json
         │   ├── audit.profile_baseline.json
         │   └── ...
         ├── models/
         ├── preprocess/
         ├── metrics/
         └── reports/
```

Regra:
- Nenhum run deve sobrescrever outro.
- Artefatos devem ser determinísticos e referenciáveis.

---

## 5. Regras Canônicas de Auditoria

### 5.1 Payload mínimo obrigatório

Todo step deve produzir um payload com campos mínimos:

```yaml
step_id: string
kind: string
status: success | skipped | failed
summary: string
metrics: {}
warnings: []
artifacts: []
```

### 5.2 Transformações exigem before/after

Steps `transform` devem registrar:
- shape antes e depois
- colunas afetadas
- contagens antes/depois (missing, duplicados, etc.)
- descrição da regra aplicada

---

## 6. Regras Canônicas de Artefatos

### 6.1 Persistência obrigatória

Artefatos obrigatórios em runs completos:
- preprocessador persistido (quando aplicável)
- modelo persistido (quando aplicável)
- bundle de inferência (quando aplicável)
- contrato congelado
- manifest final completo

### 6.2 Hash e integridade

Todo artefato persistido deve ter:
- path relativo ao run
- hash/checksum
- tipo (model, preprocess, report, metrics)

---

## 7. Integração com Use Cases e APIs

APIs futuras devem ser capazes de:
- carregar bundles de inferência
- validar payload externo usando contrato congelado
- registrar predição em logs compatíveis

O design de rastreabilidade do Atlas DataFlow garante que:
- inferência é reprodutível
- decisões do modelo são explicáveis a partir do run manifest

---

## 8. Testes de Rastreabilidade

O projeto deve possuir testes para:
- criação e atualização do manifest
- persistência sem sobrescrita de runs
- presença de payloads por step
- round-trip load de artefatos (model/preprocess)
- consistência de hashes e paths

---

## 9. Regra de Ouro

Se:
- um artefato não está referenciado no manifest,
- um step não possui payload de auditoria,
- uma decisão não está registrada,

**não existe rastreabilidade no Atlas DataFlow.**
