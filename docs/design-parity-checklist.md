# Design Parity Checklist (M42 Through M45)

M41-04 defines the finite, screen-by-screen design parity checklist that M42
through M45 must use to validate implementation completeness. This document
consolidates the M41-01 screen-to-React parity matrix
(`docs/design-runtime-parity-matrix.md`), the M41-02 prototype behavior
inventory (`docs/design-prototype-behavior-inventory.md`), and the M41-03
asset and token consolidation plan (`docs/design-asset-token-consolidation.md`)
into a single validation checklist. `docs/milestones.md` remains the M41
continuity anchor; this file carries the checklist detail.

This document does not authorize React implementation, API changes, schema
changes, publisher changes, registry changes, model changes, asset copying, or
any runtime mutation. Creating this checklist is not evidence that any M42
through M45 item is complete. Support-root paths under `design/screens/` are
UX source references only, never runtime contracts.

Every checklist item below records: the checklist item itself, its source
evidence, its React runtime owner, its validation method, its required/deferred
status, and its downstream milestone owner. Per the M41-04 operational state's
decision-05, validation methods name a behavior or boundary check wherever the
item concerns behavior or contract semantics — visual review alone is used only
for purely visual/layout concerns.

## Status Legend

| Status | Meaning |
| --- | --- |
| `required` | The downstream milestone listed must implement and/or validate this item; it is in scope for that milestone. |
| `deferred` | No safe implementation owner or schema/API support exists yet; downstream milestones must not implement this without a later authorizing decision. |
| `disabled` | The current React implementation intentionally keeps this control disabled; downstream milestones must confirm it stays disabled unless a later issue authorizes a backend owner. |
| `preview-only` | The behavior may update a local/private preview only; it must never imply real prediction, publishing, upload, or backend mutation. |

## Public Home (`/`)

| Checklist item | Source evidence | Runtime owner | Validation method | Status | Downstream owner |
| --- | --- | --- | --- | --- | --- |
| Hero, repository/portfolio actions, and featured dataset grid render data-driven from `GET /datasets` with no hardcoded upper bound on card count. | `design/screens/home/` (support-root UX reference, read-only); `web/src/pages/HomePage.test.tsx` describe block "HomePage dataset-count states" (`it("renders every card with no hardcoded upper bound for multiple published datasets")`) | `web/src/pages/HomePage.tsx`; shared cards via `web/src/components/DatasetCard/` | Behavior test: the three existing `HomePage.test.tsx` cases (zero, one, many datasets) plus a visual review against `design/screens/home/visual-spec.md`. | required | M42 |
| Empty, loading, and error states are distinct and never fabricate dataset content. | `HomePage.test.tsx` `it("renders the empty state for zero published datasets")` | `web/src/pages/HomePage.tsx` | Behavior test citing the existing empty-state case; boundary check that no placeholder dataset is rendered on error. | required | M42 |
| Curated `home_card_icon` takes precedence over the domain/tags keyword-derived icon fallback; `problem_type` label renders with a documented fallback when absent. | `HomePage.test.tsx` describe block "HomePage problem_type and curated icon rendering" (4 `it` cases: curated-icon precedence, keyword fallback, problem_type present, problem_type absent) | `web/src/pages/HomePage.tsx` | Behavior test citing the four existing cases by name. | required | M42 |
| Public navigation (desktop rail, mobile overlay, link-close-on-navigate, Escape-to-close-with-focus-return) matches the Home prototype's navigation behavior. | `design/screens/home/desktop/script.js`, `design/screens/home/mobile/script.js` (M41-02 rows: desktop rail toggle, mobile menu open/close, mobile nav-link close, Escape/focus-return) | `web/src/layouts/PublicShell.tsx` | See the PublicShell section below; this row exists to confirm Home specifically exercises the shared shell, not a page-local nav implementation. | required | M42 |

## Dataset Detail (`/dataset/:slug`)

| Checklist item | Source evidence | Runtime owner | Validation method | Status | Downstream owner |
| --- | --- | --- | --- | --- | --- |
| Detail header, metadata row, overview tab, and badge render correctly for an arbitrary synthetic dataset slug (not hardcoded to Telco/Bank fixtures). | `design/screens/dataset-detail/` (support-root UX reference); `web/src/pages/DatasetPage.test.tsx` describe block "DatasetPage synthetic-slug rendering" (`it("renders the correct title, metadata, and badge for a synthetic, non-Telco/Bank dataset_slug")`) | `web/src/pages/DatasetPage.tsx`; `web/src/components/DatasetDetail/` | Behavior test citing the existing synthetic-slug case; visual review against `design/screens/dataset-detail/visual-spec.md`. | required | M42 |
| Source and Release metadata show "Pending" when the release-context artifact has no curated values, and render the real curated values (plus the curated metric highlight) once provided (M39-03 contract). | `DatasetPage.test.tsx` `it("shows 'Pending' for Source and Release when context has no curated values (M39-03)")` and describe block "DatasetPage curated Source/Release/highlight rendering (M39-03)" | `web/src/pages/DatasetPage.tsx` | Behavior test citing both existing cases. | required | M42 |
| Tab switching (overview/inference), `aria-selected`, and visible `tabpanel` state match the prototype's tab behavior. | `design/screens/dataset-detail/desktop/script.js` (M41-02 row: "Dataset Detail tabs", classification `already implemented`) | `web/src/pages/DatasetPage.tsx`; `web/src/components/DatasetDetail/` | Behavior/accessibility check of tab state and ARIA attributes; content itself must remain data-driven from the public dataset/context/metrics/contract/model-card/predict-view APIs, not prototype-authoritative. | required | M42 |
| Dataset Detail desktop rail toggle reuses the shared PublicShell behavior rather than a page-local implementation. | `design/screens/dataset-detail/desktop/script.js` (M41-02 row: shares the Home desktop rail behavior) | `web/src/layouts/PublicShell.tsx` | Confirm via the PublicShell section below that Dataset Detail mounts the same shell component; no page-local nav code. | required | M42 |
| Inference/result presentation and predict-view list remain contract/API-driven, not prototype-authoritative. | `docs/design-runtime-parity-matrix.md` Dataset Detail row | `web/src/pages/DatasetPage.tsx`; `web/src/components/InferenceForm/`, `web/src/components/InferenceResult/` | Boundary check: inference behavior stays within the current schema/API contract; no unsupported inference semantics introduced from the prototype. | required | M42 |

## Admin Dashboard (`/admin`)

| Checklist item | Source evidence | Runtime owner | Validation method | Status | Downstream owner |
| --- | --- | --- | --- | --- | --- |
| Dashboard identity, runs-root-unavailable state, no-runs-found state, and a single-run-row rendering with status pill are all distinct. | `design/screens/dataset-admin-home/` (support-root UX reference); `web/src/pages/admin/DashboardPage.test.tsx` (`it`s: "renders the design-aligned Dashboard identity before private data is loaded", "renders the runs-root-unavailable state distinctly from an empty runs list", "renders the no-runs-found state when the runs root is available but empty", "renders exactly one run row with its status pill") | `web/src/pages/admin/DashboardPage.tsx` | Behavior test citing the four existing cases. | required | M43 |
| Search filters both runs and Dataset Details rows from the shared Dashboard search input, matching the prototype's search-filtering behavior. | `design/screens/dataset-admin-home/desktop/script.js` (M41-02 row: "Dashboard search filtering", classification `already implemented`); `DashboardPage.test.tsx` `it("filters runs and Dataset Details from the shared Dashboard search")` | `web/src/pages/admin/DashboardPage.tsx` | Behavior test citing the existing case. | required | M43 |
| Summary counters (available runs, promoted runs, published datasets, draft datasets) recompute correctly with no hardcoded upper bound, and any counter without a safe backend source is visibly unavailable rather than inferred from local DOM state. | `design/screens/dataset-admin-home/desktop/script.js` (M41-02 row: "Dashboard summary counters", classification `schema/API-backed`); `DashboardPage.test.tsx` `it("renders multiple runs with mixed statuses and no hardcoded upper bound on the counters")` | `web/src/pages/admin/DashboardPage.tsx` | Behavior test citing the existing case, plus a boundary check that unsupported counters (promotion/publication/draft, absent a safe source) remain visibly unavailable, not locally inferred. | required | M43 |
| Dataset Details table renders safe run-summary data with actions marked unavailable rather than wired to unsafe mutation. | `DashboardPage.test.tsx` `it("renders Dataset Details from safe run-summary data with unavailable actions")` | `web/src/pages/admin/DashboardPage.tsx` | Behavior test citing the existing case. | required | M43 |
| Keyboard shortcut for search (`Ctrl+K`/`Meta+K`) is added if implemented, or explicitly documented as deferred if not. | `design/screens/dataset-admin-home/desktop/script.js` (M41-02 row: "Keyboard shortcut for search", classification `implementable in React`) | `web/src/pages/admin/DashboardPage.tsx` | If implemented: a new focus-behavior test. If not implemented: document as deferred in this checklist's Deferred/Disabled section. | deferred | M43 |
| Compact desktop density (~`1360x768`): reduced sidebar width, padding, row/card spacing, and isolated horizontal overflow to table wrappers, with vertical page scroll allowed. | `docs/design-asset-token-consolidation.md` "Compact Desktop Constraints" section, Dashboard subsection | `web/src/pages/admin/DashboardPage.tsx`; `web/src/layouts/AdminShell.tsx` | Visual/responsive review at a comfortable desktop viewport and at approximately `1360x768`. | required | M43 |

## Dataset Admin (`/admin/dataset-admin`)

| Checklist item | Source evidence | Runtime owner | Validation method | Status | Downstream owner |
| --- | --- | --- | --- | --- | --- |
| Dataset selector shows a disabled state with a blank read-only panel when no datasets are registered, and populates correctly (including a synthetic non-Telco/Bank dataset) once datasets exist. | `design/screens/dataset-admin/` (support-root UX reference); `web/src/pages/admin/DatasetAdminPage.test.tsx` (`it`s: "shows a disabled selector and a blank read-only panel when no datasets are registered", "populates the filterable selector for a multi-dataset listing including a synthetic non-Telco/Bank dataset and updates the read-only panel on selection change") | `web/src/pages/admin/DatasetAdminPage.tsx` | Behavior test citing both existing cases. | required | M44 (visual structure); M45 (selector behavior) |
| Workspace tab switching across all seven tabs (public content, metadata/home-card, theme preset, inference form, result card, publishing, Live Preview) matches the prototype's tab/ARIA/panel behavior. | `design/screens/dataset-admin/desktop/script.js` (M41-02 row: "Dataset Admin main tab switching", classification `already implemented`) | `web/src/pages/admin/DatasetAdminPage.tsx` | Behavior/accessibility check of tab state, `aria-selected`, and panel visibility against the prototype. | required | M44 |
| Profile-draft save persists only schema-valid values for icon, primary metric, theme preset, and result-card fields; out-of-schema values cannot be selected or persisted. | `DatasetAdminPage.test.tsx` (`it`s: "saves a schema-valid profile-draft payload for supported icon, primary metric, theme preset, and result-card values", "cannot select or persist theme/result-card preset values outside the schema-supported set") | `web/src/pages/admin/DatasetAdminPage.tsx`; `contracts/dataset-public-profile.schema.json` | Behavior test citing both existing cases; boundary check that the schema, not the prototype's theme/preset bank, is authoritative. | required | M45 |
| Backend profile validation, publish validation, and visibility validation feedback surface without producing unintended side effects (no publish on a validation error, no visibility change on a rejected save). | `DatasetAdminPage.test.tsx` (`it`s: "surfaces backend profile validation feedback without publishing side effects", "surfaces publish validation feedback without changing visibility state", "surfaces visibility validation feedback without changing public exposure") | `web/src/pages/admin/DatasetAdminPage.tsx` | Behavior test citing the three existing cases. | required | M45 |
| Publishing lifecycle (Save Draft, Preview Draft, Publish Changes, Visible Publicly) follows backend validation states and is worded as session-local, not a release-artifact mutation. | `design/screens/dataset-admin/desktop/script.js` (M41-02 rows: "Publishing lifecycle feedback", "Visibility toggle locked until snapshot", both `schema/API-backed`); `DatasetAdminPage.test.tsx` `it("wires Publishing tab actions and derives lifecycle labels from saved, published, and visibility state")` | `web/src/pages/admin/DatasetAdminPage.tsx` | Behavior test citing the existing case; boundary check that visibility cannot toggle before a published snapshot exists and that release artifacts stay read-only from this UI. | required | M45 |
| Inference form field ordering, grouping, and drag-and-drop reorder persist only through the predict-view customization schema/contract, preserving required-field visibility and canonical contract order. | `design/screens/dataset-admin/desktop/script.js` (M41-02 rows: "Inference form field ordering and grouping builder", "Drag-and-drop field and group movement", "Group creation, edit, remove, and reorder", all `schema/API-backed`); `DatasetAdminPage.test.tsx` (`it`s: "shows pointer-following drag overlay activity for fields and groups") | `web/src/pages/admin/DatasetAdminPage.tsx`; `contracts/predict-view-customization.schema.json` | Behavior test citing the existing drag-overlay case; boundary check that required fields cannot be hidden and saved customization stays presentation-only. | required | M45 |
| Compact desktop density (~`1360x768`): all seven workspace tabs remain usable as a row (not converted to mobile nav), with reduced padding/gaps and no global horizontal overflow. | `docs/design-asset-token-consolidation.md` "Compact Desktop Constraints" section, Dataset Admin subsection | `web/src/pages/admin/DatasetAdminPage.tsx` | Visual/responsive review at a comfortable desktop viewport and at approximately `1360x768`. | required | M44 |

## PublicShell

| Checklist item | Source evidence | Runtime owner | Validation method | Status | Downstream owner |
| --- | --- | --- | --- | --- | --- |
| Nav defaults open on desktop viewports and closed on mobile viewports. | `web/src/layouts/PublicShell.test.tsx` describe block "PublicShell nav overlay responsive behavior" (`it`s: "defaults the nav open on desktop viewports", "defaults the nav closed on mobile viewports") | `web/src/layouts/PublicShell.tsx` | Behavior test citing both existing cases. | required | M42 |
| The mobile nav overlay never renders on desktop even though the nav is open by default, and renders on mobile once opened; clicking the overlay closes the nav. | `PublicShell.test.tsx` (`it`s: "does not render the nav overlay on desktop even though the nav is open by default", "renders the nav overlay on mobile once the nav is opened", "closes the nav when the mobile overlay is clicked") | `web/src/layouts/PublicShell.tsx` | Behavior test citing the three existing cases. | required | M42 |
| The existing nav item set and labels are preserved (no unintended nav content regression). | `PublicShell.test.tsx` `it("preserves the existing nav item set and labels")` | `web/src/layouts/PublicShell.tsx` | Behavior test citing the existing case. | required | M42 |
| Mobile nav closes when a side-nav link is activated. | `design/screens/home/mobile/script.js` (M41-02 row: "Mobile nav-link close", classification `implementable in React`) | `web/src/layouts/PublicShell.tsx` | New behavior test needed (not yet covered by `PublicShell.test.tsx`); not yet implemented. | deferred | M42 |
| Escape closes the mobile nav and returns focus to the menu toggle. | `design/screens/home/mobile/script.js` (M41-02 row: "Escape key close and focus return", classification `implementable in React`) | `web/src/layouts/PublicShell.tsx` | New behavior/accessibility test needed (not yet covered); not yet implemented. | deferred | M42 |
| Public navigation stays structurally and visually separate from private AdminShell navigation. | `docs/design-runtime-parity-matrix.md` PublicShell row | `web/src/layouts/PublicShell.tsx` | Boundary check: confirm no shared component conflates public and private nav state. | required | M42 |

## AdminShell

| Checklist item | Source evidence | Runtime owner | Validation method | Status | Downstream owner |
| --- | --- | --- | --- | --- | --- |
| Admin brand and navigation labels match the design-aligned reference. | `design/screens/dataset-admin-home/`, `design/screens/dataset-admin/` (support-root UX references); `web/src/layouts/AdminShell.test.tsx` `it("renders the design-aligned admin brand and navigation labels")` | `web/src/layouts/AdminShell.tsx` | Behavior test citing the existing case; visual review against the admin visual-spec references. | required | M43 |
| Profile block shows the default fallback display name before settings load, and reflects a display name set on the shared `AdminSettingsContext` without a page reload. | `AdminShell.test.tsx` (`it`s: "shows the default fallback display name before any settings are loaded", "reflects a display name set on the shared admin settings context without a page reload") | `web/src/layouts/AdminShell.tsx` | Behavior test citing both existing cases. | required | M43 |
| AdminShell does not expose misleading disabled global run or publishing controls. | `AdminShell.test.tsx` `it("does not expose misleading disabled global run or publishing controls")` | `web/src/layouts/AdminShell.tsx` | Behavior test citing the existing case. | required | M43 |
| Admin logo/brand block uses a canonical frontend asset once asset-copy is explicitly authorized; until then, the current text mark stays in place. | `docs/design-asset-token-consolidation.md` Admin Shell Token Mapping table | `web/src/layouts/AdminShell.tsx` | See the Assets and Tokens section below. | deferred | Later asset-copy issue if authorized |
| Admin navigation remains private and never implies public administration access. | `docs/design-runtime-parity-matrix.md` AdminShell row | `web/src/layouts/AdminShell.tsx` | Boundary check: confirm admin routes stay behind the existing admin route/auth boundary. | required | M43 |

## Shared Public Components (consumed by Live Preview)

| Checklist item | Source evidence | Runtime owner | Validation method | Status | Downstream owner |
| --- | --- | --- | --- | --- | --- |
| `web/src/components/DatasetCard/` is the single Home-card rendering owner for both the real public Home page and the admin Live Preview Home-card mode. | `docs/design-runtime-parity-matrix.md` "Shared public components used by Dataset Admin Live Preview" row | `web/src/components/DatasetCard/`; `web/src/pages/HomePage.tsx`; `web/src/pages/admin/DatasetAdminPage.tsx` | Boundary check: confirm Live Preview reuses this component rather than a duplicated admin-only rendering. | required | M42 (component); M44/M45 (Live Preview consumer) |
| `web/src/components/DatasetDetail/`, `web/src/components/InferenceForm/`, `web/src/components/InferenceResult/` are the shared rendering owners for both the real Dataset Detail page and the admin Live Preview detail/form/result modes. | `docs/design-runtime-parity-matrix.md` "Shared public components used by Dataset Admin Live Preview" row | Same components as above | Boundary check: confirm no page-local duplicate of these components exists for the preview path. | required | M42 (components); M44/M45 (Live Preview consumer) |
| Shared component reuse never bypasses the real public/private data boundary (e.g., Live Preview must not call authenticated admin-only fields into the public component in a way that could leak into the real public page). | `docs/design-runtime-parity-matrix.md`, `docs/design-prototype-behavior-inventory.md` Live Preview rows | `web/src/lib/livePreviewProjection.ts` | Boundary check during M45 Live Preview behavior parity work. | required | M45 |

## Live Preview

| Checklist item | Source evidence | Runtime owner | Validation method | Status | Downstream owner |
| --- | --- | --- | --- | --- | --- |
| Preview mode switching (detail/card/result/form) matches the prototype's mode-switching behavior, and the result preview is explicitly labeled as placeholder-only, never a real prediction. | `design/screens/dataset-admin/desktop/script.js` (M41-02 row: "Live Preview mode switching", classification `already implemented`); `DatasetAdminPage.test.tsx` `it("renders all Live Preview modes from the loaded draft and customization")` | `web/src/pages/admin/DatasetAdminPage.tsx`; `web/src/lib/livePreviewProjection.ts` | Behavior test citing the existing case; boundary check that the result mode never claims to be a real inference. | required | M45 |
| Each Live Preview mode's rendered output updates reactively when a fed draft or customization field is edited. | `DatasetAdminPage.test.tsx` `it("updates each Live Preview mode's rendered output when a fed draft or customization field is edited")` | `web/src/pages/admin/DatasetAdminPage.tsx`; `web/src/lib/livePreviewProjection.ts` | Behavior test citing the existing case. | required | M45 |
| `projectHomeCardPreview` correctly passes `problemType` from the loaded public context into Home card props, and leaves it undefined when no public context is available. | `web/src/lib/livePreviewProjection.test.ts` describe block "projectHomeCardPreview" (`it`s: "passes problemType from the loaded public context into the Home card props", "leaves problemType undefined when public context is unavailable") | `web/src/lib/livePreviewProjection.ts` | Behavior test citing both existing cases. | required | M45 |
| `projectDatasetDetailPreview` keeps Source and Release metadata projected from the live draft form (not the release-artifact context) for the preview path. | `livePreviewProjection.test.ts` describe block "projectDatasetDetailPreview" (`it("keeps Source and Release metadata projected from the draft form")`) | `web/src/lib/livePreviewProjection.ts` | Behavior test citing the existing case. | required | M45 |
| Result-card preview labels (probability/submit/model/badge) update from schema-backed presentation fields while the result values themselves remain fixed placeholders. | `design/screens/dataset-admin/desktop/script.js` (M41-02 row: "Result label and badge preview", classification `preview-only`) | `web/src/pages/admin/DatasetAdminPage.tsx`; `web/src/lib/livePreviewProjection.ts` | Boundary check: confirm the placeholder result never becomes a real inference call. | preview-only | M45 |
| Live Preview stays inside the tabbed workspace at the compact desktop (~`1360x768`) target. | `docs/design-asset-token-consolidation.md` "Compact Desktop Constraints" section | `web/src/pages/admin/DatasetAdminPage.tsx` | Visual/responsive review at approximately `1360x768`. | required | M44 |

## Assets and Tokens

| Checklist item | Source evidence | Runtime owner | Validation method | Status | Downstream owner |
| --- | --- | --- | --- | --- | --- |
| The two support-root Atlas sidebar logo candidates are confirmed byte-identical and must collapse to one canonical frontend asset, never two. | `docs/design-asset-token-consolidation.md` "Support-Root Asset Inventory" (SHA-256 `d4844b45a7aab4a8a00f57fac0bf88372c67d345bec5301a230c7930552c85ba`) | `web/src/layouts/AdminShell.tsx` (future asset consumer) | Boundary check when an implementation issue explicitly authorizes asset copying: confirm only one canonical asset file is added. | deferred | Later asset-copy issue if authorized |
| Public tokens (font stack, canvas, green accent, cards, buttons, focus states) map to the existing `web/src/styles/tokens.css` / `web/src/components/ui/ui.css` families rather than new page-local values. | `docs/design-asset-token-consolidation.md` "Public Shell Token Mapping" and "Cards, Tabs, Status Pills, Forms, and Tables" tables | `web/src/styles/tokens.css`; `web/src/components/ui/ui.css` | Visual review confirming reuse of `--atlas-color-accent` family and shared `atlas-card`/`atlas-button` tokens. | required | M42 |
| Admin tokens (canvas, sidebar surface, profile footer, active nav) reuse the same global token family rather than introducing a second admin-only palette. | `docs/design-asset-token-consolidation.md` "Admin Shell Token Mapping" table | `web/src/styles/tokens.css`; `web/src/layouts/AdminShell.tsx` | Visual review confirming no inferred second green palette. | required | M43 |
| Compact desktop (~`1360x768`) density constraints for Dashboard and Dataset Admin are honored (reduced padding/spacing, isolated table overflow, no forced `768px` content clipping). | `docs/design-asset-token-consolidation.md` "Compact Desktop Constraints" section | `web/src/pages/admin/DashboardPage.tsx`; `web/src/pages/admin/DatasetAdminPage.tsx`; `web/src/layouts/AdminShell.tsx` | Visual/responsive review at approximately `1360x768` for both Dashboard and Dataset Admin. | required | M43 (Dashboard); M44 (Dataset Admin) |
| No support-root CSS, HTML, or JavaScript is copied as production code or stylesheet; visual requirements are translated into existing token/style owners. | `docs/design-asset-token-consolidation.md` intro and Review Checklist | All React style owners above | Boundary check performed as part of each downstream milestone's implementation evidence. | required | M42/M43/M44/M45 |

## Behavior Classifications

Every behavior-related checklist row above (and every M41-02 inventory row it
cites) carries exactly one of the following classifications, reused verbatim
from `docs/design-prototype-behavior-inventory.md`:

| Classification | Meaning | Where it appears in this checklist |
| --- | --- | --- |
| `already implemented` | Current React already has an equivalent behavior. | Dataset Detail tabs; Dashboard search filtering; Dataset Admin tab switching; Live Preview mode switching; dataset combobox selector. |
| `implementable in React` | Local UI state, safe to translate without new backend/schema ownership. | PublicShell mobile nav-link close; PublicShell Escape/focus-return; Dashboard `Ctrl+K` search shortcut. |
| `schema/API-backed` | Behavior depends on an existing schema/API contract and must stay within it. | Dashboard summary counters; theme/icon/description/primary-metric fields; inference form customization; publishing lifecycle; visibility lock. |
| `preview-only` | May update a local/private preview only; never implies real prediction, publishing, upload, or backend mutation. | Live Preview result-card label/badge preview. |
| `disabled` | UI represents the behavior as unavailable because no safe owner exists. | Dashboard Promote; Dashboard Remove. |
| `deferred` | Needs a later M42 through M45 implementation or explicit schema/API reconciliation. | PublicShell mobile-link-close/Escape tests; Dashboard `Ctrl+K` shortcut and Open-admin placeholder; Admin logo asset copy; theme bank beyond `atlas-green`; result presets beyond `risk`; uploaded Home-card image; detail preview sub-tabs; character counters. |

Every future M42 through M45 implementation issue must carry forward the exact
classification for any item it touches, and must update this checklist's
status column (not silently reclassify) if a classification changes.

## Deferred and Disabled Prototype-Only Behavior

This section consolidates every item that must **not** be treated as
production-ready behavior until an explicit later decision changes that,
gathered from `docs/design-prototype-behavior-inventory.md`'s "Deferred or
Disabled Behavior Summary" and `docs/design-asset-token-consolidation.md`'s
"Schema/API-Dependent or Deferred Visual Options":

| Behavior | Status | Boundary | Downstream owner |
| --- | --- | --- | --- |
| Dashboard Promote run action | `disabled` | No validated publisher/profile workflow owner for backend mutation. | Later publisher/profile workflow issue only if authorized |
| Dashboard Remove row action | `disabled` | No safe owned API for deleting/removing rows from source truth. | Later admin data-management issue only if authorized |
| Dashboard "Open admin" placeholder navigation | `deferred` | Needs safe route handoff and a validated dataset identifier. | M43 (Dashboard) or M44 (Dataset Admin entry flow) |
| Uploaded Home-card background image | `deferred` | Needs explicit upload/storage/reference schema and API ownership; current schema supports a reference, not raw uploaded bytes. | Later asset/upload capability issue if authorized |
| Prototype theme bank beyond `atlas-green` | `deferred` | Must not expand the `theme.preset` schema enum by inference. | Later schema reconciliation issue if authorized |
| Result presets beyond the supported `risk` badge preset | `deferred` | Must not expand `result_card.badge_preset` by inference. | Later schema reconciliation issue if authorized |
| Detail preview sub-tabs beyond the current detail/card/result/form modes | `deferred` | Belongs to final Live Preview visual structure decided in M44. | M44 (visual structure); M45 (behavior) |
| Character counters on Dataset Admin form fields | `deferred` | Safe only if grounded in real schema `maxLength` limits, not prototype-only values. | M45 (within schema limits) |
| Arbitrary color editor for theme/tokens | `deferred` | Needs explicit schema, token, validation, and rendering support; no raw CSS/hex values by inference. | Later schema/token issue if authorized |
| Prototype-only toast/highlight feedback tied to disabled actions | `deferred` | Feedback is only safe for supported, non-disabled actions. | M43 (Dashboard) |
| PublicShell mobile nav-link close and Escape/focus-return | `deferred` | Not yet implemented or test-covered; safe local React state once added. | M42 |
| Admin sidebar Atlas logo asset copy | `deferred` | Needs repository asset-convention confirmation and explicit copy authorization; two byte-identical support-root candidates must collapse to one. | Later asset-copy issue if authorized |

## Downstream Milestone Owner Mapping

This mapping is the current best-effort ownership boundary, carried forward
from `docs/design-runtime-parity-matrix.md`'s "M42 Through M45 Ownership"
table. Per the M41-04 formal issue's own `references.missing_or_to_confirm`
and this checklist's residual gap below, it must be re-confirmed against the
actual M42 through M45 formal issues once those are derived — this checklist
does not itself derive or close them.

| Milestone | Ownership boundary | Checklist sections primarily owned |
| --- | --- | --- |
| M42 | PublicShell, Public Home, Dataset Detail, and shared public component parity. | Public Home; Dataset Detail; PublicShell; Shared Public Components (component ownership rows) |
| M43 | AdminShell and Admin Dashboard `/admin` parity against the `dataset-admin-home` reference. | Admin Dashboard; AdminShell |
| M44 | Dataset Admin `/admin/dataset-admin` visual structure and Live Preview visual structure. | Dataset Admin (visual-structure rows); Live Preview (compact-desktop row) |
| M45 | Dataset Admin behavioral parity and final public/admin regression closure. | Dataset Admin (behavior rows); Live Preview (behavior rows); Shared Public Components (boundary row) |

## Cross-Check Against M41 Definition of Done

- Every required public/admin surface named in the M41 Definition of Done
  (`docs/milestones.md`) has at least one checklist row above: Public Home,
  Dataset Detail, Admin Dashboard, Dataset Admin, PublicShell, AdminShell,
  and shared public components consumed by Live Preview are all represented.
- Assets and tokens required by React are inventoried in the Assets and Tokens
  section, consistent with `docs/design-asset-token-consolidation.md`.
- JavaScript-defined behaviors to be implemented, disabled, or deferred are
  inventoried in the Behavior Classifications and Deferred/Disabled sections,
  consistent with `docs/design-prototype-behavior-inventory.md`.
- No checklist item authorizes runtime mutation, schema expansion, asset
  copying, or public upload by itself; every `deferred`/`disabled` item names
  the later issue category required before it can change.

## Known Gaps

- Final M42 through M45 milestone owner mapping must be re-confirmed once
  those milestones are actually derived; this checklist can only carry
  forward the current best-effort mapping above.
- The PublicShell mobile-link-close and Escape/focus-return behaviors are
  marked `deferred` because no test currently exercises them; M42 must add
  the behavior and the corresponding test together, not the test alone.
- The Dataset Admin `Ctrl+K` search shortcut equivalent for Dashboard is
  optional; if a downstream milestone chooses not to implement it, it should
  be re-marked here as intentionally out of scope rather than left ambiguous.
