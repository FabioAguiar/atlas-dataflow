# 📄 persistence.preprocess — Persistência do Preprocess (v1)

## Visão Geral

Esta spec define o contrato de **persistência do preprocess** construído pelo Builder
`representation.preprocess` no Atlas DataFlow.

Persistir o preprocess é obrigatório para garantir:
- reprodutibilidade entre execuções
- consistência entre treino, validação e inferência
- rastreabilidade completa via Manifest

No Atlas, **nenhum artefato de representação é implícito ou efêmero**.

---

## Objetivo

- Definir como o preprocess deve ser persistido
- Estabelecer metadata mínima obrigatória no Manifest
- Garantir round-trip load determinístico
- Padronizar o formato e o local de armazenamento

---

## Natureza do Artefato

- **Tipo:** preprocess
- **Formato:** `joblib`
- **Origem:** Builder `representation.preprocess`
- **Milestone:** M4 — Representação & Modelagem
- **Caráter:** Artefato reutilizável e auditável

---

## Localização Canônica

O preprocess deve ser salvo no diretório de artefatos do run:

```
artifacts/
  preprocess.joblib
```

O caminho deve ser **determinístico** e **único por run**.

---

## Estratégia de Persistência

- Utilizar `joblib.dump` para serialização
- Não modificar o objeto preprocess antes de salvar
- Garantir compatibilidade com `joblib.load`

Nenhuma serialização alternativa é permitida nesta versão.

---

## Registro no Manifest

O Manifest deve conter, no mínimo:

```yaml
artifacts:
  preprocess:
    type: preprocess
    format: joblib
    path: artifacts/preprocess.joblib
    builder: representation.preprocess
    spec_version: v1
```

### Invariantes

- Metadata obrigatória
- Vínculo explícito com o Builder de origem
- Caminho relativo ao diretório do run
- Uma entrada por artefato

---

## Round-Trip Load

O sistema deve garantir que:

1. O preprocess seja salvo
2. O preprocess seja carregado posteriormente
3. A aplicação de `transform(X)` produza **resultado idêntico**
   para um dataset fixo

Qualquer divergência deve ser tratada como falha.

---

## Falhas Explícitas

O sistema deve falhar quando:

- o artefato não existir no caminho esperado
- o arquivo estiver corrompido
- o load não produzir objeto compatível
- metadata obrigatória estiver ausente no Manifest

Falhas devem ser **claras e rastreáveis**.

---

## Testes Esperados

Os testes unitários devem cobrir:

- Persistência via `joblib.dump`
- Registro correto no Manifest
- Load via `joblib.load`
- Round-trip com resultado idêntico
- Falha explícita em artefato ausente

---

## Fora de Escopo (v1)

- Versionamento automático de artefatos
- Migração entre versões incompatíveis
- Persistência de datasets
- Persistência de modelos treinados

---

## Evolução Futura

Possíveis extensões:

- Versionamento semântico de preprocess
- Hash/fingerprint do artefato
- Compatibilidade cross-version
- Persistência em storage remoto

---

## Referências

- `docs/spec/representation.preprocess.v1.md`
- `docs/pipeline_elements.md`
- `docs/engine.md`
- `docs/traceability.md`
- `docs/manifest.schema.v1.md`
- `docs/testing.md`
