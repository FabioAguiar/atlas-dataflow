# Spec — e2e.pipeline v1

## Visão Geral

A **Suite E2E do Atlas DataFlow** valida o funcionamento do sistema como um
**pipeline integrado**, garantindo que todos os componentes canônicos
operem corretamente quando encadeados **exatamente como definidos no core**.

O objetivo da suíte E2E **não é testar detalhes internos**, mas provar que o Atlas:

- respeita contratos distintos
- mantém invariantes de rastreabilidade
- gera artefatos finais consistentes
- é reutilizável entre domínios **sem alterações no core**

Esta especificação descreve **o pipeline real executado hoje**, incluindo
operações realizadas por *builders* explícitos quando não existe um Step canônico.

---

## Escopo (v1)

Incluído:

- Execução completa do pipeline
- Múltiplos cenários de domínio (Telco-like, Bank-like)
- Variação **exclusiva via contrato + configuração**
- Geração e validação de artefatos finais
- Execução determinística e isolada

Excluído (fora de escopo):

- Testes de performance
- Testes de carga
- Avaliação estatística profunda
- Integrações externas
- Dados reais sensíveis

---

## Cenários Obrigatórios

A suíte E2E v1 **DEVE** cobrir, no mínimo, dois cenários:

### Telco-like

Características:

- Dataset sintético representando churn em telecom
- Contrato com mistura de features numéricas e categóricas
- Pipeline supervisionado padrão

### Bank-like

Características:

- Dataset sintético representando churn bancário
- Contrato distinto (features, tipos e target diferentes)
- **Mesmo core e mesma sequência de execução**

Ambos os cenários devem diferir **apenas por configuração e contrato**.

---

## Pipeline Validado (Real)

Cada cenário **DEVE executar** a sequência abaixo, **na ordem real do core**:

### 1. Ingestão

- `ingest.load`

Responsável por carregar o dataset de forma determinística e rastreável.

---

### 2. Contrato

- `contract.load`
- `contract.validate`

O contrato é validado contra o schema **internal contract v1**.
Nenhuma inferência implícita é permitida.

---

### 3. Split

- `split.train_test`

Define conjuntos de treino e teste de forma determinística.

---

### 4. Preparação de Representação (Builder obrigatório)

⚠️ **Observação importante**

Atualmente **NÃO existe um Step canônico chamado `representation.preprocess`**.

A preparação da representação ocorre por meio de:

- `builders.representation.preprocess.build_representation_preprocess`
- persistência explícita via `PreprocessStore.save(...)`

Este builder é **obrigatório** e deve ser executado:

➡️ **após o split**
➡️ **antes do treino**

A suíte E2E **DEVE executar explicitamente este builder**, pois ele faz parte
do pipeline real, ainda que não seja um Step.

---

### 5. Treino

- `train.single` (ou variações futuras)

Utiliza a representação persistida gerada pelo builder de preprocess.

---

### 6. Avaliação

- `evaluate.metrics`

Geração de métricas finais associadas ao modelo treinado.

---

### 7. Exportação

- `export.inference_bundle`

Geração do bundle de inferência contendo modelo + preprocess.

---

### 8. Reporting

- `report.generate` → `report.md`
- (opcional) `report.pdf`

Consolidação final da execução a partir do Manifest.

---

## Artefatos Esperados

Para cada execução E2E, **DEVEM existir**:

- `artifacts/preprocess.joblib`
- modelo treinado persistido
- métricas finais
- `artifacts/inference_bundle.joblib`
- `artifacts/report.md`
- entradas correspondentes no `manifest.json`

---

## Regras de Execução

- Cada cenário deve rodar em `run_dir` isolado
- Um cenário **não pode poluir** o outro
- Paths e artefatos devem ser separados
- Nenhuma dependência externa é permitida
- Nenhuma heurística específica de domínio é aceita

---

## Determinismo

Para um cenário fixo:

- resultados devem ser reproduzíveis
- seeds e parâmetros devem ser explícitos
- `report.md` deve ser byte-a-byte equivalente entre execuções

---

## Falhas e Critérios de Erro

A suíte E2E **DEVE falhar explicitamente** quando:

- algum Step obrigatório falhar
- o builder de preprocess não for executado
- artefatos finais não forem gerados
- Manifest estiver inconsistente
- contrato não for respeitado

Falhas silenciosas são proibidas.

---

## Organização dos Testes

Estrutura sugerida:

```
tests/
└── e2e/
    ├── _helpers.py
    ├── test_pipeline_telco_like.py
    ├── test_pipeline_bank_like.py
    └── fixtures/
        ├── telco/
        └── bank/
```

Cada teste deve:

- montar contrato e config
- executar pipeline completo
- executar explicitamente o builder de preprocess
- validar artefatos e Manifest

---

## Versionamento

- Esta especificação define o **e2e.pipeline v1**
- Mudanças no pipeline real exigem atualização explícita desta spec
- Introdução de novos Steps ou remoção do builder exige nova versão

---

## Referências

- `docs/spec/contract.internal.v1.md`
- `docs/spec/train.single.v1.md`
- `docs/spec/evaluate.metrics.v1.md`
- `docs/spec/export.inference_bundle.v1.md`
- `docs/spec/report.md.v1.md`
- `docs/spec/report.pdf.v1.md`
- `docs/traceability.md`
- `docs/manifest.schema.v1.md`
- `docs/testing.md`
