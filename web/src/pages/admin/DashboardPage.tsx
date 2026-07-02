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

const statusGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(12rem, 1fr))",
  gap: "var(--atlas-space-4)",
};

export default function DashboardPage() {
  return (
    <section aria-labelledby="admin-dashboard-title" style={pageStyle}>
      <div>
        <p className="eyebrow">Dashboard</p>
        <h1 id="admin-dashboard-title">Admin overview</h1>
        <p className="summary">
          Static placeholder for the private admin workspace. Runtime discovery and live operational metrics are not
          implemented in this issue.
        </p>
      </div>

      <div style={statusGridStyle}>
        <article style={panelStyle}>
          <span className="atlas-status-pill atlas-status-pill--info">Placeholder</span>
          <strong>Generated runs</strong>
          <p style={{ margin: 0, color: "var(--atlas-color-text-muted)" }}>
            No run discovery is performed by this shell.
          </p>
        </article>
        <article style={panelStyle}>
          <span className="atlas-status-pill atlas-status-pill--warning">Unavailable</span>
          <strong>Publication actions</strong>
          <p style={{ margin: 0, color: "var(--atlas-color-text-muted)" }}>
            Publishing remains outside this admin foundation.
          </p>
        </article>
      </div>
    </section>
  );
}
