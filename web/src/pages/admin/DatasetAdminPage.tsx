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

const disabledButtonStyle: CSSProperties = {
  justifySelf: "start",
  minHeight: "2.5rem",
  border: "1px solid var(--atlas-color-border-strong)",
  borderRadius: "var(--atlas-radius-md)",
  padding: "0 var(--atlas-space-4)",
  color: "var(--atlas-color-text-subtle)",
  font: "inherit",
  fontWeight: 700,
  background: "var(--atlas-color-surface-muted)",
  cursor: "not-allowed",
};

export default function DatasetAdminPage() {
  return (
    <section aria-labelledby="dataset-admin-title" style={pageStyle}>
      <div>
        <p className="eyebrow">Dataset Admin</p>
        <h1 id="dataset-admin-title">Dataset administration</h1>
        <p className="summary">
          Placeholder surface for future dataset curation. Forms, backend mutation, publishing, and run discovery are
          intentionally unavailable.
        </p>
      </div>

      <article style={panelStyle}>
        <span className="atlas-status-pill atlas-status-pill--warning">Non-operational</span>
        <strong>Dataset controls are not active</strong>
        <p style={{ margin: 0, color: "var(--atlas-color-text-muted)" }}>
          This screen establishes navigation only and does not create, update, publish, or validate datasets.
        </p>
        <button disabled style={disabledButtonStyle} type="button">
          Dataset form unavailable
        </button>
      </article>
    </section>
  );
}
