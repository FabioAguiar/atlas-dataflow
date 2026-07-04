# Design Interpretation — M29-01

## Interpretation

**`design/` is a deterministic UX reference. It is not a source of truth for schemas, API contracts, publisher logic, or runtime validation.**

The `design/` directory (ASF support root, not part of this repository) contains concrete HTML/CSS/JS prototypes and Markdown specs (`content.md`, `visual-spec.md`, `responsive.md`) for the public and private screens of the design-backed product surface authorized by M29. These assets exist to guide layout, content structure, and responsive behavior for the frontend implementation that begins at M30. They do not override, and must never be treated as replacing, this repository's contracts, publisher rules, artifact schemas, API boundaries, or tests.

This interpretation restates and applies the boundary already established in this repository:

- `docs/vision.md`: "Keep the design documentation under `design/` as a deterministic UX reference for the next implementation milestones." Also: "The design documentation under `design/` should be treated as the closest available deterministic UX reference, while inconsistencies between design documents and executable prototypes should be corrected through explicit implementation documentation."
- `docs/architecture.md`: "design prototypes are implementation references for UX and layout, but they do not override contracts, publisher rules, artifact schemas, API boundaries, or tests." Also: "Design markdown, visual specifications, responsive notes, and executable HTML/CSS/JS prototypes should guide layout, naming, interaction, and presentation. Inconsistencies between markdown and executable prototypes must be documented and resolved through implementation issues. Design documents do not override contracts, runtime semantics, publisher rules, artifact schemas, tests, or security boundaries."

Where design Markdown and the executable HTML/CSS/JS prototypes disagree, the inconsistency must be documented and resolved explicitly in the implementation issue that consumes that screen, not silently resolved by copying either source verbatim.

---

## Per-Screen Review

Each of the four `design/screens/*` folders named by `docs/architecture.md`'s design reference inventory was reviewed for `content.md`, `visual-spec.md`, `responsive.md`, and the available executable prototypes.

### `design/screens/home` — public Home

Public entry point and navigable listing of published predictive-analysis datasets. Visual direction: modern, clean, minimalistic, portfolio-ready. Prototypes exist for desktop, tablet, and mobile, with a dedicated responsive specification covering all three formats.

### `design/screens/dataset-detail` — public Dataset Detail

Public product page for a single dataset, combining descriptive context, technical metadata, an analytical overview, and contract-driven inference. Visual direction is consistent with Home. Prototypes exist for desktop, tablet, and mobile, with breakpoints documented (mobile up to 767px, tablet 768–1199px, desktop above).

### `design/screens/dataset-admin-home` — private Dashboard-equivalent

Administrative hub for inspecting notebook-generated runs and curating public Dataset Detail profiles: view runs, promote a run into a preparation/publication flow, view and manage existing Dataset Detail configurations. Explicitly documented as an executable design artifact only — it does not read real files, persist changes, call APIs, or alter the Atlas runtime. Current scope is desktop only; no tablet or mobile prototype exists for this screen at the time of this review.

### `design/screens/dataset-admin` — private Dataset Admin

Publication and curation panel for a single dataset: public copy, visual order, theme preset, labels, field grouping, result language, and publication state. Explicitly documented as a design reference, not part of the real React/Vite frontend implementation yet. Current scope is desktop only; tablet and mobile are noted as future work, not implemented in this increment.

### Scope note

`design/screens/home-template` also exists under the support root but is not one of the four screens enumerated by the formal issue or by `docs/architecture.md`'s design reference inventory (`design/screens/home/`, `design/screens/dataset-detail/`, `design/screens/dataset-admin-home/`, `design/screens/dataset-admin/`). It is out of scope for this interpretation and was not reviewed as part of it.

---

## Recorded Gap: Missing Settings and Help Screen Design

No dedicated Settings or Help screen design currently exists under `design/screens/`, even though both are declared part of the private admin shell in `docs/vision.md` and `docs/architecture.md`. `docs/architecture.md` independently states: "the design currently covers primary admin/public screens, while Settings and Help still need minimal design/implementation definition."

This absence is recorded here as an open gap, not resolved by inventing a design. Whether the Settings/Help design should be produced before or during M38 (Settings, Help, and Admin Completion Pass) is not decided by this document; if a resolution is scheduled, it should be tracked as a candidate for M38 rather than expanded within M29-01.

---

## Recorded Gap: Dataset Admin Theme and Result-Card Preset Parity

`design/screens/dataset-admin/content.md`'s `Tab: Theme Preset` section lists 14 reference presets (`Atlas Green`, `Ocean Blue`, `Sunset Orange`, `Purple Dawn`, `Slate`, `Forest`, `Teal Lagoon`, `Cyan Ice`, `Indigo Night`, `Rose Analytics`, `Amber Signal`, `Lime Growth`, `Copper Lab`, `Mono Graphite`), and its `Tab: Result Card` section lists five result-badge presets (`Risk`, `Value band`, `Target status`, `Severity`, `Custom`). `contracts/dataset-public-profile.schema.json` currently authorizes only one value in each set: `theme.preset` accepts only `"atlas-green"`, and `result_card.badge_preset` accepts only `"risk"`.

This is a real, intentional gap between the design reference and the schema it must be adapted to, not an oversight. `web/src/pages/admin/DatasetAdminPage.tsx`'s `ThemePresetTab` and `ResultCardTab` already reflect this boundary: their `<select>` controls expose only the schema-supported preset (plus a blank "no curated preset" option), and `DraftForm`'s `theme_preset`/`badge_preset` fields are typed as closed unions (`"" | "atlas-green"` and `"" | "risk"`) so no other value can be constructed or saved through this form. The remaining 13 theme presets and 4 result-card badge presets are not rendered as visible-but-disabled controls; they are omitted entirely until a future schema decision authorizes them.

This gap is recorded here, not resolved by inventing additional presets or by relaxing `contracts/dataset-public-profile.schema.json`, per this document's own interpretation above that design documents do not override contracts. Whether and when the schema should be extended with additional theme or badge presets is a separate future schema decision, out of scope for the Dataset Admin content-tab parity work that produced this note.

---

## Non-Authorization Statement

This interpretation does not authorize:

- implementing React screens from the prototypes;
- modifying any file under `design/`;
- designing new Settings or Help screens;
- formal GitHub issue publication;
- any branch creation, commit beyond this file, pull request, or patch generation.

Treating the HTML/CSS/JS prototypes as production-ready code to copy verbatim is explicitly out of scope and would carry prototype-only patterns into the real frontend, obscuring the still-missing Settings/Help design coverage.
