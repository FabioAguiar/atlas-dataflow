# M42 Through M45 Derivation Boundaries and Live Preview Dependencies

M41-05 defines the explicit, non-overlapping derivation boundary between M42
through M45 and maps the shared-component dependencies between the real
public Home/Dataset Detail rendering path and Dataset Admin's Live Preview
tab. This document consolidates findings from the M41-01 screen-to-React
matrix (`docs/design-runtime-parity-matrix.md`), the M41-02 prototype
behavior inventory (`docs/design-prototype-behavior-inventory.md`), and the
M41-04 screen-by-screen checklist (`docs/design-parity-checklist.md`).
`docs/milestones.md` remains the M41 continuity anchor; this file carries the
boundary and dependency detail.

This document does not authorize React implementation, API changes, schema
changes, publisher changes, registry changes, model changes, or any runtime
mutation. Creating this document is not evidence that any M42 through M45
dependency or sequencing risk is resolved. Final M42 through M45 milestone
titles and scopes are not yet confirmed; the boundaries below are assigned
against the milestone identifiers currently known from the M41-01 matrix and
M41-04 checklist and must be re-confirmed once those milestones are actually
derived.

## M42 Through M45 Derivation Boundary Map

| Milestone | Boundary |
| --- | --- |
| M42 | PublicShell, Public Home, Dataset Detail, and shared public component parity — including `DatasetCard.tsx`, `DatasetDetailHeader.tsx`/`PerformanceSummary.tsx`/`TargetDistribution.tsx`/`FeatureImportance.tsx`, `ModelCard.tsx`, `InferenceResult.tsx`, and `InferenceForm.tsx`, since all of these are the exact same module instances Live Preview reuses. |
| M43 | AdminShell and Admin Dashboard parity; no Live Preview dependency. |
| M44 | Dataset Admin visual structure parity, including Live Preview's visual structure across all four already-implemented modes (detail, card, result, form); depends on M42 landing first for the shared components listed above. |
| M45 | Dataset Admin behavioral parity, including Live Preview's reactive update behavior and the schema/API-backed fields (theme preset, icon, primary metric, publishing lifecycle); depends on M42 (shared components) and M44 (visual structure) landing first. |

**Sequencing rule:** M44 and M45 Live Preview parity work is downstream of
and dependent on M42's shared-component parity landing first, since Live
Preview does not maintain separate preview-only copies of these components.
This sequencing is implied by the already-accepted M41-01 matrix and M41-04
checklist but was not previously stated as an explicit rule; it is stated
explicitly here so a future M44 or M45 issue does not begin Live Preview
visual/behavioral work before the underlying shared component has its M42
parity pass.

## Live Preview Shared-Component Dependency Map

Dataset Admin's Live Preview tab (`web/src/pages/admin/DatasetAdminPage.tsx`,
`LivePreviewTab`) has exactly four modes: `detail`, `card`, `result`, and
`form`. Three of the four route through dedicated projection functions in
`web/src/lib/livePreviewProjection.ts`; the fourth (`form`) bypasses the
projection-function layer entirely. These are two distinct, non-interchangeable
mechanisms and must not be treated as one uniform rule.

| Mode | Mechanism | Projection helper(s) | Shared component(s) | Public consumer |
| --- | --- | --- | --- | --- |
| `card` (Home Card) | Projection-function-mediated | `projectHomeCardPreview` | `web/src/components/DatasetCard/DatasetCard.tsx` | `web/src/pages/HomePage.tsx` |
| `detail` (Dataset Detail) | Projection-function-mediated | `projectDatasetDetailPreview`, `projectModelCardPreview`, `toVisualizationsPayload` | `web/src/components/DatasetDetail/DatasetDetailHeader.tsx`, `PerformanceSummary.tsx`, `TargetDistribution.tsx`, `FeatureImportance.tsx`, `web/src/components/ModelCard/ModelCard.tsx` | `web/src/pages/DatasetPage.tsx` |
| `result` (Result Card) | Projection-function-mediated | `projectResultCardPreview` | `web/src/components/InferenceResult/InferenceResult.tsx` | `web/src/pages/DatasetPage.tsx` (via InferenceForm's real submit flow) |
| `form` (Inference Form Layout) | Direct component reuse via the component's own `previewMode` prop; no projection helper exists or is needed | none | `web/src/components/InferenceForm/InferenceForm.tsx` | `web/src/pages/DatasetPage.tsx` |

`web/src/components/ModelCard/ModelCard.tsx` is a real Live Preview
dependency (rendered by `DatasetDetailLivePreview` via
`projectModelCardPreview`, `web/src/pages/admin/DatasetAdminPage.tsx` line
~1820) that was not named anywhere in the formal issue's `candidate_files`;
it was found only by reading `DatasetAdminPage.tsx`'s own import list during
the M41-05 analysis.

Every shared component above is the same module instance the real public
Home (`web/src/pages/HomePage.tsx`) and Dataset Detail
(`web/src/pages/DatasetPage.tsx`) pages consume — confirmed by the M41-01
matrix and by `DatasetAdminPage.tsx`'s own imports — so an M42 change to any
of these components' public props or rendering propagates into Live Preview
automatically, with no separate preview-only reimplementation to keep in
sync.

## Deferred and Schema-Backed Ownership Notes (M45)

`DatasetAdminPage.tsx`'s `DatasetDetailLivePreview` (lines ~1773–1823)
contains three pre-existing, self-documented adapter workarounds. Each has an
inline comment stating the underlying fix belongs to
`web/src/lib/livePreviewProjection.ts`'s stale type signatures but was
deliberately deferred by a prior, unidentified issue rather than done inline.
None of these three adapters change what Live Preview renders today; they
exist only to reconcile the projection layer's stale types with the current
icon-bank schema and the real `InferenceForm` contract shape.

1. **Icon-type narrowing (`toLegacyPreviewIcon`, line ~44).** Narrows the
   widened `DatasetIconName` icon bank (`DatasetCard.tsx`'s own comment
   confirms it "now spans Atlas's full curated icon bank") back to
   `livePreviewProjection.ts`'s stale closed union type (`'' | 'telecom' |
   'bank' | 'generic'`) purely to satisfy `projectDatasetDetailPreview`'s
   parameter type. Has no rendering effect since that function never reads
   the icon field for the Detail preview.
2. **Contract-shape reshaping (line ~1792).** Locally reshapes the real
   `InferenceForm` contract's `{features}` into the `{fields?}` shape
   `projectDatasetDetailPreview`'s own local `PreviewContract` type still
   expects.
3. **`date_format` clamp (lines ~1793–1805).** Force-clamps `date_format` to
   `''` so the Detail preview always renders the same fixed `dd/mm/yyyy`
   wording `web/src/pages/DatasetPage.tsx` hardcodes for the real public
   page, rather than exposing the general date-format-forwarding behavior
   `livePreviewProjection.test.ts`'s own colocated unit test still asserts in
   isolation.

Whether `livePreviewProjection.ts`'s stale closed-union icon type and local
`{fields?}` contract shape should eventually be widened/aligned (removing the
need for these three adapters), or whether the adapter-at-call-site pattern
should simply continue indefinitely, is an open design decision this document
discloses but does not resolve. Any M45 issue touching
`livePreviewProjection.ts`'s exported types must either fix them properly
(removing the need for the adapters) or explicitly continue the adapter
pattern — not silently regress the Home Card icon bank coverage or the Detail
preview's date-format parity with the real public `DatasetPage.tsx`.

Also deferred, per the already-accepted M41-02/M41-03 findings: uploaded Home
Card background image handling remains unsupported inside Live Preview's
`card` mode, since it renders the same `DatasetCard.tsx` instance the public
Home page does.

## Known Support-Root Documentation Discrepancy

`design/screens/dataset-admin/content.md` documents only two Live Preview
modes ("Dataset Detail", "Home Card") under its "Tab: Live Preview" section.
The already-implemented React Live Preview has four modes (`detail`, `card`,
`result`, `form`), and the already-accepted M41-02 behavior inventory already
documents the prototype's own `script.js` as switching all four modes. This
means `content.md`'s two-mode description is stale relative to both the
prototype's actual behavior and the current React implementation.

This discrepancy is recorded here as a disclosed finding only.
`design/screens/dataset-admin/content.md` is a support-root design reference
and is treated as read-only per this project's established boundary; it is
not corrected by this document. A future implementer must not rely on
`content.md` alone and mistakenly treat the Result Card and Inference Form
Layout modes as unspecified scope creep — the four-mode structure already in
place is the correct baseline for M44/M45, not a reduction to `content.md`'s
documented two modes.

## Cross-Check Against the M41-04 Checklist

`docs/design-parity-checklist.md`'s "Downstream Milestone Owner Mapping" and
"Live Preview" sections already assign Live Preview rows to M44 (visual
structure, compact-desktop row) and M45 (behavior rows) and already name the
`card`/`detail`/`result`/`form` modes individually. This document does not
restate that checklist's per-row validation methods; it adds the boundary
map, the explicit M44/M45-depends-on-M42 sequencing rule, the consolidated
dependency-mechanism table above, and the adapter-workaround disclosure that
the checklist itself does not carry in this level of detail.

## Known Gaps

- Final M42 through M45 milestone titles and scopes are not yet confirmed;
  this document can only assign boundaries against the milestone identifiers
  currently known from the M41-01 matrix and M41-04 checklist. When M42-M45
  formal issues are drafted, cross-check their actual scope against this
  boundary map and correct it if the real derivation diverges.
- Whether `livePreviewProjection.ts`'s stale types should be widened now or
  the adapter pattern should simply continue is an open design decision left
  to whichever future M45 issue touches that module.
- Whether `design/screens/dataset-admin/content.md`'s stale two-mode
  description should itself be corrected is unresolved; support-root design
  docs are read-only UX references and no issue has yet authorized editing
  them.
