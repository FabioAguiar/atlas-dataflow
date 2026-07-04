import type { CSSProperties } from "react";
import { NavLink, Outlet } from "react-router-dom";

import { AdminSettingsProvider, useAdminSettings } from "./AdminSettingsContext";

const navItems = [
  { end: true, label: "Dashboard", to: "/admin" },
  { end: true, label: "Public Home", to: "/" },
  { label: "Dataset Detail", to: "/admin/dataset-admin" },
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
  flex: "0 1 clamp(13.5rem, 18vw, 16rem)",
  minHeight: "100vh",
  display: "flex",
  flexDirection: "column",
  gap: "clamp(var(--atlas-space-4), 3vh, var(--atlas-space-6))",
  borderRight: "1px solid var(--atlas-color-border)",
  padding: "clamp(var(--atlas-space-4), 2.5vw, var(--atlas-space-6))",
  background: "var(--atlas-color-surface)",
};

const brandStyle: CSSProperties = {
  display: "flex",
  gap: "var(--atlas-space-3)",
  alignItems: "center",
};

const brandMarkStyle: CSSProperties = {
  display: "grid",
  placeItems: "center",
  width: "2.25rem",
  height: "2.25rem",
  borderRadius: "var(--atlas-radius-md)",
  color: "var(--atlas-color-accent-strong)",
  fontSize: "var(--atlas-text-sm)",
  fontWeight: 900,
  background: "var(--atlas-color-accent-muted)",
};

const brandCopyStyle: CSSProperties = {
  display: "grid",
  gap: "0.125rem",
};

const navStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-2)",
};

const baseNavLinkStyle: CSSProperties = {
  borderRadius: "var(--atlas-radius-md)",
  padding: "clamp(var(--atlas-space-2), 1.5vh, var(--atlas-space-3)) var(--atlas-space-4)",
  color: "var(--atlas-color-text-muted)",
  fontSize: "var(--atlas-text-sm)",
  fontWeight: 800,
  textDecoration: "none",
};

const profileBlockStyle: CSSProperties = {
  display: "flex",
  gap: "var(--atlas-space-3)",
  alignItems: "center",
  marginTop: "auto",
  border: "1px solid var(--atlas-color-border)",
  borderRadius: "var(--atlas-radius-md)",
  padding: "var(--atlas-space-3)",
  background: "var(--atlas-color-surface-muted)",
};

const profileAvatarStyle: CSSProperties = {
  display: "grid",
  placeItems: "center",
  width: "2rem",
  height: "2rem",
  flex: "0 0 auto",
  borderRadius: "50%",
  color: "var(--atlas-color-accent-strong)",
  fontSize: "var(--atlas-text-xs)",
  fontWeight: 900,
  background: "var(--atlas-color-accent-muted)",
};

const profileCopyStyle: CSSProperties = {
  display: "grid",
  minWidth: 0,
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
  minHeight: "4rem",
  borderBottom: "1px solid var(--atlas-color-border)",
  padding: "var(--atlas-space-4) clamp(var(--atlas-space-5), 4vw, var(--atlas-space-8))",
  background: "var(--atlas-color-surface)",
};

const mainStyle: CSSProperties = {
  display: "grid",
  alignContent: "start",
  gap: "clamp(var(--atlas-space-4), 3vh, var(--atlas-space-6))",
  width: "min(100%, 1040px)",
  padding: "clamp(var(--atlas-space-5), 4vw, var(--atlas-space-8))",
};

function getInitials(name: string): string {
  const initials = name
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");

  return initials || "AD";
}

function AdminProfileBlock() {
  const { displayName } = useAdminSettings();

  return (
    <section aria-label="Current admin profile" style={profileBlockStyle}>
      <span aria-hidden="true" style={profileAvatarStyle}>
        {getInitials(displayName)}
      </span>
      <span style={profileCopyStyle}>
        <strong style={{ color: "var(--atlas-color-text)", overflow: "hidden", textOverflow: "ellipsis" }}>
          {displayName}
        </strong>
        <span style={{ color: "var(--atlas-color-text-muted)", fontSize: "var(--atlas-text-sm)" }}>Admin</span>
      </span>
    </section>
  );
}

export default function AdminShell() {
  return (
    <AdminSettingsProvider>
      <div style={shellStyle}>
        <aside aria-label="Private admin navigation" style={sidebarStyle}>
          <div style={brandStyle}>
            <span aria-hidden="true" style={brandMarkStyle}>
              AD
            </span>
            <span style={brandCopyStyle}>
              <strong style={{ color: "var(--atlas-color-text)", fontSize: "var(--atlas-text-lg)" }}>
                Atlas DataFlow
              </strong>
              <span style={{ color: "var(--atlas-color-text-subtle)", fontSize: "var(--atlas-text-sm)" }}>
                Admin
              </span>
            </span>
          </div>

          <nav aria-label="Admin sections" style={navStyle}>
            {navItems.map((item) => (
              <NavLink
                end={item.end}
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

          <AdminProfileBlock />
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
                Private workspace for governed dataset publication workflows.
              </p>
            </div>
          </header>

          <main style={mainStyle}>
            <Outlet />
          </main>
        </div>
      </div>
    </AdminSettingsProvider>
  );
}
