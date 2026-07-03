# Dataset Onboarding Path (Run to Public Profile)

This document is an operator aid describing, as a sequential narrative, how a generated run becomes a public dataset profile. It does not replace `docs/architecture.md`'s Dataset Profile Lifecycle Definition and Main Flows, which remain the authoritative vocabulary and boundaries for draft, preview, published snapshot, and visibility state. It does not replace `docs/operations/release-flow.md`, which validates the same path as a pass/fail checklist rather than describing it as a sequence of operator actions; use that checklist alongside this document rather than in place of it.

This document is private/admin-facing only. It does not define or authorize public dataset upload or automatic discovery of datasets from arbitrary user uploads.

## Scope and Boundaries

- Every stage described below is existing, tested, `dataset_slug`-driven code; this document does not introduce new behavior.
- The registration mechanism has no fixture-only code path. Telco and Bank remain in the registry only as seeded example datasets, per `docs/architecture.md`'s "Seeded Examples vs Product Model" boundary; this document does not re-derive that classification.
- Registry, release, contract, profile, snapshot, and visibility authority are preserved exactly as `docs/architecture.md` defines them; this document only narrates the order in which an operator exercises them.
- This path is currently multi-step and operator-driven; it is not a single command or an automated pipeline.

## Step 1: Build the release candidate

`pipeline/build.py` validates a source-contract-input and produces a release candidate.

## Step 2: Promote the candidate

`publisher/promote.py`'s `run()` gates promotion on the candidate's `validation-result.json` reporting `promotion_gate.promotion_allowed: true`, then copies the candidate's artifacts into `releases/{release_id}/` and writes `promotion-result.json`. This step does not read or write `registry/datasets.json` and exposes no HTTP endpoint.

## Step 3: Activate the release in the registry

`registry/update.py`'s `run()` reads a promotion result and updates (or creates) the matching `dataset_slug` entry's `active_release` in `registry/datasets.json`.

## Step 4: Save a profile draft

`registry/dataset_public_profile_store.py`'s `create_draft`/`update_draft`/`get_draft` persist private, editable profile curation state per `dataset_slug`, validated against `contracts/dataset-public-profile.schema.json` before any write. `api/admin_profile_drafts.py` exposes this privately to the Dataset Admin screen. The Dataset Admin Live Preview tab renders this draft state through the same components the public experience uses, without publishing or exposing it.

## Step 5: Publish a snapshot

`registry/dataset_public_profile_snapshot_store.py`'s `publish_snapshot`/`get_snapshot` validate the current draft against the dataset's active release and create a single deterministic published profile snapshot per `dataset_slug`. `api/admin_profile_publish.py` exposes this privately to the Dataset Admin Publishing tab. Publishing a snapshot does not by itself change public visibility.

## Step 6: Set visibility

`registry/dataset_public_profile_publication_store.py`'s `get_visibility`/`set_visibility` persist a publication record per `dataset_slug`, decoupled from and never mutating `registry/datasets.json`'s legacy per-dataset `visibility` field. A dataset with no publication record yet defaults to visible. `api/admin_profile_visibility.py` exposes this privately to the Dataset Admin Publishing tab.

## Step 7: Public resolution

`registry/resolve.py`'s `resolve_dataset()` is the public-facing registry resolution entry point consumed by the runtime API and public web experience; it resolves `active_release`, the published snapshot, and its visibility state to serve the public dataset profile.

## Automation Status

Every stage above is currently a distinct, manually operated step (a pipeline command, a promotion command, a registry-update command, or a Dataset Admin UI action). Fully automated dataset onboarding — a single command or orchestration script that performs all seven steps — is a named, deferred gap and may require later milestones. This document does not describe, design, or authorize such automation.

## Related Documents

- `docs/architecture.md` — Dataset Profile Lifecycle Definition (state and action vocabulary) and Main Flows (system-responsibility narrative for each flow named above).
- `docs/operations/release-flow.md` — pass/fail validation checklist covering the same path; use it to verify a release operation, not to learn the operator sequence.
