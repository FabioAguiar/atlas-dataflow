import type { ReactNode } from "react";
import { NavLink, Outlet } from "react-router-dom";

import atlasLogoSidebar from "../assets/admin/atlas-logo-sidebar.png";
import { AdminSettingsProvider, useAdminSettings } from "./AdminSettingsContext";

type NavItem = {
  end?: boolean;
  icon: ReactNode;
  label: string;
  to: string;
};

const primaryNavItems: NavItem[] = [
  {
    end: true,
    icon: (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z" />
      </svg>
    ),
    label: "Dashboard",
    to: "/admin",
  },
  {
    end: true,
    icon: (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <path d="M4.5 11 12 5l7.5 6" />
        <path d="M7 10.5V20h10v-9.5" />
      </svg>
    ),
    label: "Public Home",
    to: "/",
  },
  {
    icon: (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <path d="M7 3.5h7l3 3V20H7z" />
        <path d="M14 3.5V7h3" />
        <path d="M9.5 11h5M9.5 14h5M9.5 17h3" />
      </svg>
    ),
    label: "Dataset Detail",
    to: "/admin/dataset-admin",
  },
];

const utilityNavItems: NavItem[] = [
  {
    icon: (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <path d="M12 8.3a3.7 3.7 0 1 0 0 7.4 3.7 3.7 0 0 0 0-7.4Z" />
        <path d="M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.5-2.3 1a7.2 7.2 0 0 0-1.8-1L14.5 3h-5l-.3 3a7.2 7.2 0 0 0-1.8 1l-2.3-1-2 3.5 2 1.5a7 7 0 0 0 0 2L3 14.5l2 3.5 2.3-1a7.2 7.2 0 0 0 1.8 1l.4 3h5l.3-3a7.2 7.2 0 0 0 1.8-1l2.3 1 2-3.5-2-1.5c.1-.3.1-.7.1-1Z" />
      </svg>
    ),
    label: "Settings",
    to: "/admin/settings",
  },
  {
    icon: (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <circle cx="12" cy="12" r="9" />
        <path d="M9.7 9a2.4 2.4 0 0 1 4.6 1c0 1.8-2.3 2.1-2.3 4" />
        <path d="M12 17.2h.01" />
      </svg>
    ),
    label: "Help",
    to: "/admin/help",
  },
];

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

function AdminNavGroup({ ariaLabel, className, items }: { ariaLabel: string; className?: string; items: NavItem[] }) {
  return (
    <nav aria-label={ariaLabel} className={["admin-shell__nav", className].filter(Boolean).join(" ")}>
      {items.map((item) => (
        <NavLink
          className={({ isActive }) => ["admin-shell__nav-link", isActive ? "is-active" : ""].filter(Boolean).join(" ")}
          end={item.end}
          key={item.to}
          to={item.to}
        >
          <span aria-hidden="true" className="admin-shell__nav-icon">
            {item.icon}
          </span>
          <span>{item.label}</span>
        </NavLink>
      ))}
    </nav>
  );
}

function AdminProfileBlock() {
  const { displayName } = useAdminSettings();

  return (
    <section aria-label="Current admin profile" className="admin-shell__profile">
      <span aria-hidden="true" className="admin-shell__profile-avatar">
        {getInitials(displayName)}
      </span>
      <span className="admin-shell__profile-copy">
        <strong className="admin-shell__profile-name">{displayName}</strong>
        <span className="admin-shell__profile-role">Admin</span>
      </span>
      <svg
        aria-hidden="true"
        className="admin-shell__profile-caret"
        fill="none"
        height="16"
        viewBox="0 0 24 24"
        width="16"
      >
        <path d="m9 6 6 6-6 6" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
      </svg>
    </section>
  );
}

export default function AdminShell() {
  return (
    <AdminSettingsProvider>
      <div className="admin-shell">
        <aside aria-label="Private admin navigation" className="admin-shell__sidebar">
          <div className="admin-shell__brand">
            <span className="admin-shell__brand-mark">
              <img alt="" src={atlasLogoSidebar} />
            </span>
            <span className="admin-shell__brand-copy">
              <strong className="admin-shell__brand-name">Atlas DataFlow.</strong>
            </span>
          </div>

          <AdminNavGroup ariaLabel="Admin sections" items={primaryNavItems} />
          <AdminNavGroup ariaLabel="Admin utilities" className="admin-shell__nav--utility" items={utilityNavItems} />

          <AdminProfileBlock />
        </aside>

        <div className="admin-shell__workspace">
          <header className="admin-shell__header">
            <div>
              <p className="admin-shell__header-eyebrow">Private administration</p>
              <p className="admin-shell__header-subtitle">Private workspace for governed dataset publication workflows.</p>
            </div>
          </header>

          <main className="admin-shell__main">
            <Outlet />
          </main>
        </div>
      </div>
    </AdminSettingsProvider>
  );
}
