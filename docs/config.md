# Atlas DataFlow — Config Canonical Specification

## 1. Propósito do Documento

Este documento define a **especificação canônica de Configuração (config)** do Atlas DataFlow.

A configuração controla **como o pipeline é executado**, sem jamais alterar o **significado semântico dos dados**, que é responsabilidade exclusiva do **Contrato**.

Este documento é fonte de verdade para:
- comportamento operacional do pipeline
- ativação e parametrização de steps
- políticas de execução do engine
- controle por ambiente (local, dev, prod)
- reprodutibilidade e determinismo

---

## 2. Princípio Fundamental

> **Config controla comportamento.  
> Contrato controla significado.**

Qualquer violação desta separação deve ser considerada **erro arquitetural**.

---

## 3. Formato Oficial

O formato oficial de configuração do Atlas DataFlow é:

> **YAML**

### Justificativa
- Alta legibilidade para humanos
- Suporte nativo a comentários
- Aderência a pipelines modernos (Airflow, dbt, MLflow, etc.)
- Adequado para composição de defaults e overrides

Configurações **não devem** ser escritas em JSON.

---

## 4. Arquivos Canônicos de Configuração

A configuração é composta por **dois níveis explícitos**:

### 4.1 `defaults.yaml`

- Define valores padrão do pipeline
- Versionado em repositório
- Compartilhado por todos os ambientes
- Nunca contém segredos

### 4.2 `local.yaml`

- Define overrides locais ou por ambiente
- **Nunca versionado**
- Deve constar no `.gitignore`
- Pode conter paths, flags locais, segredos ou ajustes temporários

---

## 5. Política de Merge (Deep Merge)

O Atlas DataFlow adota **deep-merge determinístico** entre arquivos de configuração.

### Regras:
1. `defaults.yaml` é carregado primeiro
2. `local.yaml` é aplicado sobre ele
3. Estruturas aninhadas são mescladas recursivamente
4. Valores escalares em `local.yaml` **sobrescrevem** os defaults
5. Chaves ausentes em `local.yaml` preservam o valor do default

> **Nunca é permitido merge implícito ou silencioso fora dessa política.**

---

## 6. Exemplo de Configuração

### defaults.yaml
```yaml
engine:
  fail_fast: true
  log_level: INFO

steps:
  ingest:
    enabled: true
  preprocess:
    enabled: true
  train:
    enabled: true
```

### local.yaml
```yaml
engine:
  log_level: DEBUG

steps:
  train:
    enabled: false
```

### Resultado efetivo
```yaml
engine:
  fail_fast: true
  log_level: DEBUG

steps:
  ingest:
    enabled: true
  preprocess:
    enabled: true
  train:
    enabled: false
```

---

## 7. O que Pode Existir no Config

Exemplos permitidos:
- flags de ativação de steps
- parâmetros de execução
- paths de entrada/saída
- políticas de erro
- parâmetros de engine
- controles por ambiente

---

## 8. O que NÃO Pode Existir no Config

É proibido no config:
- definição de target
- definição de tipos semânticos
- regras de validação de dados
- defaults semânticos
- regras de compatibilidade
- qualquer lógica que afete inferência

Esses elementos pertencem **exclusivamente ao Contrato**.

---

## 9. Validação

Toda configuração carregada deve:
- ser validada estruturalmente
- respeitar a política de merge definida
- gerar erro explícito em caso de inconsistência

Nenhuma correção automática é permitida.

---

## 10. Integração com Outros Documentos

Este documento deve ser usado em conjunto com:
- `docs/contract.md`
- `docs/domain/domain.core-pipeline.v1.md`
- `docs/engine.md`
- `docs/traceability.md`

---

## 11. Regra de Ouro

Se uma regra:
- altera o comportamento da execução,
- controla fluxo ou ativação,
- depende de ambiente,

**ela pertence ao config — nunca ao contrato.**
