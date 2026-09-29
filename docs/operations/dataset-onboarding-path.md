# Dataset Onboarding Path (Dataset Study to Public Profile)

This document is an operator aid describing, as a sequential narrative, how a new dataset becomes a public dataset profile. It does not replace `docs/architecture.md`'s Dataset Profile Lifecycle Definition and Main Flows, which remain the authoritative vocabulary and boundaries for draft, preview, published snapshot, and visibility state. It does not replace `docs/operations/release-flow.md`, which validates the same path as a pass/fail checklist rather than describing it as a sequence of operator actions; use that checklist alongside this document rather than in place of it.

This document is private/admin-facing only. It does not define or authorize public dataset upload or automatic discovery of datasets from arbitrary user uploads.

## Scope and Boundaries

- Every stage described below is existing, tested, `dataset_slug`-driven generic code. Onboarding a dataset of an already-supported problem type (binary classification, multiclass classification, continuous regression, univariate forecasting) requires **no dataset-specific production-code change** -- only declarative/authoring artifacts (listed below). Production code changes only when a study introduces a genuinely new capability (a new problem type, protocol kind, model family, preparation rule, or inference modality).
- Registry, release, contract, profile, snapshot, and visibility authority are preserved exactly as `docs/architecture.md` defines them; this document only narrates the order in which an operator exercises them.
- The registry currently holds `telco-customer-churn`, `dry-bean`, `concrete-compressive-strength`, and `nottem` (see `registry/datasets.json`). Historical note: the first cycle seeded Telco and Bank Marketing as examples; `contracts/bank-marketing/` and its old release remain as historical artifacts only and are not in the registry.
- This path is multi-step and operator-driven; it is not a single command or an automated pipeline.

## Artifacts a new dataset needs

- Raw data under `data/raw/<dataset_slug>...` (or acquisition through the generic `pipeline/dataset_acquisition.py` helper).
- `notebooks/datasets/<dataset_slug>/dataset_integration.ipynb` -- dataset narrative and dataset-specific scientific decisions, calling only generic pipeline capabilities (shared plumbing comes from `pipeline/notebook_support.py`; forecasting temporal preparation from `pipeline/forecasting_preparation.py`).
- Generated governed artifacts: `pipeline/evidence/<dataset_slug>/`, `pipeline/authoring/<dataset_slug>/`, `pipeline/prepared/<dataset_slug>/`, `contracts/<dataset_slug>/` (execution, runtime, public contracts and dataset context), `pipeline/training-runs/<dataset_slug>/`, `pipeline/inference-bundles/<dataset_slug>/`, `releases/candidates/<dataset_slug>/`, `publisher/runs/`.
- Optionally a scientific study contract under `pipeline/scientific-studies/<dataset_slug>/<revision>/` when the study only uses implemented reproduction protocol kinds.

## Step 1: Dataset integration notebook -- discovery, intent, preparation

The notebook verifies the Atlas-owned raw input and builds discovery evidence, semantic intent, and the preparation recipe through `pipeline.discovery_evidence`, preparation rules from the canonical vocabulary in `pipeline/preparation_rules.py`, and (for forecasting) `pipeline/forecasting_preparation.py`.

## Step 2: Contracts

`pipeline.contract_derivation.materialize_execution_contract` materializes `execution_contract.v1` (tabular) or `execution_contract.v2` (forecasting) from the reviewed modeling intent. A v1 contract **requires an explicit, approved `training_policy_intent`** (split, metrics, model families, encoding); there are no implicit default policies -- an absent policy fails closed. Identifier columns declared in the modeling intent become the contract's `ignored_columns`, which training enforces. `pipeline.derive_projections.derive` projects the runtime/public contracts and dataset context.

## Step 3: Training

`pipeline.training.materialize_training_run_from_prepared_metadata` / `train_from_paths` dispatch by contract version and result semantics. Metrics, their direction, and permutation-importance scoring follow the contract's `primary_metric` through the canonical metric identity registry (`contracts/metric-identity-registry.json`); model families are governed by `pipeline/model_families.py`.

## Step 4: Inference bundle and release candidate

`pipeline.generate_inference_bundle.materialize_governed_inference_bundle`, `pipeline.release_identity.allocate_release_id`, and `pipeline.assemble_candidate.assemble_release_candidate` produce a release candidate under `releases/candidates/<dataset_slug>/<release_id>/`.

## Step 5: Publisher validation

`publisher.validate.materialize_validation_run` validates the candidate and writes a Publisher Run (and manifest when accepted); `pipeline.validated_run.materialize_validated_run_terminal_result` records the terminal result.

## Step 6: Promotion and registry activation

The Admin promote route (`POST /admin/runs/{run_id}/promote`) promotes a validated run through `publisher/promote.py` into `releases/<release_id>/`, and `registry/update.py` updates (or creates, with `review_status` `needs_review`) the matching `dataset_slug` entry's `active_release` in `registry/datasets.json`.

## Step 7: Profile draft, snapshot, and visibility

`registry/dataset_public_profile_store.py` persists private profile drafts (exposed by `api/admin_profile_drafts.py` to the Dataset Admin screen, whose Live Preview renders them through the public components). Without a curated draft, `api/public_profile_fallback.py` generates a deterministic fallback whose headline metric is the active release's own contract primary metric. `registry/dataset_public_profile_snapshot_store.py` publishes a single snapshot per `dataset_slug` (`api/admin_profile_publish.py`), and `registry/dataset_public_profile_publication_store.py` persists visibility (`api/admin_profile_visibility.py`); a dataset with no publication record defaults to visible.

## Step 8: Public resolution

`registry/resolve.py`'s `resolve_dataset()` resolves `active_release`, the published snapshot, and its visibility state for the runtime API (`/datasets/{dataset_slug}/...`) and the public web experience, which render by problem type and result contract -- never by dataset slug.

## Automation Status

Every stage above is a distinct, operator-driven step (notebook execution, the Admin promote action, Dataset Admin curation). Fully automated dataset onboarding is a named, deferred gap; this document does not describe, design, or authorize such automation.

## Related Documents

- `docs/architecture.md` -- Dataset Profile Lifecycle Definition (state and action vocabulary) and Main Flows (system-responsibility narrative for each flow named above).
- `docs/operations/release-flow.md` -- pass/fail validation checklist covering the same path; use it to verify a release operation, not to learn the operator sequence.
