# Admin Decision Record — M20

## Decision

**Outcome: Defer private internal administration again.**

Private internal administration is deferred beyond M20. No admin surface is created or partially created at this time.

This decision is based on a review of current operational evidence conducted as part of milestone M20, which re-evaluated the admin deferral recorded in M10.

---

## Operational Task Inventory

The following operational tasks exist in the current system. Each task is classified by the responsibility that should own it.

### Publisher responsibilities (owned by `publisher/`)

| Task | Current mechanism | Admin value |
|------|------------------|-------------|
| Validate release candidate | `publisher/validate.py` — CLI script with evidence recording | None — publisher CLI is the correct owner |
| Generate release manifest | `publisher/manifest.py` | None — tooling is direct and correct |
| Promote validated release | `publisher/promote.py` — explicit, records promotion evidence | None — promotion must remain an explicit controlled operation |
| Record publisher run evidence | `publisher/evidence.py` | None — evidence is file-based and inspectable |

Two publisher validation runs are on record (`validate-20260619T213122Z`, `validate-20260621T012527Z`). The publisher promotion flow has produced two published releases without requiring an admin surface.

### Pipeline responsibilities (owned by `pipeline/`)

| Task | Current mechanism | Admin value |
|------|------------------|-------------|
| Build pipeline artifacts | `pipeline/build.py` | None — pipeline is a data science workflow, not an admin concern |
| Assemble release candidate | `pipeline/assemble_candidate.py` | None — candidate assembly is pipeline logic |
| Derive contracts | `pipeline/contract_derivation.py` | None — contract derivation is a pipeline output |

### Registry responsibilities (owned by `registry/` and `publisher/`)

| Task | Current mechanism | Admin value |
|------|------------------|-------------|
| Declare active release per dataset | `registry/datasets.json` — explicit file | Minimal — file is readable directly; no admin inspection advantage yet |
| Manage predict views | `registry/predict-views.json` | Minimal — file-based, directly editable |
| Manage predict view customizations | `registry/predict-view-customizations.json` | Minimal — file-based, directly editable |

Two datasets are currently published: `telco-customer-churn` (active: `release-20260619-001`) and `bank-marketing` (candidate: `release-20260620-002`). This scale does not create a management burden that justifies a UI.

### Read-only inspection tasks (currently via filesystem or CLI)

| Task | Current access | Admin value |
|------|---------------|-------------|
| View release manifest | `releases/<release-id>/manifest.json` — direct file read | Low — filesystem access is sufficient at current scale |
| Review release candidate layout | `releases/candidates/<dataset>/<release>/` | Low — filesystem is sufficient |
| Query publisher run history | `publisher/runs/` | Low — two runs on record; CLI/filesystem is sufficient |
| Review promotion evidence | `publisher/promotion/` | Low — evidence files are directly readable |
| Review M12 and M15 milestone evidence | `evidence/M12/`, `evidence/M15/` | None — not an admin concern |

---

## Evidence and Assumptions Behind the Decision

### Evidence supporting deferral

1. The publisher CLI (`validate.py`, `promote.py`, `manifest.py`) is functional, explicitly controlled, and produces traceable evidence. Two releases have been promoted successfully without an admin surface.

2. The system operates with two datasets at this time. The administrative overhead of a small number of datasets does not justify adding a private web surface and its associated security complexity.

3. All operational tasks with real admin value (validate candidate, promote release, query release state) are already owned by publisher CLI. An admin surface would orchestrate these same operations — providing no new capability, only a different access mechanism.

4. Predict view definitions and customizations are managed as JSON files in `registry/`. At current scale, direct file editing is efficient and traceable.

5. The architecture principle is explicit: "Internal administration, when it exists, must orchestrate publisher operations, not duplicate logic." The publisher already provides this logic with CLI access. Adding admin now would introduce access-mechanism complexity without substantive operational gain.

6. No multi-operator scenario has been identified that would require concurrent access without SSH. Single-operator CLI workflow covers all current operational needs.

### Assumptions

- The publisher and pipeline CLI workflows will remain the authoritative operational interfaces for release management.
- New datasets will be added through the existing pipeline and publisher flow, not through an admin interface.
- The access mechanism for any future admin (SSH tunnel or private network) is not yet required because admin itself is not yet created.

---

## Boundary Notes

### Admin vs publisher responsibilities

The publisher is the authoritative owner of all publication logic: validation, hash calculation, manifest generation, promotion, and registry update. Any future admin surface must call publisher operations; it must not reimplement or duplicate them.

### Admin vs pipeline responsibilities

The pipeline owns all artifact preparation and candidate generation. Admin must not trigger pipeline runs or manage pipeline state. These remain separate responsibilities.

### Admin vs public surface

No admin functionality may be exposed on public routes. The public API (`api/`) exposes only inference, dataset metadata, contracts, metrics, and predict view data. Any future admin must operate entirely on a private surface (SSH tunnel, internal network, or equivalent).

### Registry management

Predict view definitions (`registry/predict-views.json`) and customizations (`registry/predict-view-customizations.json`) are currently managed as direct file edits. This is an area that could benefit from admin tooling as the number of datasets grows, but it does not justify admin creation at current scale.

---

## Out-of-Scope Confirmations

The following items remain explicitly out of scope and are not authorized by this decision:

- No public admin surface is created.
- No broad CRUD UI is introduced.
- No multi-user administration is introduced.
- No public upload or public retraining is introduced.
- No publisher or pipeline logic is replaced with UI.
- The decision does not authorize any follow-up implementation without an explicit future milestone issue.

---

## Conditions for Future Re-Evaluation

Admin creation should be re-evaluated (in a future milestone) when one or more of the following conditions are met:

1. **Dataset count exceeds five active datasets.** At this point, registry and release management via direct file access becomes error-prone.

2. **Multiple operators require concurrent operational access** without SSH sessions — i.e., a second legitimate operator identity needs read-only or controlled-promotion access without direct filesystem access.

3. **Predict view and customization management** grows to a complexity where direct JSON editing introduces frequent errors or version conflicts across datasets.

4. **Release promotion audit trail** requirements emerge that cannot be satisfied by the existing publisher evidence files.

5. **Security review** identifies that SSH-based direct access is inappropriate for the deployment environment and a controlled internal API is required instead.

Until at least one of these conditions is met with concrete evidence, admin should remain deferred.

---

## Follow-Up Conditions for M20 Issues

Later M20 issues must remain conditional on the outcome of this decision:

- Issues that would implement admin routes, admin UI, or admin access mechanisms are **blocked** by this deferral and must not be derived as unconditional work from M20.
- Issues that implement non-admin M20 scope (e.g., security boundary review, private access validation) are unaffected by this deferral.
- If a future milestone revisits admin, it must start with a new decision issue that cites the re-evaluation conditions above and demonstrates that at least one is met with operational evidence.

---

*Recorded as part of M20-01. This document does not authorize implementation of any admin surface. It records the evidence-based decision to defer admin beyond M20.*

---

## M20-03: Read-Only Inspection Scope Definition

This section records the read-only inspection scope for future internal admin — the specific operational records, safe fields, and ownership boundaries that any future admin inspection surface must respect. It is a planning artifact: no admin surface, admin routes, endpoints, or `apps/` directory are created in M20. Admin creation remains deferred beyond M20 per the M20-01 decision above.

### Context

M20-03 adjusts its scope from implementing inspection endpoints (which would have required an active admin surface) to documenting the inspection scope boundary. This adjustment is a direct consequence of the M20-01 deferral. The result is a recorded constraint set that any future admin milestone must treat as authoritative when building a read-only inspection surface.

### Safe Inspection Targets

The following operational records may be read by a future admin inspection surface. All other records are excluded.

| Target | File | Notes |
|--------|------|-------|
| Dataset registry | `registry/datasets.json` | Two datasets registered at scope definition time: `telco-customer-churn` and `bank-marketing` |
| Predict view customizations | `registry/predict-view-customizations.json` | One customization registered at scope definition time: `churn-risk-overview` for `telco-customer-churn` |
| Published release manifests | `releases/<release-id>/manifest.json` | Promoted releases only — see candidate boundary below |
| Publisher promotion records | `publisher/promotion/` | Evidence of release promotion history |

### Safe Field Lists

#### `registry/datasets.json` — safe fields per dataset entry

| Field | Notes |
|-------|-------|
| `dataset_slug` | Public dataset identity |
| `active_release` | Pointer to the currently promoted release |
| `public_metadata.title` | Human-readable dataset title |
| `public_metadata.summary` | Short description of the dataset |
| `public_metadata.domain` | Subject domain |
| `public_metadata.visibility` | Expected to be `"public"` for published datasets |
| `public_metadata.tags` | Classification tags |

Fields not listed here — including any internal identifiers, `$schema`, `conventions`, or other top-level registry fields — are not authorized for inspection surface display.

#### Release manifest — safe fields per `releases/<release-id>/manifest.json`

| Field | Notes |
|-------|-------|
| `dataset_identity.dataset_slug` | Links manifest to its dataset |
| `dataset_identity.dataset_title` | Human-readable title from publisher |
| `release_identity.release_id` | Unique release identifier |
| `release_identity.release_version` | Version string |
| `release_identity.created_at` | Release creation timestamp |
| `artifacts[].role` | Role of each artifact in the release |
| `artifacts[].reference` | Relative artifact path |
| `artifacts[].hash_algorithm` | Hash algorithm used (e.g., `sha256`) |
| `artifacts[].hash_value` | Derived public checksum enabling integrity verification |

Hash values (`hash_value`) are derived public checksums — they are not secrets. The manifest's own `safety_boundaries` block confirms `raw_artifact_contents_embedded: false` and `secrets_persisted: false`. Hash values enable operators to verify release integrity without requiring access to raw artifact content.

Fields not listed here — including `required_hash_coverage`, `validation_policy`, and `safety_boundaries` — are internal governance fields not required for inspection. They are owned by the publisher and must not be reproduced by any admin inspection surface.

### Release Candidate Boundary

Only release candidates that match an `active_release` entry in `registry/datasets.json` are safe to reference by ID in read-only inspection.

- **Promoted** (safe): a candidate whose ID equals the `active_release` value for its dataset in `registry/datasets.json`.
- **Unpromoted** (excluded): any candidate in `releases/candidates/` whose ID does not appear as an `active_release` in the registry.

Any future inspection implementation must cross-check a candidate ID against the registry before surfacing it. Listing all contents of `releases/candidates/` without this cross-check is not permitted. Unpromoted candidates represent intermediate publisher state not governed by promotion and must not be exposed.

### Evidence Scope Disambiguation

The term "evidence" in the M20-03 issue scope refers to **publisher-managed release evidence**: the release manifests and promotion records in `publisher/promotion/`. It does **not** refer to the raw ASF build artifacts in `evidence/M12/` or `evidence/M15/`.

The `evidence/M12/` and `evidence/M15/` directories are ASF workflow build artifacts — they record control results, router decisions, and issue iteration outcomes for the M12 and M15 milestones. They are internal workflow records, not operational state artifacts. Their admin value was assessed as None in the M20-01 review above. Exposing them through an inspection surface would leak internal workflow state and is explicitly excluded from all inspection scope.

### Publisher Ownership Boundary

Admin inspection reads publisher-governed artifacts; it does not reproduce, duplicate, or re-implement publisher logic.

Specifically:
- Inspection reads the `manifest.json` output of the publisher's promotion workflow. It does not re-run `required_hash_coverage` checks, `validation_policy` conditions, or any other publisher validation rule.
- Inspection reads `publisher/promotion/` evidence files. It does not re-execute `publisher/promote.py` logic or reproduce the promotion decision.
- Any future admin inspection surface that re-implements publisher validation creates a secondary source of truth and violates the architecture principle: "Internal administration, when it exists, must orchestrate publisher operations, not duplicate logic."

### What Is Explicitly Not In Scope for M20

The following are not authorized by this scope definition and remain deferred beyond M20:

- Building any admin inspection surface, routes, endpoints, or API views.
- Creating `apps/` directory or any admin runtime infrastructure.
- Exposing raw pipeline intermediate outputs or raw build candidates.
- Exposing raw ASF build artifacts from `evidence/M12/` or `evidence/M15/`.
- Exposing unpromoted release candidates through any inspection surface.
- Broad CRUD, write access, or mutation of registry, releases, contracts, or evidence through admin.

### Predict View Customizations — Read-Only Clarification

`registry/predict-view-customizations.json` contains a `contract_precedence` field with `canonical_contracts_are_source_of_truth: true` and `customization_defines_runtime_validation: false`. This field does not grant admin authority over customization logic — it records that canonical contracts (not view customizations) govern runtime validation. Any future inspection of this file is read-only: admin cannot modify view customizations through an inspection surface.

---

*Recorded as part of M20-03. This section does not authorize implementation of any admin inspection surface. It records the inspection scope boundary as a planning artifact for future admin creation.*

---

## M20-04: Safe Triggering Policy for Existing Publisher Operations

This section records the safe operation triggering policy for future internal admin — which existing publisher operations may be triggered from a private admin surface, the required invocation sequence, the safety conditions for each eligible operation, and the categorical exclusions. It is a planning artifact: no admin trigger infrastructure, admin routes, endpoints, or `apps/` directory are created in M20. Admin creation remains deferred beyond M20 per the M20-01 decision above.

### Context

M20-04 adjusts its scope from implementing admin trigger endpoints (which would have required an active admin surface) to documenting the safe triggering policy boundary. This adjustment is a direct consequence of the M20-01 deferral. The result is a recorded constraint set that any future admin milestone must treat as authoritative when building a controlled operation trigger surface.

M20-04 addresses write operations (validate, promote) rather than the read-only inspection scope of M20-03. The safety constraints here are stricter: promotion is an irreversible state change, and the publisher evidence audit trail must be preserved in full.

### Eligible Trigger Targets

The following publisher operations are eligible for triggering from a future private admin surface, subject to the conditions and sequence constraints below.

| Operation | CLI | Risk | Condition |
|-----------|-----|------|-----------|
| Validate release candidate | `python -m publisher.validate <candidate-directory>` | Low — read-only, no state change | Safe for direct triggering |
| Generate release manifest | `python -m publisher.manifest <validation-result-path-or-run-dir>` | Low — idempotent for unchanged artifacts | Must follow validate; must precede promote |
| Promote validated release | `python -m publisher.promote <validation-result-path-or-run-dir>` | High — irreversible artifact copy | Requires admin-layer confirmation before invocation |
| Record publication evidence | `python -m publisher.evidence <promotion-result-path-or-run-dir> '<registry-update-result-json>'` | Low — evidence recording only | Required final step; requires registry update result with `update_applied: true` |

### Required Trigger Sequence

Any admin trigger of a complete publisher publication operation must invoke all four steps in this exact order:

1. **validate** — `python -m publisher.validate <candidate-directory>`  
   Validates structural completeness of the release candidate. Exit 0 if `validation_outcome == 'accepted'`. Writes `publisher/runs/validate-{timestamp}/validation-result.json`.

2. **manifest** — `python -m publisher.manifest <validation-result-path-or-run-dir>`  
   Computes SHA-256 hashes for all 7 required artifact roles and writes `manifest.json` to the run directory. Gates on `promotion_gate.promotion_allowed: true` in the validation result. Idempotent for unchanged candidate artifacts.

3. **promote** — `python -m publisher.promote <validation-result-path-or-run-dir>`  
   Copies artifact role files into `releases/{release_id}/` and writes `promotion-result.json`. Gates on `promotion_gate.promotion_allowed: true` and requires `manifest.json` to be present in the run directory (raises `RuntimeError` if absent). Has built-in overwrite prevention: raises `RuntimeError` if `releases/{release_id}/` already exists.  
   **Admin-layer confirmation required before this step** — see safety constraint below.

4. **[registry update]** — Update `registry/datasets.json` to set `active_release` for the promoted dataset.  
   This step is not performed by any publisher CLI script in the current implementation (M11-04 boundary: `promote.py` does not modify `registry/datasets.json`). It must be completed before calling `evidence`.

5. **evidence** — `python -m publisher.evidence <promotion-result-path-or-run-dir> '<registry-update-result-json>'`  
   Builds and writes `publication-evidence.json` in the run directory. Requires a registry update result JSON argument with `update_applied: true` confirming that the `registry/datasets.json` was updated. This step is **not called automatically** by any other publisher script and must be invoked explicitly as the final step.

No step may be omitted. Omitting `evidence` produces an incomplete audit trail. Omitting the registry update step causes `evidence` to fail (`registry_update_result.update_applied` must be `true`).

### Safety Constraints

#### promote.py: Admin-layer confirmation required

`publisher/promote.py` has **no built-in dry-run or confirmation flag**. The only programmatic gate is `promotion_gate.promotion_allowed: true` in the validation result. Promotion copies artifact role files into `releases/{release_id}/` — this is an irreversible state change (an existing release directory cannot be overwritten).

Any future admin surface that exposes the promote operation **must implement its own confirmation step** at the admin layer before invoking `promote.py`. Triggering promotion from admin without such a guard is explicitly rejected by this policy.

#### evidence.py: Registry update prerequisite

`publisher/evidence.py` requires the caller to supply a `registry_update_result` JSON object as the second CLI argument. This object must include `update_applied: true`. This means the `registry/datasets.json` active release pointer must be updated (confirming the promotion is the new active release) before `evidence.py` can be called. Until registry update logic is formalized beyond the M11-04 boundary, the registry update step requires manual operator action between `promote` and `evidence`.

#### Admin must not reimplement publisher logic

Admin calls existing publisher CLI scripts as subprocesses or programmatic equivalents. Admin must never reconstruct publisher validation logic, hash calculation, manifest generation, promotion decisions, or evidence recording logic. Any admin trigger implementation that replicates publisher logic instead of calling the existing scripts violates the architecture principle recorded in the M20-01 decision above.

#### Private trigger surface only

All admin trigger operations are subject to the M20-02 private access boundary: SSH tunnel to localhost-bound Caddy server block. No publisher operation may be exposed on any public route. Admin triggering must not be reachable from the public `:443` block or any public-facing interface.

### Pipeline Operations: Categorical Exclusion

The following pipeline operations are categorically excluded from admin triggering. No exceptions are permitted.

| Script | Reason for exclusion |
|--------|---------------------|
| `pipeline/build.py` | Long-running data science workflow; not designed as an on-demand service |
| `pipeline/assemble_candidate.py` | Long-running candidate assembly; produces large intermediate artifacts |
| `pipeline/contract_derivation.py` | Long-running derivation workflow; complex file dependencies |
| `pipeline/evidence.py` | Internal pipeline evidence recorder; not a trigger boundary |

No lightweight or discrete sub-operations exist within the pipeline directory. The entire pipeline directory is excluded because pipeline operations fail the constraint: "Long fragile operations must not be run through unsafe request paths."

### What Is Explicitly Not In Scope for M20

The following are not authorized by this policy and remain deferred beyond M20:

- Building any admin trigger surface, routes, endpoints, or integration adapters.
- Creating `apps/` directory or any admin trigger runtime infrastructure.
- Exposing any pipeline operation through any trigger path.
- Creating public trigger surfaces for any publisher or pipeline operation.
- Implementing the registry update step as a governed CLI operation (deferred beyond M11-04).
- Implementing or running tests for any trigger integration.
- Creating branches, commits, pull requests, or GitHub publications.

---

*Recorded as part of M20-04. This section does not authorize implementation of any admin trigger surface. It records the safe triggering policy boundary as a planning artifact for future admin creation.*

---

## M20-05: Admin Privacy, Public Exposure, and Operation Boundary Validation

This section records the M20 completion validation for the internal administration decision, privacy model, public exposure boundary, and operational responsibilities. It validates the M20-01 through M20-04 records as a documentation and security boundary set. It does not create an admin surface, routes, endpoints, tests, deployment changes, or runtime validation artifacts.

### Validation Outcome

The M20 admin branch remains deferred. No private internal administration surface is created or partially created in M20, and no `apps/` admin runtime is introduced. Because no admin surface exists, private access behavior for an implemented admin surface is not applicable in this milestone.

The completion condition for M20 is therefore not "private admin access works"; it is that M20 records why admin remains deferred and preserves the boundaries a future admin implementation must satisfy. The recorded boundary is:

- Admin is not public.
- Admin is not implemented in M20.
- Future admin, if created, must be private-only.
- Future admin must orchestrate publisher operations instead of duplicating publisher or pipeline logic.
- Unsafe long-running pipeline operations must not be exposed through request paths.

### Public Exposure Review

M20 records no public admin capability. The decision record, read-only inspection scope, and safe triggering policy all explicitly reject public administration and do not authorize any public route, public endpoint, admin UI, `apps/` runtime, or public operation trigger.

The public exposure review for M20-05 is limited to the M20 records and authorized repository context. Within that scope, there is no M20-created admin surface to expose publicly. Public runtime and web surfaces remain governed by the existing architecture boundary: public endpoints are for dataset metadata, contracts, metrics, inference, and related public consumption only; internal services and future admin remain outside the public surface.

### Publisher and Pipeline Boundary Validation

The publisher remains the owner of release validation, manifest generation, promotion, registry update evidence, and publication evidence. Future admin may call publisher operations only as controlled operations; it must not reimplement validation rules, hash calculation, manifest generation, promotion decisions, registry evidence, or publication evidence.

The pipeline remains outside admin triggering. Pipeline build, candidate assembly, contract derivation, and pipeline evidence recording are long-running internal workflows and are categorically excluded from admin request paths.

The M20-03 inspection scope and M20-04 triggering policy preserve this separation:

- Read-only inspection may only expose selected safe fields from promoted publisher-governed artifacts.
- Unpromoted candidates, raw pipeline outputs, and ASF workflow evidence are excluded from admin inspection.
- Promotion requires admin-layer confirmation before invoking publisher promotion.
- Publication evidence remains a required final publisher evidence step after registry update.
- No pipeline operation is eligible for admin triggering.

### Security Review Record

M20-05 validates that the recorded M20 admin decision is complete for a deferred-admin milestone:

1. Admin decision evidence is present in M20-01 and records deferral beyond M20.
2. Private access validation is not applicable because no admin surface was created.
3. Public exposure review confirms that M20 creates no public admin route, endpoint, UI, or trigger surface.
4. Publisher and pipeline logic are not duplicated by admin because no admin implementation exists, and future admin is constrained to orchestrate existing publisher operations only.
5. Unsafe long-running pipeline operations are excluded from public and admin request paths.
6. Validation evidence is reduced to this decision record and does not persist secrets, raw runtime payloads, raw logs, raw API payloads, or repository file contents.

### Residual Conditions

If a future milestone creates any admin surface, completion must include fresh validation of the actual implementation:

- private access behavior through the selected private access mechanism;
- rejection of unauthorized access;
- absence of public route or deployment exposure;
- confirmation that publisher and pipeline logic are not duplicated;
- confirmation that unsafe long-running operations are not exposed through request paths;
- sanitized security and operational evidence.

Until such a future implementation exists, M20's validated state is deferred admin with documented boundaries, not an operational private admin surface.

---

*Recorded as part of M20-05. This section validates the M20 admin deferral and operational boundaries. It does not authorize implementation of any admin surface or public admin capability.*
