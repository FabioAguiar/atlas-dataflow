import type { CSSProperties } from "react";

const pageStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-5)",
};

const panelStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-3)",
  border: "1px solid var(--atlas-color-border)",
  borderRadius: "var(--atlas-radius-md)",
  padding: "var(--atlas-space-5)",
  background: "var(--atlas-color-surface)",
  boxShadow: "var(--atlas-shadow-sm)",
};

const mutedTextStyle: CSSProperties = {
  margin: 0,
  color: "var(--atlas-color-text-muted)",
};

const listStyle: CSSProperties = {
  margin: 0,
  paddingLeft: "var(--atlas-space-5)",
  display: "grid",
  gap: "var(--atlas-space-2)",
  color: "var(--atlas-color-text-muted)",
};

export default function HelpPage() {
  return (
    <section aria-labelledby="admin-help-title" style={pageStyle}>
      <div>
        <p className="eyebrow">Help</p>
        <h1 id="admin-help-title">Admin help</h1>
        <p style={mutedTextStyle}>
          Reference for the workflows already implemented in this admin surface. This page describes current
          behavior only; it does not document account management, credentials, deployment, or model settings, none
          of which exist here.
        </p>
      </div>

      <article aria-labelledby="admin-help-dashboard-title" style={panelStyle}>
        <h2 id="admin-help-dashboard-title" style={{ margin: 0 }}>
          Dashboard
        </h2>
        <p style={mutedTextStyle}>
          Dashboard loads private run summaries and shows each run&apos;s status (available, invalid, or
          unavailable), its dataset candidate, and its validation outcome. Use Search and Status to filter the run
          list.
        </p>
        <p style={mutedTextStyle}>
          Every run row also shows a <strong>Future workflow</strong> promotion control. This control is
          intentionally disabled: promotion is a future workflow entry point only, and does not create drafts,
          release candidates, publications, published snapshot visibility changes, registry updates, or release
          artifact mutations today.
        </p>
      </article>

      <article aria-labelledby="admin-help-dataset-admin-title" style={panelStyle}>
        <h2 id="admin-help-dataset-admin-title" style={{ margin: 0 }}>
          Dataset Admin
        </h2>
        <p style={mutedTextStyle}>
          Dataset Admin is a tabbed curation screen: Public Content, Metadata &amp; Card, Theme Preset, Inference
          Form, Result Card, Publishing, and Live Preview. The Publishing tab is where draft, preview, publish, and
          visibility actions live:
        </p>
        <ul style={listStyle}>
          <li>
            <strong>Save Draft</strong> updates private draft state only; it never publishes anything.
          </li>
          <li>
            <strong>Preview Draft</strong> opens a private, read-time preview of the current draft; it is not
            separately persisted.
          </li>
          <li>
            <strong>Publish Changes</strong> creates the latest published snapshot from the current draft. Publishing
            a snapshot does not by itself change public visibility.
          </li>
          <li>
            <strong>Visible Publicly</strong> controls exposure of the already-published snapshot only, independent
            of Publish Changes. A dataset with no publication record yet defaults to visible.
          </li>
        </ul>
        <p style={mutedTextStyle}>
          Publish Changes and Visible Publicly are distinct actions and do not imply each other: publishing a
          snapshot does not make it visible or hidden, and changing visibility does not publish a new snapshot.
        </p>
      </article>

      <article aria-labelledby="admin-help-onboarding-title" style={panelStyle}>
        <h2 id="admin-help-onboarding-title" style={{ margin: 0 }}>
          Public/private boundary and dataset onboarding
        </h2>
        <p style={mutedTextStyle}>
          A dataset moves from a generated run to a public profile through a sequence of distinct, manually operated
          steps: build the release candidate, promote it, activate it in the registry, save a profile draft, publish
          a snapshot, and set visibility. Public resolution then serves the published snapshot according to its
          visibility state.
        </p>
        <p style={mutedTextStyle}>
          Every one of these steps is currently a separate, manually operated action (a pipeline command, a
          promotion command, a registry-update command, or a Dataset Admin action) rather than a single automated
          pipeline. Fully automated onboarding — one command or workflow performing all steps together — does not
          exist yet.
        </p>
      </article>
    </section>
  );
}
