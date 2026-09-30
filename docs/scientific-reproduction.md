# Scientific Reproduction Contract

Esta página descreve a camada que permite ao Atlas responder, de forma verificável:

> O Atlas consegue reproduzir o protocolo científico desta revisão específica do Dataset Study?

Há quatro casos reais:

| Estudo | Revisão | Problema | Contrato | Status da reprodução |
|---|---|---|---|---|
| `dataset-study-telco-customer-churn` | `43ced1fbb76f` | classificação binária | `scientific-study-contract.v1` | `reproduced_within_tolerance` |
| `dataset-study-dry-bean` | `e3e697c1b60f` | classificação multiclasse (7 classes) + seleção em duas etapas | `scientific-study-contract.v2` | `reproduced_within_tolerance` ([detalhes](scientific-reproduction-dry-bean.md)) |
| `dataset-study-concrete-compressives-strength` | `b223370e0f44` | regressão contínua (MPa) | `scientific-study-contract.v3` | `reproduced_exact` (ver §7b) |
| `dataset-study-nottingham-monthly-temperatures` | `79c6abccbf65` | forecasting univariado mensal (°F) | `scientific-study-contract.v4` | `divergent` — seleção, especificação escolhida e as 12 previsões finais reproduzidas; métricas de Holt-Winters/SARIMA não selecionados fora de 1e-9 (ver §7c) |

A infraestrutura é genérica. O código despacha pelo `problem.problem_type` (adapters `binary_classification`, `multiclass_classification` e `continuous_regression` no runner tabular; `univariate_forecasting` no runner temporal) e não tem nenhum caminho `if telco`, `if dry-bean`, `if concrete` ou `if nottem`; testes garantem que os módulos do motor não citam datasets. O que é específico de cada estudo vive apenas no contrato versionado, na evidência pinada, no notebook de integração e nos artefatos de reprodução.

**Dataset novo ≠ branch de produção novo.** Integrar um estudo novo de um tipo de problema e protocolo já suportados é escrever um contrato, não código. Um *tipo de problema ou protocolo* novo (por exemplo, regressão contínua com split não estratificado e `KFold`) pode exigir evolução **genérica** do motor: um adapter por `problem_type`, um `split.kind` ou `cross_validation.kind` novo, uma família no registry, uma identidade de métrica. Essa evolução é reutilizável por qualquer estudo futuro compatível e nunca ramifica pelo slug do dataset.

Tipos de problema suportados pela reprodução científica: **classificação binária**, **classificação multiclasse**, **regressão contínua** e **forecasting univariado**. O forecasting é executado por um **runner temporal separado do tabular** (`pipeline/scientific_forecasting.py`): não há split aleatório, validação cruzada nem busca de hiperparâmetros, e sim um holdout final selado, backtesting expanding-window e um catálogo congelado de especificações. Identidade do dataset, classificação de ambiente, comparação com a evidência esperada, tolerância, status, linhagens e o relatório write-once são a mesma infraestrutura dos dois runners.

## 1. Linhagens de evidência

| Linhagem | Quem produz | Onde vive | Papel |
|---|---|---|---|
| `scientific_study_run` | Dataset Study externo (read-only) | repositório `dataset-study-*` | evidência de referência pinada no contrato |
| `scientific_reproduction_run` | Atlas, `pipeline/scientific_reproduction.py` | `pipeline/scientific-reproduction-runs/<slug>/<run_id>/` | reprodução independente + comparação |
| `atlas_native_training_run` | Atlas, `pipeline/training.py` | `pipeline/training-runs/<slug>/` | treino nativo governado (inalterado) |
| `atlas_release` | publisher/registry | `releases/`, `registry/datasets.json` | publicação (inalterada) |

Regras aplicadas pelo código e pelos testes:

- o relatório de reprodução declara `atlas_native_training_run.referenced = false` e `atlas_release.referenced = false` (o schema exige esses valores);
- todo `metric_set` tem `provenance.producer_lineage = "scientific_reproduction_run"`, com run, revisão do estudo, hash do contrato, hash do dataset, partição, hash de membership da partição, modelo, threshold (valor, regra e proveniência) e protocolo;
- valores do estudo aparecem apenas no lado `expected` da comparação e nunca são copiados para os resultados reproduzidos. Há um teste que injeta um valor esperado falso e exige o status `divergent`;
- a reprodução nunca lê `run_state`, não grava contrato de execução, training run, release candidate ou registry, e não lê o checkout do estudo em runtime;
- `describe_lineage_separation` mostra nativo e reprodução lado a lado em modo read-only, normalizando nomes de métrica (`pr_auc` nativo é `average_precision`) e marcando `directly_comparable: false`.

## 2. Artefatos e módulos novos

| Caminho | Tipo | Descrição |
|---|---|---|
| `pipeline/model_families.py` | módulo | registry genérico família → estimador por tipo de tarefa; valida hiperparâmetros contra `get_params()` e falha fechado |
| `pipeline/scientific_study_contract.py` | módulo | load + schema + hash do contrato; `assess_protocol_support`; `verify_against_study_checkout` |
| `pipeline/scientific_environment.py` | módulo | extração de pins do `pylock.toml` (PEP 751), captura de runtime e classificação de ambiente |
| `pipeline/scientific_reproduction.py` | módulo + CLI | motor de reprodução, comparação, status, relatório write-once, respostas programáticas, visão de linhagens |
| `pipeline/scientific-study-contract.schema.json` | schema | `scientific-study-contract.v1` |
| `pipeline/scientific-reproduction-report.schema.json` | schema | `scientific-reproduction-report.v1` |
| `pipeline/scientific-studies/telco-customer-churn/study-43ced1fbb76f/scientific-study-contract.json` | contrato | protocolo + evidência de referência do Telco na revisão pinada |
| `pipeline/scientific-reproduction-runs/telco-customer-churn/<run_id>/` | evidência | `reproduction-report.json` + `search-results.json` (todas as configurações de busca) |
| `pipeline/scientific-study-contract.v2.schema.json` | schema | `scientific-study-contract.v2`: binário + multiclasse com regras condicionais |
| `pipeline/scientific-reproduction-report.v2.schema.json` | schema | `scientific-reproduction-report.v2` (os relatórios v1 continuam válidos no schema v1) |
| `pipeline/scientific-studies/dry-bean/study-e3e697c1b60f/` | contrato | contrato Dry Bean + rascunho de autoria (`authoring/contract-draft.json`) |
| `pipeline/scientific-reproduction-runs/dry-bean/repro-20260929T163341Z/` | evidência | primeira reprodução real do Dry Bean |
| `pipeline/scientific-study-contract.v3.schema.json` | schema | `scientific-study-contract.v3`: v2 (binário + multiclasse, inalterados) + `continuous_regression` |
| `pipeline/scientific-reproduction-report.v3.schema.json` | schema | `scientific-reproduction-report.v3`: v2 + regressão, com `interpretive_diagnostics` (os relatórios v1/v2 continuam válidos nos seus schemas) |
| `pipeline/scientific-study-contract.v4.schema.json` | schema | `scientific-study-contract.v4`: ramo tabular idêntico ao v3 + ramo `univariate_forecasting` |
| `pipeline/scientific-reproduction-report.v4.schema.json` | schema | `scientific-reproduction-report.v4`: ramo tabular idêntico ao v3 + relatório temporal |
| `pipeline/scientific_forecasting.py` | módulo | runner temporal (`ForecastingReproduction`): tradução do índice, partições seladas, backtesting, elegibilidade, seleção, finalização, relatório |
| `pipeline/forecasting_models.py` | módulo | um adapter sem estado por família de forecasting (fit do zero + vetor completo de previsão) |
| `pipeline/scientific-studies/nottem/study-79c6abccbf65/` | contrato | contrato Nottingham + rascunho de autoria |
| `pipeline/scientific-reproduction-runs/nottem/repro-20260930T125644Z/` | evidência | `reproduction-report.json` + `backtest-forecasts.json` (todas as previsões fora da amostra) |

`pipeline/training.py` passou a resolver as classes de estimador pelo registry. Os argumentos de construção nativos não mudaram (`LogisticRegression(max_iter=1000, …)` etc.), e o conjunto nativo `SUPPORTED_MODEL_FAMILIES` também não.

### Execução (determinística, orquestrável)

```bash
python -m pipeline.scientific_reproduction \
  --contract pipeline/scientific-studies/telco-customer-churn/study-43ced1fbb76f/scientific-study-contract.json \
  [--study-checkout <checkout read-only do estudo>] [--n-jobs N]
```

Cada etapa é uma função pura sobre entradas declaradas: `verify_dataset_identity`, `apply_preparation`, `split_two_stage_stratified`, `run_candidate_search`, `select_leader_anchored_practical_tie`, `threshold_max_precision_subject_to_min_recall`, `compare_with_expected_evidence`, `compute_reproduction_status` e `write_reproduction_report`. Isso permite que um orquestrador (por exemplo, Airflow no futuro) as encadeie sem estado de kernel.

O dataset não é versionado (licença da fonte). O motor lê `dataset_identity.atlas_local_path` (em `data/`, gitignored) e só executa se SHA-256 e tamanho baterem com o contrato.

## 3. Contrato científico (`scientific-study-contract.v1`)

Seções: `study_identity`, `source_repository` (URL, commit, arquivos pinados com SHA-256), `dataset_identity`, `scientific_environment`, `problem`, `features`, `preparation`, `split`, `preprocessing`, `cross_validation`, `metrics`, `baseline`, `candidates` (família, parâmetros fixos, escala numérica, busca e espaço), `search_execution`, `selection`, `threshold_policy`, `final_evaluation`, `tolerance_policy`, `expected_evidence`, `evidence_gaps`, `study_observations`, `limitations` e `authoring`.

- **Imutável por revisão.** O caminho é `pipeline/scientific-studies/<slug>/study-<commit[:12]>/`. O loader rejeita um contrato fora desse local ou com rótulo que não bata com o commit. Uma revisão nova do estudo gera um diretório novo, nunca uma edição.
- **Composição por referência.** O contrato referencia arquivos do estudo por caminho e hash e não copia notebooks, locks nem artefatos.
- **Evidência localizável.** Cada valor esperado tem `source.path` e um `locator`: `notebook_cell_output:<n>` ou `file_text` (texto renderizado), ou `json_pointer:/…` (valor em artefato JSON estruturado). `verify_against_study_checkout` confere commit, hashes pinados e todos os locators e devolve `synchronized`, `revision_differs_but_pinned_content_unchanged` ou `study_revision_drift`. O caminho absoluto do checkout nunca é gravado.
- **Tolerância declarada antes da primeira execução.** Para o Telco: `numeric_absolute = 1e-4` (duas ordens de grandeza abaixo da tolerância de empate prático do próprio estudo, 0,01) e contagens exatas. Valores publicados com N casas também aceitam meia unidade da precisão reportada, com o tier registrado.

### Contrato v2 (binário e multiclasse)

`scientific-study-contract.v2` não torna campos opcionais indiscriminadamente. Ele usa regras condicionais por `problem_type`:

| Conceito | `binary_classification` | `multiclass_classification` |
|---|---|---|
| `problem.target.positive_class` | classe obrigatória | `{"applicable": false, "reason": …}` obrigatório; `null` ou uma classe são rejeitados |
| `threshold_policy` | regra de threshold obrigatória | `{"kind": "not_applicable", "applicable": false, "reason": "multiclass_argmax_decision"}` |
| `metrics.default_threshold` | permitido | proibido |
| `problem.decision_rule` | `probability_threshold` | `argmax_class_probability` + `tie_resolution` |
| ordens de classes | — | `estimator_class_order` e `public_class_order` obrigatórias e distintas |
| vocabulário de métricas | AP, ROC-AUC, Brier, F1/F2, precisão/recall… | macro-F1, balanced accuracy, macro recall, weighted F1, accuracy, recall mínimo por classe, log loss multiclasse |

Outras novidades: membership `technical_row_occurrence` (hash da linha + ordinal de ocorrência, para fontes sem identificador), `partition_fingerprint` (SHA-256 dos bytes CSV), **gates de protocolo** (membership e número de linhas do fit final: a execução para antes de qualquer fit se a partição não coincidir), `family_shortlist`, `feature_policies` (projeções com parâmetros congelados da família), `interpretive_evidence` (pares de confusão, sensibilidade a perfis repetidos), `canonical_run` pinado, grupo `runtime_identity` (bytes da matriz de probabilidades, que nunca tornam uma reprodução divergente), `protocol_integrity` (isolamento procedimental × exposição histórica) e `protocol_parameter_sources` (parâmetros declarados reconferidos contra o artefato do estudo). `validate_contract_semantics` checa coerência entre campos: ordens de classes como permutações, políticas que excluem só features conhecidas, canonical run pinado com o mesmo hash etc.

### Contrato v3 (regressão contínua)

`scientific-study-contract.v3` é um superconjunto do v2: os ramos binário e multiclasse são os mesmos (um contrato v2 reetiquetado como v3 valida sem mudanças) e o ramo `continuous_regression` acrescenta:

| Conceito | `continuous_regression` |
|---|---|
| `problem.target` | `column`, `semantics`, `unit`, `value_representation = "float"`, `value_validation = "numeric_complete_finite"`; `classes`, `positive_class`, `encoding`, `label_representation` e as ordens de classes são **proibidos** |
| `problem.classification_concepts` | `{"applicable": false, "reason": …}` obrigatório: registro explícito de que classe, classe positiva, ordem de classes e threshold não se aplicam |
| `problem.decision_rule`, `threshold_policy`, `metrics.default_threshold` | **ausentes** (o schema rejeita) — nunca preenchidos com valores inventados |
| `split.kind` | `two_stage_random_holdout` (`train_test_split` em dois estágios, `stratify=None`, `shuffle`; seeds por estágio; `order_by_identifier = false` preserva as posições da fonte); `stratify_by` deve ser `null` |
| `cross_validation.kind` | `k_fold` (`KFold`); `stratified_k_fold` num alvo contínuo é lacuna de capacidade |
| métricas | `mae`, `rmse`, `r2`, `medae` (do registry de identidades; scorers `neg_*` do scikit-learn são só detalhe da API — o relatório usa sempre a orientação natural: MAE/RMSE/MedAE menor é melhor, R² maior é melhor) |
| `selection.practical_tie.bound` | `leader_plus_tolerance` reproduz `valor <= melhor + tolerância` exatamente como o estudo o calcula em float; o padrão histórico continua `absolute_difference` (`abs(líder − outro) <= tolerância`). As duas formas podem divergir na fronteira (`abs(2.1 − 2.0) > 0.1`, mas `2.1 <= 2.0 + 0.1`), por isso o contrato declara qual reproduz |
| `interpretive_evidence.group_overlap_diagnostic` | diagnóstico **descritivo**: divide o erro de uma predição já feita por "grupo visto / não visto" nas partições de ajuste (colunas de grupo declaradas). Roda depois da avaliação única de teste e nunca alimenta split, busca, seleção ou ajuste |

O adapter `ContinuousRegressionTask` valida o alvo (numérico, completo, finito, mantido em float64), calcula MAE, RMSE, R², MedAE e diagnósticos agregados de resíduo (média, desvio padrão com `ddof=1`, erro absoluto máximo, percentis 50/90/95 do erro absoluto) sem persistir predições linha a linha, reajusta o pipeline congelado em train + validation e prediz o teste exatamente uma vez. Relatórios v3 registram `positive_class`, `class_order` e threshold como não aplicáveis em todo `metric_set`. A família `ridge` (`sklearn.linear_model.Ridge`) existe só para a reprodução científica (não é treinável nativamente nem aceita em contratos de resultado governados). `dummy_prior` identifica a família de baseline não-aprendiz; a estratégia (`prior`, `median`) é sempre a declarada em `fixed_params`.

### Contrato v4 (forecasting univariado)

`scientific-study-contract.v4` mantém o ramo tabular do v3 sem mudanças (um contrato v2/v3 reetiquetado como v4 valida igual) e acrescenta um ramo discriminado por `problem.problem_type = univariate_forecasting`, com protocolo `univariate_forecasting_expanding_window_model_selection.v1`. Ele representa o forecasting de forma nativa e **não tem** `features`, `split`, `cross_validation`, `preprocessing`, classes, classe positiva nem threshold (o schema rejeita):

| Conceito | Representação |
|---|---|
| vocabulário do estudo | `problem.study_problem_identity` preserva `time_series_forecasting` / `univariate`; a tabela única `STUDY_PROBLEM_IDENTITIES` mapeia para a capacidade Atlas `univariate_forecasting` |
| fonte temporal | `temporal_source` (`fractional_year_monthly`: `ano = floor(t)`, `mês = rint((t − ano)·12)`, tolerância declarada; nunca ordena, preenche ou embaralha) |
| partições | `temporal_protocol.development` e `final_holdout` com início, fim, observações e SHA-256 dos bytes `period,target` (`%.15g`, LF); gate antes de qualquer fit |
| backtesting | `expanding_window` com treino inicial, horizonte, passo de origem, número de folds, contagem de previsões, política de sobreposição e a agenda por fold (gate) |
| catálogo | `candidates[]`: `candidate_id`, papel (`primary_baseline`, `secondary_baseline`, `candidate`), família Atlas, nome da família no estudo, construtor, `complexity_rank`, período sazonal, `fixed_params`, estratégia multi-step e políticas |
| métricas | `mae`, `rmse`, `seasonal_mase` do registry canônico; `seasonal_mase_12` do estudo é `seasonal_mase` com `seasonal_period = 12` (parâmetro declarado no registry); diagnósticos declarados (`fold_mae_std`, janelas de horizonte) |
| falhas | `failure_policy`: tipos de erro de programação que abortam, falha de baseline aborta, falha legítima de fit/forecast (inclusive não convergência explícita) torna a especificação inelegível; o rótulo do estudo para suas falhas de guarda é declarado |
| seleção | `forecasting_pooled_metric_practical_tie`: MAE agregado menor é melhor, empate prático `≤ melhor + tolerância`, desempate lexicográfico declarado, ranking "selecionado primeiro"; sem margem sobre baseline |
| finalização | refit único no desenvolvimento, congelamento, uma previsão, holdout aberto uma vez, escala MASE do desenvolvimento completo, referência do baseline calculada depois |
| exposição do holdout | `protocol_integrity.holdout_exposure` (por exemplo `final_holdout_exploration_blind = false`, revisão do estudo) |

**Runner temporal.** `build_reproduction` escolhe `ForecastingReproduction` para um contrato de forecasting. Cada especificação é ajustada do zero em cada fold só com o histórico de treino; o vetor completo de previsões é produzido antes de qualquer alvo do fold ser lido; nenhum alvo de validação realimenta o fold; a escala do seasonal MASE vem só do histórico do fold. O holdout fica num objeto selado (`SealedHoldout`) e um guarda (`FinalizationGuard`) impõe *fit → freeze → forecast → abrir holdout → avaliar*, cada etapa uma vez. O relatório v4 traz protocolo temporal, catálogo, execução por fold (status, categoria de falha, warnings), resultados agregados, traço da seleção, fit final, previsão final, avaliação, referência do baseline, `metric_sets` com proveniência temporal, comparação, `divergence_scope` (descritivo, nunca relaxa o status), exposição do holdout, referência superada e separação de linhagens.

**Famílias.** `pipeline/model_families.py` continua a autoridade única: as famílias `seasonal_naive`, `naive_last_value`, `exponential_smoothing`, `autoreg`, `sarimax` e `deterministic_seasonal_trend_ols` registram o construtor científico e os nomes reconhecidos; `pipeline/forecasting_models.py` tem exatamente um adapter por família (testado). Só `deterministic_seasonal_trend_ols` é treinável nativamente e governada em release; as demais são apenas científicas.

**Dependência.** A reprodução de forecasting exige statsmodels, declarado como extra opcional `scientific-forecasting` no `pyproject.toml` da raiz (`statsmodels>=0.15,<0.16`). A imagem da API instala apenas `api/pyproject.toml` e não recebe statsmodels. O lock do estudo não é instalado nem fundido; sem statsmodels o ambiente é `incompatible` e a reprodução não executa.

**Autoria sem transcrição.** `python -m pipeline.scientific_study_contract author --draft … --study-checkout … --output …` preenche valores esperados, gates e hashes a partir do checkout pinado, por JSON pointer. `verify` reconfere o contrato contra o checkout.

**Probabilidades multiclasse.** A coluna *j* de `predict_proba` pertence a `estimator.classes_[j]`. `align_probabilities_to_class_order` mapeia colunas para classes por rótulo e falha se faltar classe, sobrar classe ou se a ordem ajustada diferir da declarada. O log loss é calculado depois desse mapeamento. Um teste de regressão mostra que tratar as colunas brutas como ordem pública muda o log loss.

## 4. Ambiente científico

O lock do estudo é tratado como proveniência e requisito de compatibilidade e nunca é instalado nem fundido no ambiente do Atlas. O contrato guarda Python, plataforma, pins dos pacotes centrais extraídos do `pylock.toml`, hash do lock e uma política de fronteira por componente.

| Classe | Significado |
|---|---|
| `exact` | Python, pacotes centrais e plataforma idênticos |
| `compatible` | alguma diferença dentro da fronteira declarada (padrão: mesmo major.minor); toda diferença é listada |
| `incompatible` | alguma diferença cruza a fronteira, ou falta um pacote central; a reprodução não executa por padrão |
| `unknown` | contrato sem evidência de ambiente |

## 5. Estados de reprodução

Calculados por `compute_reproduction_status`, nesta ordem:

| Status | Quando |
|---|---|
| `dataset_identity_mismatch` | os bytes do dataset não batem com o contrato |
| `atlas_capability_missing` | o protocolo tem elemento que o Atlas não executa (família, busca, seleção, threshold, métrica, hiperparâmetro…) |
| `environment_incompatible` | o ambiente cruza a fronteira declarada |
| `divergent` | algum valor fora da tolerância ou alguma decisão diferente; tem precedência sobre lacunas de evidência, então divergência nunca é mascarada |
| `insufficient_scientific_evidence` | falta valor esperado, há lacuna `blocking` ou não há evidência numérica |
| `reproduced_exact` | ambiente `exact` e tudo igual na precisão reportada |
| `reproduced_within_tolerance` | demais casos concordantes (ex.: ambiente `compatible`) |

Uma falha de gate de protocolo (membership ou linhas do fit final) produz `divergent` logo depois das checagens de dataset, capacidade e ambiente, e nenhuma etapa posterior é executada. Cada relatório v2 traz `reproduction_status.evidence_tiers`: `structural_exact`, `numeric_exact_at_reported_precision`, `numeric_within_tolerance`, `environment`, `byte_identical_runtime`, `unsupported_capabilities` e `scientific_mismatches`. Assim ficam separados "mesmo protocolo científico" e "runtime byte-idêntico". Toda métrica carrega `metric_scope` (`baseline_validation`, `family_search_cv`, `feature_policy_cv`, `candidate_validation`, `scientific_final_test`), `feature_policy`, `fit_partitions`, `class_order` e o threshold ou o registro explícito de não aplicável.

A reprodução responde ao critério de sucesso por `answer_reproduction_questions(report)`: revisão, dataset, ambiente de referência, modelos esperados e executados, espaços de busca, regra de seleção, regra de threshold, métricas esperadas e reproduzidas, deltas, tolerância, itens não suportados, status final e perguntas sem resposta (lacunas registradas).

## 6. Auditoria do Telco (estado anterior)

Estado do Atlas antes desta mudança, em relação ao protocolo do estudo na revisão `43ced1f`:

| Elemento científico | Estado anterior no Atlas |
|---|---|
| Revisão/commit do estudo | não registrado; o notebook tratava o estudo como "provenance context only" |
| Identidade do dataset | Atlas pinava apenas o CSV **preparado** (`d4ac02e9…`); nenhum hash da fonte bruta. O estudo pina `88be4b93…` (Kaggle v1, CRLF) |
| Split | **diferente**: nativo usa `random.Random(0)` por classe (70/15/15); o estudo usa `train_test_split` em dois estágios (seeds 42/43) sobre linhas ordenadas por `customerID` |
| Seed | nativo `0`; estudo `42` (split, CV, busca, estimadores) e `43` (segundo estágio) |
| Preparação TotalCharges | reproduzida (blank com `tenure==0` → `0.0`) |
| Encoding categórico | parcialmente: nativo usa `SimpleImputer(most_frequent)` + OneHot; o estudo usa OneHot direto. `SeniorCitizen` (`0`/`1`) vira coluna numérica escalada no nativo e é categórica one-hot no estudo |
| Escala numérica | diferente: nativo `standardize` com imputação por mediana; estudo passthrough para árvores e StandardScaler só na Logistic Regression |
| Famílias candidatas | **não suportado**: o estudo avalia LR, Decision Tree, Random Forest, HGB + Dummy. O nativo aceita só `fixed_configuration` HGB; `decision_tree`, `hist_gradient_boosting` (fora do modo fixo) e `dummy_prior` não existiam como famílias genéricas |
| Search spaces / CV | não suportado; apenas documentado pelos hiperparâmetros vencedores copiados |
| Métricas | parcial: nativo `roc_auc`, `f1`, `pr_auc` (= AP), `accuracy`, `log_loss`; sem Brier, F2 nem balanced accuracy; métrica primária `roc_auc` (o estudo usa AP) |
| Seleção, empate prático e desempate | não suportado no nativo; representado documentalmente nas materializações externas históricas |
| Threshold científico | representado só como valor (`0.2577…`) nas materializações externas; o nativo usa `0.5` |
| Avaliação final | nativo faz fit em train+val e uma avaliação de teste, mas em partições diferentes das do estudo |
| Ambiente/lock | nativo pina `joblib 1.5.3 / pandas 3.0.3 / sklearn 1.9.0` (API); o estudo usa `1.6.0 / 3.0.6 / 1.9.1` sob Python 3.13.13; não havia classificação de compatibilidade |
| Resultados esperados | copiados pontualmente (AP de CV/validação) em `external-fitted-model-runs`, sem proveniência de revisão |

### Gaps encontrados e tratamento

1. Não existia contrato científico pinado por revisão. **Resolvido** com `scientific-study-contract.v1` e o contrato Telco verificado como `synchronized`.
2. Faltavam as famílias Decision Tree, HGB genérico e Dummy baseline. **Resolvido** no registry genérico (`pipeline/model_families.py`).
3. Faltavam busca Grid/Randomized com StratifiedKFold, regra de seleção com empate prático ancorado no líder e política de threshold. **Resolvido** no motor, dirigido pelo contrato.
4. Faltava classificação de ambiente. **Resolvido** (`exact/compatible/incompatible/unknown`).
5. Métricas sem proveniência de linhagem. **Resolvido** para a linhagem de reprodução. A linhagem nativa mantém seu formato atual, e a visão de linhagens a rotula sem alterá-la.
6. A materialização externa histórica (`…-20260824T163122Z`) registra um empate de **2** candidatos (HGB, LR). A revisão atual do estudo reporta empate de **3** (HGB, LR, RF). É uma evidência de revisão anterior e **não foi alterada**; um teste confere que as materializações históricas continuam autoconsistentes pelos hashes que elas mesmas registram.
7. Observação sobre o estudo (sem efeito no Telco atual): `finalize_model.py` reconstrói o pipeline final com `scale_numerical=False` para qualquer família. Isso seria inconsistente se a Logistic Regression vencesse. Está registrada no contrato como `OBS-FINAL-PIPELINE-SCALING`.

### Lacunas de evidência (informacionais, registradas no contrato)

- `GAP-SPLIT-MEMBERSHIP-DIGEST`: o estudo não versiona digest de membership. O split é conferido por tamanhos e contagens de classe e corroborado pela concordância das métricas.
- `GAP-NON-SELECTED-BEST-PARAMS`: os melhores hiperparâmetros das famílias não selecionadas não aparecem nos outputs versionados.
- `GAP-STRUCTURED-ARTIFACTS-UNVERSIONED`: os artefatos JSON do estudo estão no `.gitignore`. A referência vem dos outputs executados dos notebooks (6 casas) e do README.

## 7. Resultado real da reprodução Telco

Ambiente de reprodução: CPython 3.13.12, linux-x86_64, scikit-learn 1.9.1, pandas 3.0.6, numpy 2.5.3, scipy 1.18.1, joblib 1.6.0. Classificação: **`compatible`** (patch do Python e arquitetura diferem; pacotes centrais idênticos). Verificação de fonte: **`synchronized`**. O Kaggle está bloqueado pela política de rede do ambiente de execução. Por isso o dataset veio de um espelho público (repositório IBM no GitHub, com quebras de linha LF), foi normalizado para CRLF e só foi aceito porque o SHA-256 resultante coincide exatamente com o contrato (`88be4b93…`, 977.501 bytes).

| Pergunta | Resposta |
|---|---|
| Revisão reproduzida | `43ced1fbb76f55ad156e133ee421e756b1921df1` |
| Dataset | SHA-256 `88be4b93…61358a`, verificado |
| Modelos esperados / executados | LR, DT, RF, HGB / LR, DT, RF, HGB (+ Dummy baseline) |
| Buscas | LR grid 24, DT grid 48, RF randomized 40, HGB randomized 40, todas executadas por completo |
| Seleção | elegíveis LR, DT, RF, HGB; empate prático {HGB, LR, RF}; critério decisivo `lower_validation_brier_score`; selecionado HGB com os mesmos 6 hiperparâmetros |
| Threshold | política `max_precision_subject_to_min_recall` (recall ≥ 0,80, validação) → `0.2577809673219062`, idêntico ao valor de referência |
| Comparação | 108 quantidades comparadas: 108 iguais na precisão reportada, 0 dentro só da tolerância, 0 divergentes, 0 ausentes |
| Maior delta | 4,99e-7, que é arredondamento de exibição a 6 casas. Valores em precisão total (AP de validação `0.67082102305192`, Brier `0.13320337544392163`, threshold) coincidem exatamente |
| Status | **`reproduced_within_tolerance`**; única razão: ambiente `compatible`, não `exact` |

Teste final (HGB, fit em 5.986 linhas, uma avaliação): AP 0,641283 · ROC-AUC 0,840151 · Brier 0,139422 · Log loss 0,420650. A 0,50: TP 140, FP 84, TN 692, FN 141. No threshold da política: TP 226, FP 215, TN 561, FN 55. Tudo igual ao estudo.

## 7b. Resultado real da reprodução Concrete

O estudo não versionava evidência estruturada: os artefatos ficam no `.gitignore`, as métricas de teste só aparecem com 4 casas no README e os digests de membership não existiam. O estudo ganhou `evidence/canonical-run.json` (commit `b223370e0f44`), uma projeção determinística dos artefatos persistidos de uma reexecução do zero dos Notebooks 01–04 no ambiente travado (CPython 3.12.13 + `pylock.toml`) em linux-x86_64. A execução canônica original foi em linux-aarch64. A reexecução reproduziu byte a byte o modelo (`6e6a5a97…`) e todas as decisões. O bloco `reference_verification` do manifesto lista as únicas diferenças em relação aos notebooks executados versionados: os últimos dígitos de MAE/MedAE de validação e do desvio padrão do CV-MAE do Ridge (≤ 1,4e-14).

| Pergunta | Resposta |
|---|---|
| Contrato | `pipeline/scientific-studies/concrete-compressive-strength/study-b223370e0f44/` (`verify`: `synchronized`, 15/15 arquivos, 164/164 localizadores, 34/34 parâmetros) |
| Dataset | UCI 165, SHA-256 `2f6e6320…e1be`, 48.501 bytes, 1.030 × 9, verificado (os mesmos bytes já registrados pela linhagem nativa, mas lidos apenas do `atlas_local_path` científico) |
| Split | `two_stage_random_holdout`, seeds 42/43, `stratify=None`: 721/154/155; gate de membership aprovado |
| Busca | KFold(5, shuffle, 42) só em train; Ridge 4, DT 12, RF 12, HGB 24 = 52 configurações |
| Seleção | elegíveis HGB, RF, DT, Ridge; sem empate prático; HGB com `l2_regularization=1.0, learning_rate=0.1, max_leaf_nodes=15, min_samples_leaf=10` |
| Teste final | fit em 875 linhas, uma avaliação em 155: MAE 2,5822 · RMSE 4,2104 · R² 0,9387 · MedAE 1,6363 |
| Mistura | validação 111 vistas / 43 não vistas; teste 116 / 39; descritivo, nunca usado na seleção |
| Comparação | 160 quantidades: 160 exatas (120 métricas numéricas com delta 0), 0 dentro só da tolerância, 0 divergentes, 0 ausentes |
| Ambiente | `exact` em interpretador, pacotes centrais e plataforma da evidência pinada; o lock completo não foi instalado no Atlas e `byte_identical_runtime` fica `null` |

As métricas nativas do Concrete (`release-20260820-001`, MAE de teste 2,0453) vêm de outro split e de outra seleção. Não são diretamente comparáveis, e o treino nativo não foi alterado.

## 7c. Resultado real da reprodução Nottingham

O estudo já versiona `reproducibility/canonical-run.json` (commit `79c6abccbf65`) com identidade da fonte, protocolo temporal, hashes das partições, catálogo completo, elegibilidade, métricas agregadas, finalistas, ranking, especificação selecionada, métricas finais, baseline e as 12 previsões finais. **Nenhuma mudança no estudo foi necessária.** A agenda por fold não é versionada; o contrato a deriva dos parâmetros pinados e a aplica como gate (lacuna informacional `GAP-FOLD-SCHEDULE-DERIVED`).

| Pergunta | Resposta |
|---|---|
| Contrato | `pipeline/scientific-studies/nottem/study-79c6abccbf65/` (`verify`: `synchronized`, 18/18 arquivos, 189/189 localizadores, 109/109 parâmetros, sem lacuna de capacidade) |
| Dataset | `datasets::nottem` via `get_rdataset(...).to_csv(index=False)`, SHA-256 `2908bd6f…ca8b`, 4.531 bytes, 240 × 2; lido só de `data/scientific-studies/nottem/dataset.csv` (o arquivo nativo `data/raw/nottem/dataset.csv` tem outros bytes, CRLF) |
| Protocolo | desenvolvimento 1920-01 → 1938-12 (228), holdout 1939 (12); 9 folds expanding-window (120 / 12 / 12), 108 previsões por especificação, sem sobreposição; gates de partição e agenda aprovados |
| Catálogo | as 10 especificações executadas; 9 elegíveis; `sarima_100_100_12` inelegível por não convergência explícita (`ForecastingModelSelectionError` no vocabulário do estudo) |
| Seleção | finalistas `seasonal_trend_ols`, `holt_winters_additive_no_trend`, `sarima_100_011_12`, `holt_winters_additive_damped_trend`, `holt_winters_additive_trend`; critério decisivo: seasonal MASE agregado; **`seasonal_trend_ols` selecionado de forma independente**; ranking completo idêntico |
| Final | OLS reajustado nas 228 observações, origem 1938-12, holdout avaliado uma vez: MAE 1,526584 · RMSE 1,859967 · seasonal MASE(12) 0,555495; as 12 previsões iguais ao canônico (|Δ| ≤ 1e-13) |
| Comparação | 189 quantidades: 168 exatas, 0 só dentro da tolerância, **21 fora da tolerância**, 0 ausentes |
| Ambiente | `compatible`: CPython 3.13.12 (referência 3.13.13) em linux-x86_64 (referência linux-aarch64); statsmodels 0.15.0, pandas 3.0.6, numpy 2.5.3 e scipy 1.18.1 idênticos |
| Status | **`divergent`** (a tolerância 1e-9 do próprio estudo não foi afrouxada) |

As 21 divergências ficam todas em especificações **não selecionadas** estimadas por otimizador: as métricas agregadas das três Holt-Winters (|Δ| de 1,4e-7 a 9,8e-4), de `sarima_100_011_12` (|Δ| de 1,3e-8 a 9,9e-8) e a contagem de falhas de `sarima_100_100_12` (8 folds em vez de 7). Baselines, OLS e AutoReg coincidem até ~1e-14, e nenhuma decisão muda (`divergence_scope`: seleção, evidência da especificação escolhida e evidência final concordam). Dois diagnósticos, fora do runtime do Atlas, apoiam a atribuição ao runtime numérico e não à implementação: (1) o próprio código do estudo, executado neste mesmo runtime x86_64, produz **exatamente** os valores do Atlas (inclusive as 8 falhas); (2) sob emulação linux-aarch64 (qemu-user, CPython 3.13.7), o runner do Atlas reproduz as **7** falhas do canônico, mas os valores de Holt-Winters/SARIMA mudam de novo — são sensíveis ao runtime e nenhum dos runtimes disponíveis é o de referência. A reprodução exata exige um runner linux-aarch64 real com CPython 3.13.13.

A exposição do holdout é preservada: o Notebook 01 do estudo explorou a série inteira antes de o holdout ser selado (`final_holdout_exploration_blind = false`, `REV-001`). O holdout nunca foi usado para pontuar, ajustar ou selecionar e foi avaliado uma vez, mas não é um conjunto de teste externo cego à exploração. A execução não bloqueada e superada do estudo (statsmodels 0.14.6, `old_names`) é proveniência, não alvo.

### Nottingham: linhagem científica × treino nativo

Ao contrário de Telco e Concrete, os números das duas linhagens quase coincidem: mesma geometria desenvolvimento/holdout, mesma agenda expanding-window e o modelo nativo fixo tem a forma da especificação `seasonal_trend_ols` (a implementação nativa é do Atlas; a científica executa o OLS do statsmodels). Diferenças de 4e-16 a 5e-14 nas métricas de backtest e de holdout. Mesmo assim são experimentos diferentes: o nativo **assume** a especificação (`fixed_configuration`, `model_selection_performed = false`); a reprodução **avalia as 10 especificações e a seleciona**. O antigo gate do notebook nativo que bloqueava a montagem do candidato quando as métricas nativas se afastavam de valores arredondados do estudo foi removido; a comparação científica agora é só esta linhagem.

## 8. Reprodução científica × treino nativo Atlas

| Fato | Atlas nativo (`release-20260830-001`) | Reprodução científica |
|---|---|---|
| Split | estratificado por `random.Random(0)` | dois estágios, ordenado por identificador, seeds 42/43 |
| Seleção | `fixed_configuration` (HGB congelado) | busca em 4 famílias + empate prático |
| Métrica primária | `roc_auc` | `average_precision` |
| Threshold | 0,5 (operacional, `result_semantics`) | 0,2578 (educacional, regra do estudo) |
| AP teste | 0,6768 (`pr_auc`) | 0,6413 |
| ROC-AUC teste | 0,8545 | 0,8402 |
| F1 teste a 0,5 | 0,6130 | 0,5545 |

Os hiperparâmetros do HGB nativo coincidem com os selecionados pelo estudo, mas o nativo difere em split, seed, `random_state`, pré-processamento (imputação e escala) e threshold. As métricas descrevem experimentos diferentes e não devem ser comparadas como se fossem a mesma medida. Nenhuma linhagem substitui a outra.

## 9. Avaliação preliminar dos outros estudos

| Aspecto | Dry Bean (`e3e697c`) | Concrete (`d8b4fe0`) | Nottingham (`79c6abc`, implementado — §7c) |
|---|---|---|---|
| Problema | multiclasse (7 classes) | regressão | forecasting univariado mensal |
| Python / sklearn | 3.13.13 / 1.9.0 | **3.12.13** / 1.9.0 | 3.13.13 / sem sklearn; **statsmodels 0.15.0** |
| Evidência estruturada versionada | `reproducibility/canonical-run.json` (precisão total, membership SHA por partição) | apenas README/notebooks | `reproducibility/canonical-run.json` |
| Split | dois estágios estratificado 70/15/15, seeds 42/43, membership por ocorrência de linha (sem identificador) | dois estágios **não estratificado** 70/15/15, seeds 42/43 | holdout temporal final (12 meses) + backtesting expanding-window (9 folds, h=12) |
| Famílias | HGB, LR, RF, DT (+ Dummy) | Dummy(median), **Ridge**, DT, RF, HGB (regressores) | SeasonalNaive, NaiveLast, OLS sazonal+tendência, ExponentialSmoothing, AutoReg, SARIMAX |
| Seleção | macro-F1; margem sobre Dummy 0,02; empate 0,002 → balanced accuracy, recall da pior classe, estabilidade CV, log loss, simplicidade, ID; **inclui políticas de features** | MAE (menor é melhor); empate 0,10 MPa → RMSE, MedAE, std CV-MAE, R², ID; CV `KFold` | MAE agregado (pooled) dos folds; tolerância de empate `0.05` (`practical_tie_tolerance_f`); ordem de desempate própria |
| Threshold | não se aplica (argmax) | não se aplica | não se aplica |

**Já suportado genericamente:** contrato, verificação de fonte (inclusive `json_pointer`, adicionado a partir desta auditoria), classificação de ambiente (incluindo Python 3.12 do Concrete como fronteira declarada), famílias DT/RF/HGB por tipo de tarefa, comparação, tolerância, status, relatório e linhagens. A regra de seleção já respeita a orientação da métrica (MAE e log loss são "menor é melhor") e o intervalo de CV da métrica declarada, depois de corrigido o acoplamento a AP encontrado nesta auditoria.

**Capacidade ausente (vira `atlas_capability_missing`, sem execução parcial):**

- Dry Bean: **implementado nesta evolução** (métricas multiclasse, membership por ocorrência de linha, shortlist e etapa de políticas de features). Ver [scientific-reproduction-dry-bean.md](scientific-reproduction-dry-bean.md).
- Concrete: **implementado genericamente** como capacidade `continuous_regression` (contrato v3, família `ridge`, `k_fold`, `two_stage_random_holdout`, identidade `medae`, diagnóstico de sobreposição de grupos).
- Nottingham: **implementado genericamente** como capacidade `univariate_forecasting` (contrato v4, runner temporal, adapters statsmodels e baselines ingênuos, backtesting expanding-window, holdout selado, identidade parametrizada `seasonal_mase`).

**Extensão de contrato provavelmente necessária:** `split.kind` não estratificado e temporal; `membership_kind` sem identificador; estágio de seleção de políticas de features (Dry Bean); `cross_validation.kind = k_fold` e `expanding_window_backtest`; `search.kind = none` com especificação fixa por candidato (Nottingham).

**Abstração específica por família de problema:** vocabulário de scorers e métricas por `problem_type` (binário, multiclasse, regressão, forecasting) e um executor de forecasting separado do tabular. Nada disso foi implementado especulativamente nesta tarefa.

## 10. Limitações restantes

- O protocolo tabular cobre classificação binária, multiclasse e regressão contínua (`tabular_holdout_model_selection.v1`/`.v2`); o temporal cobre forecasting univariado mensal com backtesting expanding-window (`univariate_forecasting_expanding_window_model_selection.v1`). Frequências não mensais, janelas deslizantes, intervalos de previsão e forecasting multivariado aparecem como `atlas_capability_missing`.
- Especificações estimadas por otimizador (Holt-Winters, SARIMA) são sensíveis ao runtime numérico; no Nottingham isso produz `divergent` em linux-x86_64 sem mudar nenhuma decisão.
- A regra de desempate Dry Bean do estudo é um mínimo lexicográfico, e o motor aplica os critérios em sequência. Um teste com 300 casos aleatórios confirma a equivalência. Com valores iguais a menos de 1e-12, a filtragem sequencial trata como empate o que a comparação exata do estudo distinguiria.
- A referência do Telco vem de outputs de notebook (6 casas) e do README, porque o estudo não versiona seus artefatos estruturados.
- A reprodução não é `exact`: não há runner linux-aarch64 com CPython 3.13.13 neste ambiente.
- A linhagem nativa continua sem proveniência por `metric_set` e sem hash da fonte bruta. A visão de linhagens a rotula, mas não altera artefatos nativos.
- O motor ainda não compara curvas (PR/ROC/calibração) nem as dispositions de operações adiadas do estudo.

## 11. Próximos passos recomendados

1. Nos Dataset Studies, versionar um `canonical-run.json` também no Telco (como Dry Bean e Nottingham já fazem), incluindo membership SHA e melhores hiperparâmetros por família, para que a referência deixe de depender de texto renderizado.
2. Executar a reprodução em linux-aarch64 com CPython 3.13.13 para buscar `reproduced_exact`.
3. ~~Adicionar `multiclass_classification` (Dry Bean)~~, ~~`continuous_regression` (Concrete)~~ e ~~`univariate_forecasting` (Nottingham)~~: feitos. Para o Nottingham, reexecutar num runner linux-aarch64 real com CPython 3.13.13 para separar de vez a sensibilidade de plataforma.
4. Pinar o SHA-256 da fonte bruta também na linhagem nativa e dar proveniência de linhagem às métricas nativas em uma versão nova de schema, sem reescrever artefatos antigos.
5. Orquestrar as etapas do motor (já funções determinísticas com entradas e saídas JSON) quando o Airflow for introduzido.
