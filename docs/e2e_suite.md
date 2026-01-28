
# Atlas DataFlow — E2E Suite (Canonical)

## 1. Motivação da Suite E2E

A suíte **End-to-End (E2E)** do Atlas DataFlow existe para provar, de forma
inequívoca, que o framework funciona como **sistema integrado**, e não apenas
como um conjunto de componentes corretos isoladamente.

Ela responde às perguntas fundamentais:

- O mesmo core suporta múltiplos domínios?
- Contratos distintos são respeitados sem heurísticas?
- Todos os artefatos finais são gerados e rastreáveis?
- A execução é determinística e auditável?

A suíte E2E é a **evidência final de qualidade, rastreabilidade e reutilização**
do Atlas DataFlow.

---

## 2. Como Executar a Suite

Executar cenários individualmente:

```bash
pytest -q tests/e2e/test_pipeline_telco_like.py
pytest -q tests/e2e/test_pipeline_bank_like.py
```

Executar toda a suíte de testes:

```bash
pytest -q
```

A execução deve:
- ser determinística
- não depender de serviços externos
- rodar integralmente em ambiente local

---

## 3. Estrutura Canônica da Suite

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

Os arquivos `_helpers.py` definem o **contrato operacional** da suíte E2E
e não devem ser reimplementados por testes individuais.

---

## 4. Como Adicionar um 3º Cenário (via config/fixtures)

Adicionar um novo cenário **NÃO exige alteração no core**.

Passos canônicos:

1. Criar um dataset sintético mínimo
2. Criar um contrato versionado correspondente
3. Criar uma config explícita e determinística
4. Criar um novo teste em `tests/e2e/` seguindo o padrão existente

Exemplo:

```
tests/e2e/
 ├── test_pipeline_retail_like.py
 └── fixtures/
     └── retail/
         ├── retail_like.csv
         ├── contract.internal.v1.json
         └── config.pipeline.yml
```

O teste deve:
- usar `run_pipeline(...)`
- validar artefatos com `assert_core_artifacts(...)`
- validar determinismo com `assert_reports_equal(...)`

Se qualquer ajuste no core for necessário,
o cenário **não é válido como E2E canônico**.

---

## 5. Checklist — Não Quebrar Invariantes

Antes de considerar um novo cenário E2E válido, confirme:

- [ ] Nenhuma alteração no core foi necessária
- [ ] Todas as variações ocorrem via config e contrato
- [ ] Seeds explícitos estão definidos (`split`, `train`)
- [ ] `target_metric` está definido em `evaluate.model_selection`
- [ ] Paths são relativos ao `run_dir` quando aplicável
- [ ] `representation.preprocess` foi executado explicitamente
- [ ] Todos os artefatos finais foram gerados
- [ ] `assert_reports_equal` valida determinismo (Run A vs Run B)

Se qualquer item falhar, o cenário **não deve ser integrado**.

---

## 6. Regra Final

Se um cenário:
- quebra invariantes,
- exige heurísticas,
- depende de estado externo,

**ele não pertence à suíte E2E do Atlas DataFlow.**
