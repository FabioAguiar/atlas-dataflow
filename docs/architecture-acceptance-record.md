# Architecture Acceptance Record — M29-03

## Decision

**Outcome: Accepted as-is. No edits to `docs/architecture.md` are required.**

The already-drafted `docs/architecture.md` addition — which defines the Private Administrative Web Experience, the Private Admin API / Internal Operations Layer, and the Dataset Profile, Dataset Profile Draft, and Published Public Snapshot concepts — was reviewed section by section to confirm that publisher rules, contracts, and runtime validation remain authoritative over the new administrative layer, and that no internal service becomes part of the public surface. The review found the drafted language already satisfies acceptance criteria 1-3 without requiring clarification edits.

This record does not authorize implementation of the private admin API, creation of profile schemas, building of any UI component, publication, branch creation, commits, pull requests, or patches. It only records that the review was performed and accepted.

---

## Section-by-Section Review

### Private Administrative Web Experience and Private Admin API

`docs/architecture.md` (Private Administrative Web Experience, lines 229-233) scopes the private admin surface to the Dashboard, Dataset Admin, Settings, and Help screens, and states it "must remain outside the public surface and must not become the authority for contracts, models, validations, or publication rules." The Private Admin API / Internal Operations Layer (lines 235-239) scopes controlled operations to run listing, run promotion, draft management, preview data, publication, visibility, settings, and help content, and states it "must remain private and must not expose internal paths, secrets, raw logs, or unrestricted filesystem access." The corresponding responsibilities sections (lines 383-401 and 403-413) reiterate the same scope and require the API layer to "call or reuse publisher/profile logic" rather than duplicate it.

### Dataset Profile, Dataset Profile Draft, and Published Public Snapshot

`docs/architecture.md` (lines 181-197) defines the Public Dataset Profile as presentation-oriented configuration that "must not replace the runtime contract, model, metrics, or release manifest as technical sources of truth," the Dataset Profile Draft as editable administrative state that "must not automatically change the public experience," and the Published Public Snapshot as the versioned public presentation state that the public surface actually consumes. None of the three concepts is defined as a source of technical truth.

### Publisher/contract/runtime-validation authority preserved

`docs/architecture.md` line 215 states: "Future admin operations must call or reuse this logic rather than duplicating publication rules." The Publisher vs Private Administration boundary (line 505) states: "Private administration must only orchestrate or trigger operations already available in publisher/profile logic. It must not duplicate publication rules." The Accepted Current-Cycle Architectural Decisions restate this at line 944 ("Public dataset profiles may curate presentation metadata, but must not redefine contract, model, metrics, or inference semantics.") and line 956 ("Private administration must orchestrate existing publisher/profile operations instead of duplicating publication logic."). Publisher, contract, and runtime-validation authority is preserved.

### No internal service exposed publicly

`docs/architecture.md`'s Security section (lines 744-760) requires "no public endpoints for training, upload, run discovery, draft state, publication, or administration," "internal services outside the public internet," "no admin route forwarded from the public HTTPS server block," and "no public port mapping or public DNS entry for admin." The Accepted Current-Cycle Architectural Decisions restate this at lines 958 and 960: internal tooling, publisher operations, generated runs, draft states, pipeline work, sensitive logs, operational tools, and private administration remain outside the public surface. No internal service is exposed as part of the public surface.

### Cross-check against docs/vision.md (M29-02) and docs/milestones.md M29

The already-accepted `docs/vision.md` reauthorization (see `docs/vision-acceptance-record.md`, M29-02) scopes the same four private admin screens (Dashboard, Dataset Admin, Settings limited to display-name, Help) and the same out-of-scope boundary (no marketplace, public upload, multi-tenant, complex authentication). No contradiction was found between the two documents. `docs/milestones.md`'s M29 Expected Deliverables (line 3830) requires "Updated `docs/architecture.md` authorizing private admin and profile/snapshot boundaries," which the reviewed content satisfies through the sections cited above.

---

## Acceptance Criteria Check

- [x] The Private Administrative Web Experience and Private Admin API sections have been reviewed.
- [x] The Dataset Profile, Draft, and Published Public Snapshot definitions have been reviewed.
- [x] The review confirms publisher/contract/runtime validation remain authoritative.
- [x] The review confirms no internal service is exposed as part of the public surface.

## Architectural Boundary Confirmed vs. Pending Security Mechanism

This review confirms the **architectural boundary** — that no internal service and no admin route are exposed on the public surface — is satisfied now, as documented above.

This review does **not** resolve the **concrete private-access security mechanism**. `docs/architecture.md`'s own Gaps and Pending Decisions section (line 979) still reads: "define the minimum privacy/security mechanism required before the administrative surface can be considered private" (for example, a localhost-bound service, an SSH tunnel, an internal network, or an equivalent control). This is a pre-existing, explicitly acknowledged gap in the reviewed document, not an ambiguity introduced by this review, and it remains flagged as a distinct future decision outside M29-03's scope. This record does not select or invent a mechanism.

## Working-Tree State Note

`docs/architecture.md`, `docs/vision.md`, `docs/milestones.md`, and `docs/project-status/milestone-state.json` are committed in the target repository (commit `f4336d4`, "docs(vision): record acceptance of vision.md reauthorization update"), together with `docs/vision-acceptance-record.md` and `docs/design-interpretation.md`. At the time of this M29-03 review, the target repository's working tree is clean; no further commit of those documents is pending as a consequence of this issue.

## Boundary Statement

This acceptance record does not authorize implementation of the private admin API, creation of profile schemas, or building of any UI component. It does not authorize publication, branch creation, commits, pull requests, or patches beyond this single file. It does not resolve the still-pending private-access security mechanism decision (line 979). It records only that the review was performed and the reviewed `docs/architecture.md` content is accepted without requiring edits.
