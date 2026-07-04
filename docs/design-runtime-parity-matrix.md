# Design Runtime Parity Matrix

M41-01 defines the screen-to-React parity contract for the current public and
admin design surfaces. This document is a planning artifact for M42 through
M45. It does not authorize React implementation, API changes, schema changes,
publisher changes, registry changes, model changes, or copying support-root
prototype files into runtime paths.

Support-root paths under `design/screens/` are UX source references only. React
paths under `web/src/` are runtime owner references only unless a later issue
explicitly authorizes implementation work.

## Status Taxonomy

| Status | Meaning |
| --- | --- |
| `current_runtime_owner_confirmed` | A current React owner exists and is sufficient as a mapping target. |
| `partial_parity` | A current React owner exists, but later milestones must close visual, responsive, or behavioral gaps against the UX reference. |
| `deferred_to_downstream_milestone` | The mapping is known, but implementation belongs to M42 through M45. |
| `unsupported_or_no_runtime_target` | The prototype behavior has no safe current runtime target and must be treated as unsupported until a later decision changes that. |
| `requires_read_only_confirmation` | The mapping needs another read-only confirmation pass before implementation. |

## Matrix

| Surface or component | Route or usage | Support-root UX reference | React runtime owner | Visual elements | Responsive targets | Interaction source | Implementation status | Downstream owner | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Public Home | `/` | `design/screens/home/` UX reference only | `web/src/pages/HomePage.tsx` with `web/src/layouts/PublicShell.tsx`; shared cards via `web/src/components/DatasetCard/` | Hero, repository and portfolio actions, featured dataset grid, empty/loading/error states, public footer | Public desktop, tablet, and mobile behavior from the Home reference | Home prototype content, responsive notes, and scripts as UX inputs only; current React fetches `/datasets` and renders data-driven cards | `partial_parity` | M42 public screens parity | Runtime owner is confirmed. Future work must keep cards data-driven and must not hardcode one dataset set as the product contract. |
| Dataset Detail | `/dataset/:slug` | `design/screens/dataset-detail/` UX reference only | `web/src/pages/DatasetPage.tsx` with `web/src/layouts/PublicShell.tsx`; detail, inference, visualization, model-card, and predict-view components under `web/src/components/` | Detail header, metadata row, overview tab, inference tab, metrics, target distribution, feature importance, model card, predict-view list | Public desktop, tablet, and mobile behavior from the Dataset Detail reference | Dataset Detail prototype content, responsive notes, and scripts as UX inputs only; current React fetches dataset metadata, context, metrics, contract, visualizations, model card, and views | `partial_parity` | M42 public screens parity | Runtime owner is confirmed. Runtime validation and inference behavior remain contract/API-driven, not prototype-authoritative. |
| Admin Dashboard | `/admin` | `design/screens/dataset-admin-home/` UX reference only | `web/src/pages/admin/DashboardPage.tsx` with `web/src/layouts/AdminShell.tsx` | Private dashboard header, run filters, status counters, runs table, dataset details table, safe action-state presentation | Compact desktop behavior from the dataset-admin-home reference, including approximately `1360x768` | Admin Dashboard prototype content, responsive notes, and scripts as UX inputs only; current React fetches admin runs and presents local filters/search | `partial_parity` | M43 admin shell and Dashboard parity | The `dataset-admin-home` design maps to Admin Dashboard `/admin`, not Public Home `/`. Private admin boundaries remain required. |
| Dataset Admin | `/admin/dataset-admin` | `design/screens/dataset-admin/` UX reference only | `web/src/pages/admin/DatasetAdminPage.tsx` with `web/src/layouts/AdminShell.tsx` | Dataset selector, status pill, public content tab, metadata/home-card tab, theme preset tab, inference form tab, result card tab, publishing tab, Live Preview tab | Compact desktop behavior from the Dataset Admin reference, including approximately `1360x768` | Dataset Admin prototype content, visual specs, assets, and scripts as UX inputs only; current React has draft, save, publish, visibility, customization, and preview flows | `partial_parity` | M44 visual structure parity; M45 behavior parity | Runtime owner is confirmed. M44 owns visual structure; M45 owns behavior translation where schema/API support exists. |
| PublicShell | Public route wrapper for `/`, `/dataset/:slug`, and `/dataset/:slug/view/:viewId` | `design/screens/home/` and `design/screens/dataset-detail/` shell/navigation references as UX inputs only | `web/src/layouts/PublicShell.tsx` | Public brand, navigation, mobile overlay toggle, external portfolio/repository/contact links, public content frame | Public desktop and mobile navigation behavior from public screen references | Public shell prototype navigation and responsive behavior as UX inputs only; current React owns nav-open state and media-query handling | `partial_parity` | M42 public screens parity | Runtime owner is confirmed. Public navigation must stay separate from private admin navigation. |
| AdminShell | Private route wrapper for `/admin`, `/admin/dataset-admin`, `/admin/settings`, and `/admin/help` | `design/screens/dataset-admin-home/` and `design/screens/dataset-admin/` shell/navigation references as UX inputs only | `web/src/layouts/AdminShell.tsx` | Private sidebar, Atlas DataFlow brand, admin navigation, profile block, private workspace header, admin content frame | Compact desktop admin shell behavior from admin references | Admin shell prototype navigation and compact layout behavior as UX inputs only; current React uses `AdminSettingsContext` for profile display | `partial_parity` | M43 admin shell and Dashboard parity | Runtime owner is confirmed. Admin navigation must stay private and must not imply public admin access. |
| Shared public components used by Dataset Admin Live Preview | Dataset Admin Live Preview modes for Home card, Dataset Detail, Result card, and Inference form layout | `design/screens/home/`, `design/screens/dataset-detail/`, and `design/screens/dataset-admin/` UX references only | `web/src/pages/admin/DatasetAdminPage.tsx`, `web/src/lib/livePreviewProjection.ts`, `web/src/components/DatasetCard/`, `web/src/components/DatasetDetail/`, `web/src/components/InferenceForm/`, `web/src/components/InferenceResult/` | Home card preview, Dataset Detail header preview, fixed placeholder result preview, inference form layout preview, preview mode controls | Admin compact desktop preview behavior plus public component responsive expectations | Dataset Admin Live Preview prototype behavior as UX input only; current projection helpers map draft fields onto real public component props and use fixed placeholders for non-real predictions | `partial_parity` | M42 public component parity; M44/M45 Live Preview consumers | Runtime owners are confirmed. Live Preview dependencies must remain explicit rather than hidden inside the Dataset Admin row. Placeholder result preview is not a real inference response. |

## Deferred and Unsupported Notes

- M41 records mapping only; React implementation is deferred to M42 through
  M45.
- Prototype JavaScript is a behavioral UX source, not production code and not
  API/schema authority.
- Any design control that requires unsupported schema, publisher, registry,
  model, release, or notebook behavior remains deferred until a later issue
  authorizes that contract.
- Support-root assets are not copied by M41-01. Asset consolidation belongs to
  later M41 work if explicitly authorized.

## M42 Through M45 Ownership

| Milestone | Ownership boundary |
| --- | --- |
| M42 | PublicShell, Public Home, Dataset Detail, and shared public component parity. |
| M43 | AdminShell and Admin Dashboard `/admin` parity against `dataset-admin-home`. |
| M44 | Dataset Admin `/admin/dataset-admin` visual structure parity and Live Preview visual structure. |
| M45 | Dataset Admin behavioral parity and final public/admin regression closure. |

## Review Checklist

- Every required public/admin surface has a React runtime owner or explicit
  downstream note.
- Public Home `/` and Admin Dashboard `/admin` remain distinct.
- Public navigation and private admin navigation remain distinct.
- Every support-root path is labeled as a UX source reference only.
- Every runtime path is labeled as a React owner reference only.
- Live Preview shared public component dependencies are explicit.
- M42 through M45 ownership is recorded without authorizing implementation in
  M41.
