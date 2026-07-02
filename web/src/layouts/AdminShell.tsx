import type { CSSProperties } from "react";
import { NavLink, Outlet } from "react-router-dom";

const navItems = [
  { label: "Dashboard", to: "/admin" },
  { label: "Dataset Admin", to: "/admin/dataset-admin" },
  { label: "Settings", to: "/admin/settings" },
  { label: "Help", to: "/admin/help" },
];

const shellStyle: CSSProperties = {
  minHeight: "100vh",
  display: "flex",
  flexWrap: "wrap",
  background: "var(--atlas-color-canvas)",
};

const sidebarStyle: CSSProperties = {
  flex: "0 1 16rem",
  minHeight: "100vh",
  display: "flex",
  flexDirection: "column",
  gap: "var(--atlas-space-6)",
  borderRight: "1px solid var(--atlas-color-border)",
  padding: "var(--atlas-space-6)",
  background: "var(--atlas-color-surface)",
};

const brandStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-1)",
};

const navStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-2)",
};

const baseNavLinkStyle: CSSProperties = {
  borderRadius: "var(--atlas-radius-md)",
  padding: "var(--atlas-space-3) var(--atlas-space-4)",
  color: "var(--atlas-color-text-muted)",
  fontSize: "var(--atlas-text-sm)",
  fontWeight: 800,
  textDecoration: "none",
};

const profileBlockStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-2)",
  marginTop: "auto",
  border: "1px solid var(--atlas-color-border)",
  borderRadius: "var(--atlas-radius-md)",
  padding: "var(--atlas-space-4)",
  background: "var(--atlas-color-surface-muted)",
};

const workspaceStyle: CSSProperties = {
  flex: "1 1 32rem",
  minWidth: 0,
  display: "grid",
  gridTemplateRows: "auto 1fr",
};

const headerStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  alignItems: "center",
  justifyContent: "space-between",
  gap: "var(--atlas-space-4)",
  minHeight: "4.5rem",
  borderBottom: "1px solid var(--atlas-color-border)",
  padding: "var(--atlas-space-4) var(--atlas-space-8)",
  background: "var(--atlas-color-surface)",
};

const headerControlsStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: "var(--atlas-space-2)",
};

const disabledControlStyle: CSSProperties = {
  minHeight: "2.25rem",
  border: "1px solid var(--atlas-color-border-strong)",
  borderRadius: "var(--atlas-radius-md)",
  padding: "0 var(--atlas-space-3)",
  color: "var(--atlas-color-text-subtle)",
  font: "inherit",
  fontSize: "var(--atlas-text-sm)",
  fontWeight: 700,
  background: "var(--atlas-color-surface-muted)",
  cursor: "not-allowed",
};

const mainStyle: CSSProperties = {
  display: "grid",
  alignContent: "start",
  gap: "var(--atlas-space-6)",
  width: "min(100%, 960px)",
  padding: "var(--atlas-space-8)",
};

export default function AdminShell() {
  return (
    <div style={shellStyle}>
      <aside aria-label="Private admin navigation" style={sidebarStyle}>
        <div style={brandStyle}>
          <strong style={{ color: "var(--atlas-color-text)", fontSize: "var(--atlas-text-lg)" }}>
            Atlas Admin
          </strong>
          <span style={{ color: "var(--atlas-color-text-subtle)", fontSize: "var(--atlas-text-sm)" }}>
            Internal shell
          </span>
        </div>

        <nav aria-label="Admin sections" style={navStyle}>
          {navItems.map((item) => (
            <NavLink
              end={item.to === "/admin"}
              key={item.to}
              style={({ isActive }) => ({
                ...baseNavLinkStyle,
                background: isActive ? "var(--atlas-color-accent-muted)" : "transparent",
                color: isActive ? "var(--atlas-color-accent-strong)" : "var(--atlas-color-text-muted)",
              })}
              to={item.to}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <section aria-label="Current admin profile" style={profileBlockStyle}>
          <span style={{ color: "var(--atlas-color-text-subtle)", fontSize: "var(--atlas-text-xs)", fontWeight: 800 }}>
            PROFILE
          </span>
          <strong style={{ color: "var(--atlas-color-text)" }}>Internal operator</strong>
          <span style={{ color: "var(--atlas-color-text-muted)", fontSize: "var(--atlas-text-sm)" }}>
            Static shell state. Profile editing is not available here.
          </span>
        </section>
      </aside>

      <div style={workspaceStyle}>
        <header style={headerStyle}>
          <div>
            <p
              style={{
                margin: 0,
                color: "var(--atlas-color-accent)",
                fontSize: "var(--atlas-text-sm)",
                fontWeight: 800,
                textTransform: "uppercase",
              }}
            >
              Private administration
            </p>
            <p style={{ margin: 0, color: "var(--atlas-color-text-muted)" }}>
              Safe navigation structure for future admin workflows.
            </p>
          </div>
          <div aria-label="Admin controls" style={headerControlsStyle}>
            <button disabled style={disabledControlStyle} type="button">
              Run discovery private
            </button>
            <button disabled style={disabledControlStyle} type="button">
              Publishing unavailable
            </button>
          </div>
        </header>

        <main style={mainStyle}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
