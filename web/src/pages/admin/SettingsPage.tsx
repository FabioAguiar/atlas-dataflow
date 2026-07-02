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

export default function SettingsPage() {
  return (
    <section aria-labelledby="admin-settings-title" style={pageStyle}>
      <div>
        <p className="eyebrow">Settings</p>
        <h1 id="admin-settings-title">Admin settings</h1>
        <p className="summary">
          Static settings placeholder. Authentication, authorization enforcement, and profile draft behavior are outside
          this issue.
        </p>
      </div>

      <article style={panelStyle}>
        <span className="atlas-status-pill atlas-status-pill--info">Static</span>
        <strong>Profile and access settings are not editable</strong>
        <p style={{ margin: 0, color: "var(--atlas-color-text-muted)" }}>
          The shell can show where future settings will live, but it does not store credentials, update profiles, or
          claim access-control enforcement.
        </p>
      </article>
    </section>
  );
}
