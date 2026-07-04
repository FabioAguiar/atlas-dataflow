# Design Asset and Token Consolidation Plan

M41-03 defines the visual asset and token consolidation plan required before
React parity work continues in M42 through M45. It is a planning artifact. It
does not authorize copying support-root assets into runtime paths, changing
React styling, expanding schemas, changing APIs, or treating prototype CSS as a
production stylesheet.

Support-root paths under `design/screens/` are UX source references only.
Repository paths under `web/src/` and `contracts/` are owner references only
unless a later issue explicitly authorizes implementation work.

## Support-Root Asset Inventory

| Asset or reference | Role | Consolidation note |
| --- | --- | --- |
| `design/screens/dataset-admin-home/assets/atlas-logo-green-transparent-sidebar.png` | Admin sidebar Atlas logo candidate | Byte-identical to the Dataset Admin logo candidate. Treat as one support-root source candidate for future canonicalization. |
| `design/screens/dataset-admin/assets/atlas-logo-green-transparent-sidebar.png` | Dataset Admin sidebar Atlas logo candidate | Byte-identical to the Dashboard logo candidate. Do not copy both into runtime paths. |
| `design/screens/home/visual-spec.md` | Public token and shell reference | Source for public light canvas, green accent, navigation rail behavior, card visual rules, buttons, focus states, and public spacing. |
| `design/screens/dataset-admin-home/visual-spec.md` | Dashboard token and compact desktop reference | Source for admin sidebar, Dashboard cards, tables, status pills, search control, action styles, and compact desktop density. |
| `design/screens/dataset-admin/visual-spec.md` | Dataset Admin token and compact desktop reference | Source for admin workspace, tab system, forms, theme presets, icon/card options, upload concept, Live Preview visuals, and publishing panels. |
| `design/screens/dataset-admin-home/responsive.md` | Dashboard compact desktop reference | Source for the `1360x768` low-height desktop rules for sidebar width, table wrappers, card density, padding, and scroll behavior. |
| `design/screens/dataset-admin/responsive.md` | Dataset Admin compact desktop reference | Source for the `1360x768` low-height desktop rules for tabs, forms, theme/icon grids, publishing controls, and workspace scrolling. |

The two sidebar logo files currently share the same SHA-256:
`d4844b45a7aab4a8a00f57fac0bf88372c67d345bec5301a230c7930552c85ba`.
Future implementation should treat them as duplicate support-root candidates,
not as separate runtime assets.

## Duplicate Asset Canonicalization Recommendation

- Canonicalize the Atlas sidebar logo to one frontend asset only when a later
  implementation issue explicitly authorizes asset copying.
- Before copying, confirm the repository's preferred static asset convention.
  This plan does not decide whether the eventual path belongs under `public/`,
  `web/src/assets/`, or another future approved location.
- Preserve source attribution in the future implementation evidence so the
  copied asset can be traced back to the support-root logo candidates.
- Do not copy support-root CSS, HTML, or JavaScript. Translate visual
  requirements into existing React token/style owners.
- Do not add a duplicate logo file per admin screen. AdminShell and any future
  admin surfaces should reference the same canonical asset once authorized.

## Future Frontend Asset Path Strategy

Future M42 through M45 implementation should use this sequence:

1. Confirm the target repository's asset convention from existing frontend
   structure and build tooling.
2. Copy only the required canonical asset, not every support-root asset folder.
3. Wire the asset through the React owner that needs it, most likely
   `web/src/layouts/AdminShell.tsx` for private admin navigation.
4. Keep public and private shell branding separate unless a later issue
   explicitly authorizes a shared brand component.
5. Validate that the asset renders in comfortable desktop and compact desktop
   layouts without global overflow.

No current M41-03 change should create runtime asset imports, public URLs, or
stylesheet references.

## Public Shell Token Mapping

| Visual concern | Current or proposed owner | Planning guidance |
| --- | --- | --- |
| Font stack, page canvas, primary text | `web/src/styles/tokens.css` through `web/src/index.css` | Continue using the global Atlas token file as the first owner for shared font, canvas, text, border, radius, shadow, and semantic color tokens. |
| Public green accent, active nav state, soft icon tiles | `web/src/styles/tokens.css`; public shell/page CSS where already owned | Map support-root public `#176b2c` / soft green concepts to the current `--atlas-color-accent`, `--atlas-color-accent-strong`, and `--atlas-color-accent-muted` family unless a later design-token issue expands presets. |
| Public cards, dataset tiles, buttons, focus states | `web/src/components/ui/ui.css` plus existing public component styles | Prefer shared `atlas-card`, `atlas-button`, focus ring, border, radius, and shadow tokens before adding page-local values. |
| Public navigation rail and mobile overlay | `web/src/layouts/PublicShell.tsx` as React owner; existing shell CSS as style owner | Shell behavior remains React state. Token changes should support always-visible toggle, active item state, mobile overlay, and desktop collapse without duplicating admin shell styles. |

Public parity work should keep Home and Dataset Detail data-driven. Visual
tokens must not hardcode a particular dataset set as product behavior.

## Admin Shell Token Mapping

| Visual concern | Current or proposed owner | Planning guidance |
| --- | --- | --- |
| Admin canvas, sidebar surface, borders, profile block | `web/src/styles/tokens.css`; `web/src/layouts/AdminShell.tsx` style owner until extracted | Reuse global canvas, surface, border, radius, muted text, and accent tokens. Avoid introducing a second admin-only green palette by inference. |
| Admin logo and brand block | `web/src/layouts/AdminShell.tsx` plus a future canonical asset path if authorized | Replace the current text mark only in a later asset-copy implementation. M41-03 records the need but does not copy the logo. |
| Admin active navigation and profile footer | `web/src/styles/tokens.css`; `web/src/layouts/AdminShell.tsx` | Keep active item and avatar treatments aligned with `--atlas-color-accent-muted` / `--atlas-color-accent-strong`. |
| Compact admin workspace density | `web/src/layouts/AdminShell.tsx`; page-level admin styles | Future extraction may move inline shell styles into CSS, but M41-03 does not authorize that refactor. |

Admin navigation must remain private. Matching the support-root admin shell must
not imply public administration or weaken existing access boundaries.

## Cards, Tabs, Status Pills, Forms, and Tables

| Element family | Current or proposed token owner | Consolidation rule |
| --- | --- | --- |
| Cards and panels | `web/src/components/ui/ui.css` | Use shared radius, border, surface, muted surface, and shadow tokens. Avoid screen-local card shadows unless visual parity requires a later scoped token. |
| Buttons and actions | `web/src/components/ui/ui.css` | Keep primary, secondary, ghost, warning, and destructive treatments token-based. Dashboard destructive actions need visual caution but no unsupported backend mutation. |
| Tabs | `web/src/components/ui/ui.css` and page-specific tab styles where needed | Shared pill tabs already exist; Dataset Admin's horizontal workspace tabs may need a later structural style owner, but should still use shared color/radius/spacing tokens. |
| Status pills and badges | `web/src/components/ui/ui.css` | Reuse semantic `info`, `success`, `warning`, and `danger` token pairs. Add gray/slate unavailable state only through a later scoped token if required. |
| Forms and helpers | `web/src/components/ui/ui.css`; Dataset Admin page owner | Form fields should use shared spacing, border, radius, help text, and focus-ring tokens. Character counters should only follow real schema limits. |
| Tables and dense rows | `web/src/components/ui/ui.css`; Dashboard page owner | Keep table-row structure responsive and isolate overflow to table wrappers on compact desktop. |

The design references use rounded surfaces, subtle borders, and soft shadows.
Future implementation should map those concepts into shared tokens rather than
copying prototype-specific CSS values into each page.

## Compact Desktop Constraints

Compact desktop means a desktop viewport around `1360x768`, not a tablet or
mobile layout.

For Dashboard (`/admin`):

- Preserve the fixed admin shell and table-based management model.
- Reduce sidebar width, outer padding, row gaps, card spacing, card icon size,
  and table cell padding only inside compact desktop breakpoints.
- Keep summary cards in a desktop row when space allows.
- Keep search accessible in the header, allowing wrap only when needed.
- Isolate horizontal overflow to table wrappers.
- Allow vertical page scroll instead of forcing all content into `768px`
  height.

For Dataset Admin (`/admin/dataset-admin`):

- Keep the fixed admin shell, top header controls, and the tabbed workspace.
- Keep all seven workspace tabs usable as a desktop row or controlled
  horizontal tab strip; do not convert to mobile navigation for this target.
- Reduce panel padding, form gaps, tab height, tab typography, and card spacing.
- Keep the 15-icon Home card selector, the controlled theme grid, and publishing
  controls usable without global horizontal overflow.
- Keep Live Preview inside the tab system.
- Allow vertical workspace scroll.

Future parity validation should include at least a comfortable desktop viewport
and the compact `1360x768` target.

## Controlled Theme, Icon, and Card References

- `contracts/dataset-public-profile.schema.json` currently constrains
  `theme.preset` to `atlas-green`. Prototype theme-bank entries are visual
  references only until schema/API work authorizes additional presets.
- `home_card.icon` has a controlled enum that includes legacy values and a
  curated icon bank. Future UI may expose only schema-supported icon values.
- `home_card.background_image_ref` is a bounded reference field. The prototype
  upload behavior must not be translated into raw image bytes, local paths, or
  arbitrary URL persistence.
- `home_card.short_description` and `home_card.primary_metric_key` are safe
  presentation references when they remain schema-backed and data-driven.
- `result_card.badge_preset` is currently constrained to `risk`; other
  prototype result preset concepts remain deferred.

These controls can update local previews when backed by current schema fields,
but preview changes must not imply publication until the publishing workflow
creates or updates a public snapshot.

## Schema/API-Dependent or Deferred Visual Options

| Option | Status | Required decision before runtime persistence |
| --- | --- | --- |
| Arbitrary color editor | Deferred | Needs explicit schema, token, validation, and rendering support. Do not accept raw CSS or arbitrary hex values by inference. |
| Prototype theme bank beyond `atlas-green` | Deferred | Needs expanded `theme.preset` enum plus frontend token implementation for each preset. |
| Uploaded image handling | Deferred | Needs upload/storage/reference ownership, safe validation, and public rendering rules. Existing schema supports a reference, not local uploaded bytes. |
| Unsupported result enums or preset banks | Deferred | Needs result-card schema support and rendering semantics beyond the current `risk` preset. |
| Character counters | Deferred unless schema-backed | Counters should reflect actual schema limits, not prototype-only maxlength values. |
| Dashboard promote/remove/open actions | Deferred or disabled | Needs backend/API ownership and safe workflow semantics before visual success states can be meaningful. |

Unsupported visual controls should be absent, disabled, or explicitly marked as
deferred in future implementation rather than persisted opportunistically.

## Validation Expectations for Future Implementation

Future M42 through M45 implementation should provide evidence that:

- support-root assets were copied only when explicitly authorized;
- duplicate sidebar logos were collapsed to one canonical frontend asset;
- public and admin shell token use maps back to existing token/style owners;
- compact desktop behavior was checked at approximately `1360x768`;
- no support-root CSS was copied as a production stylesheet;
- no unsupported profile fields, theme presets, result presets, upload payloads,
  or arbitrary colors were persisted;
- public navigation and private admin navigation remain separate;
- Live Preview remains a preview and does not become runtime prediction,
  publisher, registry, or release authority;
- React owner paths were changed only by later issues that authorize those
  paths.

## Review Checklist

- Every required support-root asset and visual reference is represented.
- The duplicate logo candidates are documented as byte-identical.
- The future asset path strategy requires repository convention validation.
- Public shell, admin shell, shared UI, cards, tabs, status pills, forms, and
  tables have token owner guidance.
- Dashboard and Dataset Admin compact desktop constraints are explicit.
- Schema/API-dependent visual options are marked deferred or bounded by current
  contracts.
- This document does not authorize runtime code, CSS, schema, publisher,
  registry, model, notebook, API, or asset-copy changes.
