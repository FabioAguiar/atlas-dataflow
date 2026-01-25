# Spec — e2e.pipeline v1

## Visão Geral

A **Suite E2E do Atlas DataFlow** valida o funcionamento do sistema como um
**pipeline integrado**, garantindo que todos os componentes canônicos
operem corretamente quando encadeados.

O objetivo da suíte E2E **não é testar detalhes internos**, mas verificar
que o Atlas:

- respeita contratos distintos
- mantém invariantes de rastreabilidade
- gera artefatos finais consistentes
- é reutilizável entre domínios

---

## Escopo (v1)

Incluído:

- Execução completa do pipeline
- Múltiplos cenários de domínio
- Geração e validação de artefatos finais
- Execução determinística

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

- Dataset sintético com churn
- Contrato com features categóricas e numéricas
- Pipeline supervisionado padrão

### Bank-like

Características:

- Dataset sintético com churn bancário
- Contrato distinto (features e tipos diferentes)
- Mesmo core e mesmos Steps

Ambos os cenários devem diferir **apenas por configuração e contrato**.

---

## Pipeline Validado

Cada cenário **DEVE executar** a sequência completa:

1. Ingestão (`ingest.load`)
2. Contrato
   - `contract.load`
   - `contract.conformity_report`
3. Preparação
   - `representation.preprocess`
4. Treino
   - `train.single` ou `train.search`
5. Avaliação
   - `evaluate.metrics`
   - `evaluate.model_selection`
6. Exportação
   - `export.inference_bundle`
7. Reporting
   - `report.md`
   - (opcional) `report.pdf`

---

## Artefatos Esperados

Para cada execução E2E, devem existir:

- preprocess persistido
- modelo treinado
- métricas finais
- bundle de inferência
- report.md
- entradas correspondentes no Manifest

---

## Regras de Execução

- Cada cenário deve rodar de forma isolada
- Um cenário não pode poluir o outro
- Paths e artefatos devem ser separados
- Nenhuma dependência externa é permitida

---

## Determinismo

Para um cenário fixo:

- resultados devem ser reproduzíveis
- hashes devem ser estáveis
- artefatos devem ser equivalentes

---

## Falhas e Critérios de Erro

A suíte E2E **DEVE falhar explicitamente** quando:

- algum Step obrigatório falhar
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
    ├── test_pipeline_telco_like.py
    └── test_pipeline_bank_like.py
```

Cada teste deve:

- montar config e contrato
- executar pipeline completo
- validar artefatos e Manifest

---

## Versionamento

- Esta especificação define o **e2e.pipeline v1**
- Novos cenários exigem extensão explícita
- Mudanças estruturais exigem nova versão

---

## Referências

- `docs/spec/contract.internal.v1.md`
- `docs/spec/representation.preprocess.v1.md`
- `docs/spec/train.single.v1.md`
- `docs/spec/evaluate.metrics.v1.md`
- `docs/spec/export.inference_bundle.v1.md`
- `docs/spec/report.md.v1.md`
- `docs/spec/report.pdf.v1.md`
- `docs/traceability.md`
- `docs/manifest.schema.v1.md`
- `docs/testing.md`