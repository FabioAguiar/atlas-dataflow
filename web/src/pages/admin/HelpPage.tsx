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

export default function HelpPage() {
  return (
    <section aria-labelledby="admin-help-title" style={pageStyle}>
      <div>
        <p className="eyebrow">Help</p>
        <h1 id="admin-help-title">Admin help</h1>
        <p className="summary">
          Placeholder for future operator guidance. This page does not expose generated runs, draft states, or
          operational admin actions.
        </p>
      </div>

      <article style={panelStyle}>
        <span className="atlas-status-pill atlas-status-pill--info">Guidance placeholder</span>
        <strong>Future admin documentation surface</strong>
        <p style={{ margin: 0, color: "var(--atlas-color-text-muted)" }}>
          Help content can be added later without changing publisher, registry, runtime, contract, or release-artifact
          source-of-truth boundaries.
        </p>
      </article>
    </section>
  );
}
