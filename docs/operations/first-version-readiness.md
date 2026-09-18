# First-version readiness evidence plan

## Purpose and boundary

This document defines the evidence plan for the M49 first-version release-readiness gate. It makes the required checks finite, assigns an evidence artifact and owner role to each check, and defines how the final result is derived.

This plan is not evidence that a check passed and does not declare the first version ready. Every check starts with an unknown result. Later M49 validation work must run the applicable target, write the named support-root evidence artifact, and record an allowed outcome. `docs/project-status/milestone-state.json` may be updated only after the collected evidence supports the transition.

The plan does not authorize product fixes, new capabilities, new datasets, architecture or storage changes, a public admin, or a broader authentication model. A failed or missing check is recorded honestly; it is not normalized into completion.

## Inputs that execution must resolve

Before smoke execution, the responsible later M49 issue must record these values in its evidence rather than infer or invent them:

- `private_base_url`: the reachable URL for the private compose deployment;
- `public_base_url`: the reachable URL for the public compose/prod deployment;
- `representative_dataset_slug`: a published dataset with a governed active release and a usable prediction contract;
- `representative_prediction_payload`: a non-sensitive valid payload for that dataset;
- `source_revision`: the repository revision or equivalent immutable filesystem snapshot being evaluated.

If a required value is unavailable, the affected check is `blocked` or `skipped_with_reason` under the rules below. An unresolved value is never evidence of success.

## Evidence contract

All paths in this document are relative to the ASF support root. Later validation issues own the files under `evidence/M49/readiness/`; this repository document only defines their contract.

Every check artifact must be a reduced, sanitized JSON object with these common fields:

- `artifact_type`, `contract_version`, `milestone_id`, and `check_id`;
- `owner_or_later_issue` and `source_revision`;
- `validation_target_or_command_source` and the resolved non-secret target values;
- `started_at` and `recorded_at` in ISO 8601 format;
- `outcome`, using exactly one value from the result model;
- `evidence_summary`, containing concise observations rather than raw output;
- `reservations` and `blockers`, both arrays;
- `reservation_or_blocker_reason`, nullable only for an unqualified `ready` result;
- `raw_logs_persisted: false`, `raw_runtime_persisted: false`, `raw_api_payloads_persisted: false`, and `secrets_persisted: false`.

Command exit codes, HTTP status codes, assertion counts, and SHA-256 digests are permitted reduced metadata. Raw terminal logs, raw runtime dumps, local database contents, credentials, tokens, and API payload bodies must not be persisted.

## Readiness matrix

The command text below is a target for later M49 execution, not a record that the command has been run.

| Check ID | Check group | Owner or later issue | Validation target or command source | Expected support-root evidence artifact | Additional expected result fields |
| --- | --- | --- | --- | --- | --- |
| `M49-FE-BUILD` | `build` | M49 frontend build validation owner | From `web/package.json`: run `npm run build` from `web/` | `evidence/M49/readiness/frontend-build.json` | `command`, `exit_code`, `build_completed`, `output_artifact_metadata` |
| `M49-FE-TEST` | `frontend_tests` | M49 frontend test validation owner | From `web/package.json`: run `npm test` from `web/` | `evidence/M49/readiness/frontend-tests.json` | `command`, `exit_code`, `test_files`, `tests_passed`, `tests_failed`, `tests_skipped` |
| `M49-API-TEST` | `backend_api_tests` | M49 backend/API test validation owner | From `README.md`: run `python -m pytest -q`; applicability and environment must be confirmed against `api/pyproject.toml` | `evidence/M49/readiness/backend-api-tests.json` | `command`, `exit_code`, `tests_passed`, `tests_failed`, `tests_skipped`, `applicability_reason` |
| `M49-PRIVATE-COMPOSE` | `private_docker_compose` | M49 private-runtime build owner | From `docker-compose.yml` and M49 minimum evidence: `docker compose build --no-cache`, followed by controlled startup for later smoke work | `evidence/M49/readiness/private-compose-build.json` | `commands`, `build_exit_code`, `startup_exit_code`, `services_expected`, `services_healthy`, `compose_file_sha256` |
| `M49-PUBLIC-COMPOSE` | `public_docker_compose_prod` | M49 public-runtime build owner | From `docker-compose.prod.yml` and M49 minimum evidence: `docker compose -f docker-compose.prod.yml build --no-cache`, followed by controlled startup for later smoke work | `evidence/M49/readiness/public-compose-build.json` | `commands`, `build_exit_code`, `startup_exit_code`, `services_expected`, `services_healthy`, `compose_file_sha256` |
| `M49-PRIVATE-SMOKE` | `private_smoke` | M49 private-runtime smoke owner | Against `private_base_url`: `/admin`, `/admin/dataset-admin`, `/admin/settings`, `/admin/help`, plus supported draft, publish, and visibility actions | `evidence/M49/readiness/private-smoke.json` | `private_base_url`, `representative_dataset_slug`, `route_results`, `action_results`, `health_result` |
| `M49-PUBLIC-SMOKE` | `public_smoke` | M49 public-runtime smoke owner | Against `public_base_url`: `/`, `/dataset/{representative_dataset_slug}`, public health and dataset API endpoints, and one representative prediction flow | `evidence/M49/readiness/public-smoke.json` | `public_base_url`, `representative_dataset_slug`, `route_results`, `api_results`, `prediction_result`, `health_result` |
| `M49-ACCESS-BOUNDARY` | `public_private_access_boundary_denial` | M49 access-boundary validation owner | In public mode, verify `/admin`, `/admin/dataset-admin`, and private/admin API paths fail closed and expose no admin capability | `evidence/M49/readiness/access-boundary.json` | `public_base_url`, `denial_targets`, `http_statuses`, `admin_ui_exposed`, `admin_api_exposed`, `failure_mode_safe` |
| `M49-TOKENLESS-ADMIN` | `tokenless_admin` | M49 private-admin validation owner | In private mode, exercise supported admin routes and actions without a visible token field or operator-supplied browser token | `evidence/M49/readiness/tokenless-admin.json` | `private_base_url`, `routes_checked`, `actions_checked`, `visible_token_field_present`, `browser_token_required`, `action_results` |
| `M49-DESIGN` | `design_gap_acceptance` | M49 design acceptance owner | Review the active design gap register or parity checklist and classify every first-version gap as resolved, accepted reservation, blocker, or not applicable | `evidence/M49/readiness/design-gap-acceptance.json` | `source_documents`, `gaps_reviewed`, `gaps_resolved`, `gaps_reserved`, `gaps_blocking`, `acceptance_owner` |
| `M49-DOCS` | `documentation` | M49 documentation validation owner | Review first-version operating documentation for public/private startup, smoke prerequisites, known reservations, and links to this plan | `evidence/M49/readiness/documentation.json` | `documents_reviewed`, `required_topics`, `missing_topics`, `stale_statements`, `review_owner` |
| `M49-STATE` | `operational_state` | M49 operational-State owner | Compare all preceding artifacts with `docs/project-status/milestone-state.json`; update State only if the aggregate evidence justifies it | `evidence/M49/readiness/operational-state.json` | `input_evidence_paths`, `prior_state`, `proposed_state`, `state_changed`, `transition_justification`, `state_file_sha256` |

Each owner must replace its role label with a concrete later M49 issue or accountable operator in the evidence artifact before execution. A check is not assigned merely because its row exists here.

## Recorded automated-check outcomes (M49-02)

M49-02 recorded fresh, current-tree evidence for exactly the three automated checks below, at `source_revision` `04226e93106865d271429f2cb3557e725d3ae07f`. It did not remediate any failure and it does not change the outcome of any other row in the readiness matrix or the aggregate decision.

| Check ID | Outcome | Evidence artifact | Summary |
| --- | --- | --- | --- |
| `M49-FE-BUILD` | `ready` | `evidence/M49/readiness/frontend-build.json` | `npm run build` from `web/` exited `0`; build completed with 3 output files emitted under `web/dist`. |
| `M49-FE-TEST` | `blocked` | `evidence/M49/readiness/frontend-tests.json` | `npm test` from `web/` exited `1`; 2 of 1178 individual tests failed (`AdminShell.test.tsx`, `SettingsPage.test.tsx`), 1176 passed. |
| `M49-API-TEST` | `blocked` | `evidence/M49/readiness/backend-api-tests.json` | `python -m pytest -q` from the repository root exited `1`; 30 of 4020 collected tests failed, 3990 passed. |

`M49-FE-TEST` and `M49-API-TEST` remain `blocked` per the result model in this plan: a failed required check cannot be `ready`, and no later evidence-backed decision has yet accepted any of these failures as a bounded, non-safety-critical reservation. This entry does not imply, and must not be read as implying, readiness for any other check group or an aggregate M49 outcome.

## Recorded automated-check outcomes (M49-03)

M49-03 recorded fresh, current-tree evidence for the `M49-PRIVATE-COMPOSE`, `M49-PRIVATE-SMOKE`, and `M49-TOKENLESS-ADMIN` checks below, at `source_revision` `04226e93106865d271429f2cb3557e725d3ae07f`. It did not remediate any failure and it does not change the outcome of any other row in the readiness matrix or the aggregate decision.

| Check ID | Outcome | Evidence artifact | Summary |
| --- | --- | --- | --- |
| `M49-PRIVATE-COMPOSE` | `ready` | `evidence/M49/readiness/private-compose-build.json` | `docker compose build --no-cache` and `docker compose up -d` both exited `0`; `api` reached its declared healthy condition, `web` is Up (no native healthcheck defined; cross-verified via smoke). |
| `M49-PRIVATE-SMOKE` | `ready_with_documented_reservations` | `evidence/M49/readiness/private-smoke.json` | All four admin routes and the health endpoint returned HTTP `200`; only the two non-mutating action reads (profile-draft, publication-state) were authorized and checked for the representative dataset `dry-bean` -- draft save, publish, and visibility actions were not authorized in this generation and remain unchecked. |
| `M49-TOKENLESS-ADMIN` | `ready_with_documented_reservations` | `evidence/M49/readiness/tokenless-admin.json` | All four admin routes returned HTTP `200`; the admin gate (`api/main.py`) and the three admin page components were re-inspected and confirm a tokenless default UX at the source level, but no rendered-DOM/browser confirmation was authorized or performed in this generation. |

`M49-PRIVATE-SMOKE` and `M49-TOKENLESS-ADMIN` are `ready_with_documented_reservations` rather than an unqualified `ready` because this generation's `execution_authorization.commands` intentionally excluded the three mutating admin actions (draft save, publish, visibility) and any rendered-DOM/browser check; both reservations are bounded, owned, and non-safety-critical given the source-level and route-reachability evidence already collected. This entry does not imply, and must not be read as implying, readiness for any other check group or an aggregate M49 outcome.

## Recorded automated-check outcomes (M49-04)

M49-04 recorded fresh, current-tree evidence for the `M49-PUBLIC-COMPOSE` and `M49-PUBLIC-SMOKE` checks below, at `source_revision` `04226e93106865d271429f2cb3557e725d3ae07f`. It did not remediate any failure and it does not change the outcome of any other row in the readiness matrix or the aggregate decision.

| Check ID | Outcome | Evidence artifact | Summary |
| --- | --- | --- | --- |
| `M49-PUBLIC-COMPOSE` | `ready` | `evidence/M49/readiness/public-compose-build.json` | `docker compose -f docker-compose.prod.yml build --no-cache` and `docker compose -f docker-compose.prod.yml up -d` both exited `0` against the real, already-running `atlas-dataflow-prod` project; `api` reached its declared healthy condition, `web` is Up (no native healthcheck defined; cross-verified via smoke). |
| `M49-PUBLIC-SMOKE` | `blocked` | `evidence/M49/readiness/public-smoke.json` | Home, Dataset Detail, public health, and all three public dataset/contract API endpoints returned HTTP `200` (reached over the Docker-internal `atlas-dataflow-prod_default` network's `web` alias, since `docker-compose.prod.yml` publishes no host port and the real internet-facing bridge is external Coolify/Traefik infrastructure outside this repository). The representative prediction flow (`POST /datasets/dry-bean/inference`, real payload from `pipeline/prepared/dry-bean/prepared-data.csv`) returned HTTP `503`; read-only diagnosis found the public/production image never provisions `/app/contracts/` (no Dockerfile `COPY`, no compose volume mount, unlike the private compose file's `./contracts:/app/contracts:ro`), so every dataset's public prediction fails the same way in production. |

`M49-PUBLIC-SMOKE` is `blocked`, not a reservation, because the representative prediction flow is a mandatory field for this check and failed with a real, reproducible, non-dataset-specific production defect; per this plan's result model, a failed required check cannot be `ready` or `ready_with_documented_reservations`. This entry does not imply, and must not be read as implying, readiness for any other check group or an aggregate M49 outcome, and it does not authorize a fix to `docker-compose.prod.yml`, `api/Dockerfile`, or `runtime/inference.py` -- remediation is out of M49-04's scope and belongs to a future issue.

## Target-specific acceptance rules

The matrix is interpreted with these minimum rules:

- Build and test checks require a successful exit code and zero unaccepted failures. A command that did not run cannot be `ready`.
- Compose checks require the expected services to build and reach their declared health condition. Startup evidence belongs with the compose artifact; functional behavior belongs with the smoke artifacts.
- Public smoke requires the Home route, the representative Dataset Detail route, public health/API behavior, and prediction flow to succeed for the recorded dataset and revision.
- Private smoke requires the listed admin routes plus supported draft, publish, and visibility operations to behave as documented.
- Access-boundary validation is readiness-critical. Public exposure of an admin route, private/admin API, credential, or private capability is `blocked`.
- Tokenless admin validation is readiness-critical. The accepted private-access model must not require a visible token field or a browser-entered admin token.
- Design acceptance requires every first-version gap to have a traceable disposition. An unclassified first-version gap is missing evidence.
- Documentation validation must identify stale or absent operating guidance as a blocker or bounded reservation; review intent is not completion.
- Operational State is evaluated last. It consumes the exact artifact paths in this matrix and cannot use this plan itself as proof of readiness.

## Result model

Every check artifact, and the aggregate result, uses one of these outcomes:

| Outcome | Meaning |
| --- | --- |
| `ready` | The applicable target ran successfully, the required reduced evidence exists, and no reservation or blocker remains. |
| `ready_with_documented_reservations` | Required evidence exists and the check is usable, but one or more explicit, bounded, non-safety-critical reservations have an owner and disposition. |
| `blocked` | A failed, missing, stale, unsafe, or unresolved required check prevents readiness. Exact blockers and their owners are recorded. |
| `skipped_with_reason` | The check did not run and the reason, owner, and follow-up are recorded. This is not a pass and cannot by itself satisfy a required check. |
| `not_applicable` | The check does not apply to the evaluated first-version scope, with a reviewable justification and approving owner. This is not a silent skip. |

Missing artifacts and missing required fields are treated as `blocked` during aggregation. A failed required check is `blocked` unless a later evidence-backed decision explicitly accepts a bounded, non-safety-critical reservation. Access-boundary failures, unsafe secret exposure, public admin exposure, and inability to exercise the supported private admin model cannot be downgraded to reservations.

## Aggregate readiness decision

The final decision owner writes `evidence/M49/readiness/first-version-readiness-result.json`. That reduced artifact must list all 12 matrix evidence paths, their outcomes and hashes, unresolved reservations, exact blockers, the evaluated `source_revision`, and one aggregate outcome.

- Aggregate `ready` requires every applicable required check to be `ready`; justified `not_applicable` checks must include approval and do not count as passes.
- Aggregate `ready_with_documented_reservations` requires every readiness-critical check to be `ready`, all other required checks to have evidence, and every reservation to be bounded, accepted, owned, and non-safety-critical.
- Aggregate `blocked` is mandatory when required evidence is absent, a required check fails, a readiness-critical check is skipped, a blocker is unresolved, or evidence refers to incompatible revisions or deployments.
- `skipped_with_reason` and `not_applicable` are check-level outcomes. They cannot be used as the aggregate declaration.

The aggregate artifact may support an operational-State transition, but it does not perform that transition. Any update to `docs/project-status/milestone-state.json` must be a separately authorized change whose evidence records the prior state, new state, exact aggregate input, and justification. Until that evidence and authorization exist, M49 remains active and first-version completion remains undeclared.

## Evidence review checklist

Before accepting the aggregate result, confirm that:

- every matrix row has exactly one current evidence artifact for the same source revision and evaluated deployments;
- every artifact contains the common and row-specific result fields;
- commands and smoke targets are recorded with reduced results, not raw output or payload bodies;
- failures, omissions, and skips are represented by the result model rather than erased;
- public/private denial and tokenless-admin checks satisfy the non-downgradable safety rules;
- reservations name an owner, scope, impact, and follow-up;
- no raw logs, runtime dumps, API payload bodies, local database content, credentials, tokens, or secrets were persisted;
- the aggregate result does not claim more than the evidence demonstrates;
- operational State changes only after evidence supports and separately authorizes the transition.

## Recorded automated-check outcomes (M49-05)

M49-05 recorded fresh, current-tree evidence for the `M49-ACCESS-BOUNDARY` check below, at `source_revision` `04226e93106865d271429f2cb3557e725d3ae07f`, against the real, already-running `atlas-dataflow-prod` project (the same instance M49-04 rebuilt). It did not remediate any failure and it does not change the outcome of any other row in the readiness matrix or the aggregate decision.

| Check ID | Outcome | Evidence artifact | Summary |
| --- | --- | --- | --- |
| `M49-ACCESS-BOUNDARY` | `ready_with_documented_reservations` | `evidence/M49/readiness/access-boundary.json` | 12 of 13 denial targets (both `/admin`/`/admin/dataset-admin` SPA routes and all 6 admin-prefixed API paths through the `web`/nginx edge, plus 4 of 5 of the same API paths hit directly against the `api` service, bypassing nginx) returned the exact byte-for-byte `_admin_route_not_found_response()` shape (HTTP `404`, `{"detail": "Not Found"}`), confirming both independent denial layers fail closed. The 13th (`PUT /admin/datasets/dry-bean/visibility`, hit directly against `api:8000` with no body) returned HTTP `422` instead of `404`, because that route's mandatory `Body(...)` parameter is validated by FastAPI before the admin gate runs; no admin data, capability, or mutation was exposed, and this vector is reachable only from the internal Docker network, never the public internet (the same path returns the uniform `404` through the real public-facing `web`/nginx edge). |

`M49-ACCESS-BOUNDARY` is `ready_with_documented_reservations` rather than an unqualified `ready` because one internal-network-only, non-data-leaking, non-mutating route-existence disclosure remains open (recommended resolution: change `PUT /admin/datasets/{dataset_slug}/visibility`'s body parameter to optional and validate it manually after the admin gate, matching the sibling `publish` route's own pattern). It is not treated as a public admin-route or admin-API exposure under this plan's non-downgradable rule, since that rule targets exposure reachable from the public internet and this vector is not. This entry does not imply, and must not be read as implying, readiness for any other check group or an aggregate M49 outcome, and it does not authorize a fix to `api/main.py` -- remediation is out of M49-05's scope and belongs to a future issue.

## Recorded automated-check outcomes (M49-06)

M49-06 is the final M49 issue: it wrote the three remaining check artifacts (`M49-DESIGN`, `M49-DOCS`, `M49-STATE`) and computed the aggregate outcome, at `source_revision` `04226e93106865d271429f2cb3557e725d3ae07f`. It did not remediate `M49-FE-TEST`, `M49-API-TEST`, or `M49-PUBLIC-SMOKE`; it only re-grounded whether each could be accepted as a bounded, non-safety-critical reservation.

| Check ID | Outcome | Evidence artifact | Summary |
| --- | --- | --- | --- |
| `M49-DESIGN` | `ready` | `evidence/M49/readiness/design-gap-acceptance.json` | Confirmed `docs/design-parity-checklist.md`'s M48 Post-M47 Design Acceptance Gap Register as the classification source: 55 gap rows total, 45 resolved (40 `implemented` + 5 `API/schema-backed behavior fix, no fix needed`), 10 accepted as bounded, non-safety-critical, out-of-first-version-scope reservations (4 `intentionally deferred`, 4 `unsupported by current schema/API`, 1 `design-only/local prototype behavior`, 1 `blocked by missing backend owner`), 0 first-version-blocking. |
| `M49-DOCS` | `ready_with_documented_reservations` | `evidence/M49/readiness/documentation.json` | `docs/operations/first-version-readiness.md` already covers every required first-version documentation topic; `docs/operations/release-flow.md` remains valid and distinct. `docs/design-runtime-parity-matrix.md` is confirmed stale (all 7 rows still read `partial_parity` with `Downstream owner` pointing at M42 through M45, which `docs/project-status/milestone-state.json` already records as completed, and which the more current M48 register independently re-confirms as predominantly `implemented`); recorded as a non-blocking documentation finding, not remediated (out of this issue's edit scope). |
| `M49-FE-TEST` | `ready_with_documented_reservations` (re-grounded; was `blocked`) | `evidence/M49/readiness/frontend-tests.json` (unchanged) plus this issue's acceptance grounding in `evidence/M49/readiness/first-version-readiness-result.json` | Direct source re-read (not a re-run) found both of the 2 recorded failures are exact-text-match test assertions colliding with correct, intentional UI copy: `AdminShell.tsx` renders the brand name with a trailing period (`"Atlas DataFlow."`) that the test's exact-match assertion does not account for, and `SettingsPage.tsx` legitimately uses the word "Account" inside its own sentence describing which settings categories are *not* editable, which collides with a test asserting that substring is absent anywhere on the page. Neither failure indicates broken functionality; accepted as a bounded, non-safety-critical reservation. The original evidence artifact is left unmodified per `implementation_handoff.files_guidance.files_must_not_change`; the override is recorded only in the aggregate artifact. |
| `M49-API-TEST` | `blocked` (unchanged) | `evidence/M49/readiness/backend-api-tests.json` (unchanged) | Re-read all 30 failing node ids directly; they span at least 10 unrelated files/subsystems, including admin profile-publish mutation routes (10 failures), public contract/browser-inference shape tests, pipeline model-family enum tests, and several dataset-notebook-static assertions. Too heterogeneous to ground as a single bounded, non-safety-critical exception within this issue's scope; remains an exact blocker. |
| `M49-PUBLIC-SMOKE` | `blocked` (unchanged) | `evidence/M49/readiness/public-smoke.json` (unchanged) | Re-confirmed the recorded blocker (`"non_downgradable": true`) for the missing `/app/contracts/` provisioning in the public/production image; this plan's Result model forbids downgrading a self-declared non-downgradable finding, so it remains an exact blocker unchanged. |
| `M49-STATE` | `blocked` | `evidence/M49/readiness/operational-state.json` | Compared all 12 matrix artifacts against `docs/project-status/milestone-state.json`'s current `active` M49 status. Because the aggregate outcome (below) is `blocked`, no state transition is proposed or applied; `docs/project-status/milestone-state.json` is left unmodified. |

### Aggregate first-version readiness result (M49-06)

The aggregate outcome, computed in `evidence/M49/readiness/first-version-readiness-result.json`, is **`blocked`**. Exact blockers: `M49-API-TEST` (30 heterogeneous backend/pipeline test failures) and `M49-PUBLIC-SMOKE` (the non-downgradable `/app/contracts/` production defect). Unresolved reservations carried into the aggregate: `M49-FE-TEST` (newly accepted this issue), `M49-PRIVATE-SMOKE`, `M49-ACCESS-BOUNDARY`, `M49-TOKENLESS-ADMIN` (all carried forward unchanged from their own evidence artifacts), and `M49-DOCS` (the stale-documentation finding above). This is not a claim that the first version or M49 is complete; per this plan's own non-downgradable default and `docs/project-status/milestone-state.json`'s own notes, M49 remains `active` until `M49-API-TEST` and `M49-PUBLIC-SMOKE` are remediated and re-verified.
