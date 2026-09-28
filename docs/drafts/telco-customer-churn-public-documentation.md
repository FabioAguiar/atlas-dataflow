**Scientific study:** [dataset-study-telco-customer-churn on GitHub](https://github.com/FabioAguiar/dataset-study-telco-customer-churn)  
**Study revision described:** `43ced1f` · independently reproduced by Atlas (see *Scientific reproduction in Atlas*)  

This dataset presents a **binary-classification** problem built from customer-account records for a telecommunications provider. The active Atlas release estimates the probability assigned to `Churn = Yes` from service, contract, billing, payment, tenure, and charge information.

The analysis is predictive rather than causal. Model outputs and exploratory associations describe patterns in the observed data; they do not establish that changing an individual feature would change a customer's future behavior or validate a retention intervention.

## Dataset overview

| Item | Value |
|---|---:|
| Customer accounts | 7,043 |
| Source columns | 21 |
| Runtime model inputs | 19 |
| Identifier excluded from modeling | `customerID` |
| Target | `Churn` |
| Positive class | `Yes` |
| Negative class | `No` |
| Positive-class prevalence | 26.54% |
| Problem type | Binary classification |
| Active Atlas model family | HistGradientBoosting |
| Active Atlas primary metric | ROC-AUC |
| Final-test ROC-AUC | **0.8545** |

Each row represents one customer account. The 19 model inputs cover customer profile, relationship tenure, phone and internet services, online services and support, contract terms, billing preferences, payment method, monthly charges, and accumulated charges.

`customerID` is excluded from model inputs, while `Churn` is used exclusively as the prediction target.

## Analytical question

The analysis asks whether the information recorded for a customer account contains predictive signal for distinguishing accounts with `Churn = Yes` from accounts with `Churn = No`.

The active release returns the probability assigned to the positive class. A separate governed decision threshold converts that probability into a binary predicted outcome.

A feature can improve class discrimination without demonstrating that changing the feature would change future churn. Observed associations and model-based importance should therefore be interpreted as predictive evidence rather than causal effects.

## Data quality and preparation

The source contains 7,043 unique customer accounts.

The principal source-quality issue identified by the companion scientific study is limited to 11 blank raw values in `TotalCharges`. All occur for zero-tenure accounts, and the scientific preparation materializes them deterministically as `0.0`. No rows are removed and no generic learned imputation rule is introduced for this correction.

The active Atlas release is trained through an Atlas-native governed pipeline and does not read the companion study's runtime artifacts.

For the active release, Atlas uses its own stratified 70% / 15% / 15% split with random seed `0`. The partition sizes match the study's, but the membership does not: the study uses a two-stage split with seeds `42` and `43`.

| Partition | Rows | Role |
|---|---:|---|
| Train | 4,930 | Initial fit |
| Validation | 1,056 | Governed validation evaluation |
| Final test | 1,057 | One-time final evaluation |
| Final fit | 5,986 | Train plus validation |

The final-test partition is not used for fitting, model selection, hyperparameter selection, or threshold selection.

The active execution contract declares one-hot categorical encoding and standardized numerical handling. The release does **not** rerun the scientific model-family search; it trains the scientifically selected HistGradientBoosting configuration as a fixed governed configuration.

## Target distribution

Full dataset (7,043 accounts):

| Churn class | Observations | Share |
|---|---:|---:|
| `No` | 5,174 | 73.46% |
| `Yes` | 1,869 | 26.54% |

The study's target-aware analysis uses the train partition only (3,622 `No` / 1,308 `Yes`, 26.53%).

Because `Churn = Yes` is the minority class, a single accuracy-like score would provide an incomplete evaluation. The scientific study therefore uses Average Precision for model selection, while the active Atlas release governs ROC-AUC as its primary release metric and exposes PR-AUC and F1 as complementary evidence.

## Key exploratory findings

The scientific study fixes the holdout before any target-aware analysis, so the figures below describe the **train partition** (4,930 accounts). They are associations in this snapshot, not causal effects.

### Contract term is strongly associated with churn

Observed churn rates differ substantially across contract categories:

| Contract | Observed churn rate |
|---|---:|
| Month-to-month | 43.15% |
| One year | 10.60% |
| Two year | 2.94% |

![Observed churn rate by contract category](https://raw.githubusercontent.com/FabioAguiar/dataset-study-telco-customer-churn/main/docs/images/contract_churn_rate_by_category.png)

Month-to-month accounts exhibit a much higher observed churn rate than accounts on longer contracts. This pattern is analytically important, but it does not demonstrate that assigning a longer contract would independently reduce churn.

### Churn is concentrated in shorter observed relationships

Across tenure deciles in the scientific study, observed churn decreases from approximately 59.5% in the shortest-tenure group (≤ 2 months) to approximately 3.5% in the longest (> 69 months).

![Observed churn rate by tenure quantile](https://raw.githubusercontent.com/FabioAguiar/dataset-study-telco-customer-churn/main/docs/images/tenure_churn_rate_by_quantile.png)

Tenure contains substantial predictive signal but is also mechanically related to how long an account has already remained active. The relationship must not be interpreted as a causal retention effect.

### Service, support, and billing variables add predictive signal

The scientific EDA identifies contract type (Cramér's V 0.417), technical support (0.345), online security (0.340), internet service (0.315), and payment method (0.308) as the strongest categorical associations with churn. These rankings were not used to select features: all 19 features are kept.

The active Atlas release provides a complementary model-based view through permutation importance scored with ROC-AUC. Its leading displayed features include `Contract`, `tenure`, `MonthlyCharges`, `InternetService`, and `TotalCharges`.

Permutation importance measures predictive dependence of the fitted model on an evaluated feature. It does not measure causal importance.

## Scientific model-selection evidence

The companion study performs the broader model search. It compares a prior-only Dummy baseline with Logistic Regression, Decision Tree, Random Forest, and HistGradientBoostingClassifier.

Average Precision is the scientific primary selection metric because `Churn = Yes` is the minority class. Candidate search uses five-fold stratified shuffled cross-validation over the training partition with random seed `42`, followed by one-time validation evaluation.

### Candidate comparison

| Model | Search | CV AP mean ± std | Validation AP | Validation ROC-AUC | Validation Brier ↓ | Result |
|---|---|---:|---:|---:|---:|---|
| HistGradientBoostingClassifier | RandomizedSearchCV | **0.6728 ± 0.0161** | **0.6708** | **0.8477** | **0.1332** | **Selected** |
| Logistic Regression | GridSearchCV | 0.6591 ± 0.0129 | 0.6688 | 0.8470 | 0.1339 | Practical-tie group |
| Random Forest | RandomizedSearchCV | 0.6659 ± 0.0123 | 0.6679 | 0.8475 | 0.1593 | Practical-tie group |
| Decision Tree | GridSearchCV | 0.6194 ± 0.0234 | 0.6134 | 0.8161 | 0.1462 | Eligible, outside the tie |
| Dummy prior | No search | — | 0.2652 | 0.5000 | 0.1948 | Baseline |

A candidate is eligible only if its validation Average Precision exceeds the Dummy baseline's by more than `0.01`. The eligible leader on validation Average Precision anchors a practical tie: every other eligible candidate within `0.01` of the leader **and** with an overlapping approximate CV interval (`mean ± 1.96 × std / √5`) joins the tie group.

HistGradientBoosting, Logistic Regression, and Random Forest form a three-way practical tie. The predefined tie-breakers are applied in order (lower validation Brier score, lower validation log loss, lower CV AP standard deviation, higher validation ROC-AUC, interpretability, complexity, stable model ID); the first one, lower validation Brier score, selects HistGradientBoosting (`0.133203` versus `0.133898` and `0.159317`).

### Candidate search configuration and hyperparameters

The scientific search policy is fixed before validation evaluation. The table shows the actual candidate spaces used by the study.

| Model | Search policy | Evaluated configurations | Hyperparameters evaluated |
|---|---|---:|---|
| Logistic Regression | GridSearchCV | 24 | `C={0.001,0.01,0.1,1,10,100}`; `l1_ratio={1.0 (L1), 0.0 (L2)}`; `class_weight={None,balanced}`; fixed `solver=liblinear`, `max_iter=2000`, `random_state=42`; numerical `StandardScaler` |
| Decision Tree | GridSearchCV | 48 | `criterion={gini,entropy}`; `max_depth={3,5,8,None}`; `min_samples_leaf={1,10,30}`; `class_weight={None,balanced}`; fixed `random_state=42` |
| Random Forest | RandomizedSearchCV | 40 | `n_estimators={300,500,800}`; `max_depth={None,8,12,20}`; `min_samples_split={2,10,20}`; `min_samples_leaf={1,2,5,10}`; `max_features={sqrt,0.5,None}`; `class_weight={None,balanced,balanced_subsample}`; fixed `random_state=42` |
| HistGradientBoosting | RandomizedSearchCV | 40 | `learning_rate={0.03,0.05,0.1,0.2}`; `max_iter={100,200,400}`; `max_leaf_nodes={7,15,31,63}`; `max_depth={None,3,5,8}`; `min_samples_leaf={10,20,40}`; `l2_regularization={0,0.01,0.1,1,10}`; fixed `random_state=42` |
| Dummy prior | No search | 1 | `strategy=prior` |

The selected scientific configuration is:

| Hyperparameter | Selected value |
|---|---:|
| `learning_rate` | 0.03 |
| `max_iter` | 200 |
| `max_depth` | 3 |
| `max_leaf_nodes` | 7 |
| `min_samples_leaf` | 40 |
| `l2_regularization` | 1.0 |

## Scientific final evaluation

After model and threshold selection are frozen, the study fits the selected pipeline once on train + validation (5,986 rows) and evaluates it once on its own test partition (1,057 rows):

| Metric | Validation | Final test |
|---|---:|---:|
| Average Precision | 0.6708 | **0.6413** |
| ROC-AUC | 0.8477 | **0.8402** |
| Brier score ↓ | 0.1332 | **0.1394** |
| Log loss ↓ | 0.4135 | **0.4207** |

The study also selects an **educational** threshold on validation only: the highest precision subject to validation recall ≥ `0.80`, which gives `0.2578`. On the study's test partition it yields precision 51.25% and recall 80.43% (versus 62.50% and 49.82% at `0.5`). It is an educational decision rule, not a business-optimal operating point, and it is **not** the threshold used by the Atlas release.

## Scientific reproduction in Atlas

Atlas pins this study revision in a versioned scientific study contract and re-executes the protocol independently, from the hash-verified source file (SHA-256 `88be4b93…`): preparation, the two-stage split, the four candidate searches (152 configurations with five-fold CV), eligibility, the three-way practical tie and its tie-breakers, the threshold policy, and the single final evaluation.

| Check | Result |
|---|---|
| Compared quantities (metrics, counts, decisions) | 108 |
| Matching the study at its reported precision | 108 |
| Outside tolerance / mismatched | 0 |
| Selected model, tie group, hyperparameters, threshold | identical |
| Reproduction status | `reproduced_within_tolerance` |

The status is *within tolerance* rather than *exact* only because the runtime differs slightly from the study's (Python patch version and CPU architecture); the scientific packages are identical. The reproduction is a separate evidence line: it verifies the scientific study and does not produce or replace the active release.

## Active Atlas fixed configuration

The release does not repeat the scientific model search. The active execution contract fixes the `hist_gradient_boosting` family and reproduces the selected configuration under Atlas-native governance:

| Hyperparameter | Active release value |
|---|---:|
| `class_weight` | `None` |
| `learning_rate` | 0.03 |
| `max_iter` | 200 |
| `max_depth` | 3 |
| `max_leaf_nodes` | 7 |
| `min_samples_leaf` | 40 |
| `l2_regularization` | 1.0 |

This separation is intentional: the companion study owns the scientific comparison, while Atlas owns the release-bound fixed training, evaluation, bundle, runtime, and presentation contracts.

## Active Atlas evaluation

The following metrics come from the active Atlas release, not from the companion study's final holdout. They are measured on a different test partition (Atlas split, seed `0`) and at the release's own threshold, so they are not directly comparable with the scientific results above:

| Metric | Validation | Final test |
|---|---:|---:|
| ROC-AUC | 0.8385 | **0.8545** |
| PR-AUC | 0.6517 | **0.6768** |
| F1 | 0.5702 | **0.6130** |

The final-test evaluation contains 1,057 customer accounts and is executed once. Release evidence records that final test is not used for fitting, model selection, hyperparameter selection, or threshold selection.

### ROC-AUC — 0.8545

ROC-AUC measures ranking discrimination across possible decision thresholds. The active release governs it as the primary evaluation metric.

### PR-AUC — 0.6768

PR-AUC summarizes the precision-recall trade-off for `Churn = Yes` and is especially informative because the positive class is less frequent.

### F1 — 0.6130

F1 combines precision and recall at the release's governed decision threshold. Unlike ROC-AUC and PR-AUC, it depends on the classification threshold.

These metrics describe performance within the current release contract. They do not establish prospective production performance, intervention effectiveness, or economic value.

## Prediction and result interpretation

For each customer account, the active release estimates the probability assigned to:

`Churn = Yes`

The governed binary decision threshold is:

`0.5`

Predicted probabilities are also summarized into descriptive risk bands:

| Probability | Interpretation |
|---|---|
| `0.00 ≤ p < 0.35` | Low churn risk |
| `0.35 ≤ p < 0.65` | Medium churn risk |
| `0.65 ≤ p ≤ 1.00` | High churn risk |

The risk band and binary outcome answer different questions. The band summarizes the location of the probability on a descriptive scale; the binary prediction depends specifically on whether the probability crosses `0.5`.

A probability is a model estimate conditional on the supplied account characteristics. It is not:

- a causal explanation for churn;
- a guarantee that churn will occur;
- proof that an individual customer should receive an intervention;
- evidence that changing a particular input will alter the outcome.

## What this dataset demonstrates

The dataset provides a compact but technically rich example of tabular binary classification with:

- mixed numerical and categorical features;
- moderate target imbalance;
- explicit positive-class semantics;
- stratified train-validation-test evaluation;
- scientific comparison of linear, tree, ensemble, and gradient-boosting families;
- explicit hyperparameter-search contracts;
- threshold-independent and threshold-dependent metrics;
- probability-based predictions;
- model-based feature-importance evidence;
- observational associations that remain distinct from causal claims.

It also shows why model evaluation should not be reduced to one score: Average Precision is useful for scientific selection under class imbalance, ROC-AUC summarizes overall ranking discrimination, PR-AUC emphasizes positive-class retrieval, and F1 characterizes the precision-recall balance at a specific threshold.

## Limitations

- The evaluation uses stratified random snapshots rather than a temporal or prospective holdout, so temporal generalization is not established.
- External representativeness of the dataset is not established.
- Future distribution stability has not been evaluated.
- Production availability, latency, and consistency of all 19 inputs are not established.
- The `0.5` Atlas threshold is a governed classification rule, not a demonstrated business-optimal retention threshold.
- False-positive and false-negative business costs are not incorporated into the reported release evaluation.
- Customer value, campaign capacity, intervention cost, and expected economic benefit are not modeled.
- The available evaluation does not establish production-grade probability calibration.
- No intervention-uplift study shows that acting on high predicted churn probability improves retention.
- No subgroup fairness assessment is established.
- Deployment stability across populations or time periods has not been demonstrated.
- No drift-monitoring or scheduled-retraining policy is evaluated here.
- Feature importance and exploratory associations must not be interpreted as causal effects.
- A superseded version of the study ran target-aware EDA on the full dataset, including today's test rows; the scientific test result is a procedurally isolated random-holdout estimate, not an estimate from data never seen by the author.
- Operations the study left out of scope (TotalCharges log1p, scaler comparison, tenure/TotalCharges ablation, engineered interactions) were not evaluated.
- The scientific reproduction confirms that Atlas executes the study's protocol and obtains the same results; it does not extend the study's validity beyond its own random-snapshot scope.
- The evaluation does not establish the safety or effectiveness of automated customer-retention decisions.

## Responsible interpretation

The evidence demonstrates useful predictive discrimination for identifying accounts whose observed characteristics resemble patterns associated with `Churn = Yes`.

The scientific study shows that several model families perform substantially above a prior-only baseline and that HistGradientBoosting, Logistic Regression, and Random Forest are practically tied on the primary scientific selection metric. HistGradientBoosting is selected through the predefined Brier-score tie-break; Atlas independently reproduces that decision, and the release trains the chosen configuration as a fixed governed model rather than searching again.

Contract term, tenure, charges, internet service, and related service variables contain substantial predictive signal within this dataset. Neither the model nor the exploratory analysis demonstrates that changing those variables would cause churn probability to decrease.

Any operational retention strategy would require additional prospective validation, production-feature verification, cost-sensitive decision analysis, calibration assessment, fairness evaluation, monitoring for distribution shift, and evidence that interventions informed by the predictions produce beneficial outcomes.
