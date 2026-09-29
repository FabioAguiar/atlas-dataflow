# Dry Bean — Scientific Study, Scientific Reproduction e Release Nativa Atlas

Esta página separa três coisas que não podem ser confundidas:

1. **Scientific Study**: o estudo externo `dataset-study-dry-bean`, que é a fonte de verdade do protocolo.
2. **Scientific Reproduction in Atlas**: uma execução independente do protocolo pelo Atlas, comparada com a evidência do estudo.
3. **Active Atlas Native Release**: o modelo nativo publicado pelo Atlas, com split, protocolo e métricas próprios.

Os números de (1) e (2) descrevem o experimento científico. Os de (3) descrevem outro experimento. Eles não são intercambiáveis.

## 1. Scientific Study (referência)

| Item | Valor |
|---|---|
| Repositório | `https://github.com/FabioAguiar/dataset-study-dry-bean` |
| Revisão pinada | `e3e697c1b60f7b11f4ccb7e82447a6680bc2bfaf` (2026-09-28) |
| Evidência estruturada | `reproducibility/canonical-run.json` (`canonical-run.v1`), SHA-256 fixado no contrato |
| Contrato Atlas | `pipeline/scientific-studies/dry-bean/study-e3e697c1b60f/scientific-study-contract.json` (`scientific-study-contract.v2`) |
| Rascunho de autoria | `pipeline/scientific-studies/dry-bean/study-e3e697c1b60f/authoring/contract-draft.json` |
| Dataset | UCI 602, `dataset.csv`, 13.611 × 17, SHA-256 `1330e4cc…655787` |
| Problema | `multiclass_classification`, 7 classes nominais, `argmax`, sem classe positiva e sem threshold |
| Ambiente de referência | CPython 3.13.13, linux-aarch64, scikit-learn 1.9.0, pandas 3.0.5, numpy 2.5.3, scipy 1.18.1, joblib 1.5.3 (`pylock.toml`, `.python-version`) |

O contrato não transcreve resultados à mão. Os 212 valores, 15 das 18 decisões e o item de identidade de runtime são lidos do `canonical-run.json` por JSON pointer (`author_contract_from_draft`). As outras 3 decisões (shortlist, grupo de empate prático e critério decisivo) não existem como campos estruturados no canonical run e vêm do README na revisão pinada, com locator de texto. Os 35 parâmetros declarados do protocolo (seeds 42/43, frações, CV, tolerância de empate 0,002, margem sobre o Dummy 0,02, ordens de classes, ordem de features, pins de ambiente…) são reconferidos contra o `canonical-run.json` por `verify_against_study_checkout`. Resultado na revisão pinada: `synchronized`, com 19/19 arquivos pinados, 235/235 locators e 35/35 parâmetros.

### Validação do próprio estudo nesta sessão

- `pytest` do estudo: **838 passed**, incluindo limpeza de notebooks, canonical run, runner de notebooks e contrato de ambiente.
- Os cinco notebooks oficiais foram executados com `scripts/run_notebooks.py --fresh` no ambiente do `pylock.toml` (CPython 3.13.13, pacotes idênticos, linux-x86_64).
- `python -m scripts.canonical_run verify`: todas as métricas coincidem com tolerância 1e-9. `final_model.artifact_sha256` e `model_state_fingerprint` também coincidem. Só `final_test.probability_matrix_sha256` diverge (`c2b6082c…` contra `257d6752…` de referência), por diferença de bytes de ponto flutuante entre arquiteturas. Não é defeito científico e o estudo não foi alterado.

### Limitação histórica (preservada)

O protocolo canônico corrigido isola o test **procedimentalmente**: o split é congelado primeiro, a exploração usa só o train, o test não é usado para ajuste e é aberto uma única vez, depois de congeladas a seleção e o fit final. **A mesma partição de test (seed 42) foi, porém, avaliada uma vez pela execução anterior, hoje superseded**, cuja exploração no dataset completo também informou o desenho das políticas de features. O test não deve ser descrito como "nunca visto" nem como "previously unseen". Essa limitação está no contrato (`protocol_integrity.historical_test_exposure`) e em todo relatório de reprodução.

## 2. Scientific Reproduction in Atlas

Run `pipeline/scientific-reproduction-runs/dry-bean/repro-20260929T163341Z/` (relatório `reproduction-report.json` e todas as configurações de busca em `search-results.json`).

Execução reproduzível:

```bash
python -m pipeline.scientific_reproduction \
  --contract pipeline/scientific-studies/dry-bean/study-e3e697c1b60f/scientific-study-contract.json \
  [--study-checkout <checkout read-only do estudo>]
```

O dataset fica em `data/scientific-studies/dry-bean/dataset.csv` (gitignored) e só é aceito se SHA-256 e tamanho baterem. Nesta sessão a UCI estava bloqueada pela política de rede. O arquivo foi reconstruído a partir do espelho público `github.com/topepo/beans` (dados Koklu & Ozkan 2020), com os nomes de coluna da UCI e os valores renderizados como no formato "General" do Excel usado pelo CSV da UCI (no máximo 11 caracteres), gravados como `DataFrame.to_csv(index=False)`, igual ao `ucimlrepo` no estudo. O resultado é byte a byte idêntico: SHA-256 `1330e4cc…655787`, 2.471.169 bytes.

### Ambiente

| Componente | Referência | Reprodução | Classe |
|---|---|---|---|
| Python | 3.13.13 | 3.13.13 | exact |
| scikit-learn / pandas / numpy / scipy / joblib | 1.9.0 / 3.0.5 / 2.5.3 / 1.18.1 / 1.5.3 | idênticos | exact |
| Plataforma | linux-aarch64 | linux-x86_64 | compatible |

Classificação geral: **`compatible`**. O protocolo científico é o mesmo; o runtime não é byte-idêntico.

### Protocolo executado × referência

| Etapa | Atlas (reproduzido) | Estudo (esperado) | Status |
|---|---|---|---|
| Dataset SHA-256 | `1330e4cc…` | `1330e4cc…` | exato |
| Split (dois estágios, `train_test_split`, seeds 42 → 43) | 9.527 / 2.042 / 2.042 | 9.527 / 2.042 / 2.042 | exato |
| Membership SHA-256 (train/val/test) | `34e9cb09…` / `f2d74e5b…` / `534ff2e4…` | idem | gate aprovado |
| Partition SHA-256 | `485594b3…` / `f379db88…` / `5e17c134…` | idem | exato |
| LR, `GridSearchCV`, 4 candidatos | C=1.0, class_weight=None, CV macro-F1 0.9350306225 | idem | exato |
| DT, `GridSearchCV`, 8 | max_depth=8, min_samples_leaf=5, balanced, 0.9199041282 | idem | exato |
| RF, `RandomizedSearchCV` (seed 42), 8 | n_estimators=120, max_depth=None, leaf=1, None, 0.9333427904 | idem | exato |
| HGB, `RandomizedSearchCV` (seed 42), 8 | lr=0.05, max_iter=250, leaves=15, leaf=40, l2=0.0, None, 0.9370121386 | idem | exato |
| Shortlist (top-2 por CV macro-F1) | HGB, LR | HGB, LR | exato |
| 6 candidatos família × política | todos elegíveis (margem > 0,02 sobre Dummy 0,059052) | idem | exato |
| Empate prático (tolerância 0,002) | {HGB all_features, HGB without_shape_factor_2}, Δ = 0,0012044 | idem | exato |
| Desempate | `higher_validation_balanced_accuracy`: 0,939131 × 0,938146 | idem | exato |
| Selecionado | `hist_gradient_boosting__all_features` (HistGradientBoostingClassifier, 16 features) | idem | exato |
| Fit final | train + validation = 11.569 linhas (BARBUNYA 1123, BOMBAY 444, CALI 1386, DERMASON 3014, HOROZ 1639, SEKER 1723, SIRA 2240) | idem | gate aprovado |
| Regra de decisão | `argmax` (probabilidades mapeadas por `estimator.classes_`); threshold **não aplicável**; 0 empates exatos | argmax | — |

### Teste final (uma avaliação, 2.042 linhas)

| Métrica | Esperado (estudo) | Reproduzido (Atlas) | Delta | Status |
|---|---:|---:|---:|---|
| Macro F1 | 0.9418353636024855 | 0.9418353636024855 | 0 | exato |
| Balanced Accuracy | 0.9398971908347276 | 0.9398971908347276 | 0 | exato |
| Accuracy | 0.9324191968658179 | 0.9324191968658179 | 0 | exato |
| Weighted F1 | 0.9321874638643965 | 0.9321874638643965 | 0 | exato |
| Macro Recall | 0.9398971908347276 | 0.9398971908347276 | 0 | exato |
| Minimum per-class recall (SIRA) | 0.8686868686868687 | 0.8686868686868687 | 0 | exato |
| Log Loss | 0.18102390031373491 | 0.1810239003137349 | −2,8e-17 | exato |

Também coincidem exatamente: a matriz de confusão, comparada **junto com** a ordem pública de classes `SEKER, BARBUNYA, BOMBAY, CALI, DERMASON, HOROZ, SIRA`; as métricas por classe (precision, recall, F1, support) em validação e teste; os pares de confusão (DERMASON↔SIRA 58, BARBUNYA↔CALI 19, SEKER↔DERMASON 17; focais com 68/21 erros mútuos em validação); a ordem de classes do estimador (`BARBUNYA … SIRA`, conferida contra o `classes_` ajustado); e a sensibilidade a perfis repetidos (15 linhas, delta de macro-F1 −0,000312). O test oficial continua completo, e essa análise não prova identidade duplicada nem vazamento.

### Resultado

- 230 quantidades comparadas: **229 exatas**, **1 dentro da tolerância declarada** (log loss de validação de `logistic_regression__all_features`, Δ 1,5e-11, ruído do lbfgs entre arquiteturas), **0 divergentes, 0 ausentes**.
- Identidade de runtime: `probability_matrix_sha256` difere da referência aarch64. O hash do Atlas (`c2b6082c…`) é idêntico ao que o próprio estudo gera ao ser reexecutado nesta mesma máquina x86_64. Essa diferença vem da plataforma, não do protocolo.
- Tolerância declarada **antes** da primeira execução (commit do contrato anterior ao do run): `numeric_absolute = 1e-6` (três ordens de grandeza abaixo do empate prático de 0,002); contagens, decisões, ordens e matrizes exatas.
- **Status: `reproduced_within_tolerance`**. Motivos: ambiente `compatible`, um valor dentro da tolerância e runtime não byte-idêntico. Camadas de evidência: `structural_exact = true`, `numeric_within_tolerance = true`, `scientific_mismatches = 0`, `unsupported_capabilities = 0`.

## 3. Active Atlas Native Release (linhagem separada)

A release nativa ativa (`release-20260818-002`, training run `train-20260818T235937Z`) vem de `pipeline/training.py` com `selection_mode = fixed_configuration` e HGB como única família permitida. Ela **não** é uma reprodução científica e não foi alterada.

| Fato | Atlas nativo | Scientific Reproduction |
|---|---|---|
| Split | estratificado nativo (`random_seed = 42`), test com **2.044** linhas | dois estágios `train_test_split` (42 → 43), test com **2.042** linhas, membership verificado |
| Seleção | `fixed_configuration` (hiperparâmetros congelados, sem busca) | 4 famílias → shortlist → 3 políticas de features → empate prático |
| Métrica primária | `f1_macro` | `macro_f1` |
| Decisão | argmax (`result_semantics` nativo) | argmax; threshold não aplicável |
| Macro F1 teste | 0,943297 | 0,941835 |
| Balanced Accuracy teste | 0,943582 | 0,939897 |
| Log Loss teste | 0,194228 | 0,181024 |

As partições são diferentes, então as métricas não são diretamente comparáveis. `scientific_reproduction.describe_lineage_separation` gera essa visão em modo read-only, com proveniência de cada valor e `directly_comparable: false`. Os artefatos históricos (training runs, release candidates, releases, publisher runs, registry) não foram modificados.

## 4. Perfil público publicado: correção pendente de publicação

O snapshot publicado em `registry/profile-snapshots/dry-bean.json` (2026-09-01) apresenta os números do estudo como documentação do dataset e contém dois problemas:

- a frase da seção de avaliação final que chama as observações de test de "previously unseen", o que contradiz o `superseded_reference` do estudo;
- 10 imagens referenciadas pelo branch mutável `main` do estudo (via raw.githubusercontent.com), uma referência mutável para evidência que diz representar uma revisão congelada.

O perfil público só muda pelo fluxo governado de publicação do Dataset Admin, que grava snapshot, `.previous` e evidência de publicação. Reescrever o snapshot por commit burlaria esse fluxo e o histórico do registry. Por isso ele **não** foi alterado nesta mudança. Correção recomendada, a publicar por um operador:

1. Trocar a frase por: "The final test contains 2,042 observations. The corrected protocol isolates this partition procedurally (split frozen first, training-only exploration, test opened once after selection and final fit); the same seed-42 test partition was also evaluated once by a superseded pre-correction execution."
2. Trocar o segmento de branch `main` por `e3e697c1b60f7b11f4ccb7e82447a6680bc2bfaf` nos URLs das imagens, que são as mesmas figuras pinadas por SHA-256 no contrato (`docs/images/*.png`).
3. Rotular a tabela de resultados como **Scientific Study** (com o status da reprodução Atlas: `reproduced_within_tolerance`, run `repro-20260929T163341Z`) e, em seção separada, mostrar as métricas da **release nativa ativa**, de outro split.

`tests/pipeline/test_scientific_reproduction_docs.py` impede que a documentação do repositório e o notebook voltem a referenciar o estudo por branch mutável ou a afirmar que o test nunca foi visto. O snapshot publicado fica fora desse teste até ser republicado.
