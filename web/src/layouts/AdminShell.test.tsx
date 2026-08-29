import "@testing-library/jest-dom/vitest";
import { render, screen, within } from "@testing-library/react";
import { useEffect, type ReactNode } from "react";
import { MemoryRouter, Navigate, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import AdminShell from "./AdminShell";
import { useAdminSettings } from "./AdminSettingsContext";

function DisplayNameSetter({ name }: { name: string }) {
  const { setDisplayName } = useAdminSettings();
  useEffect(() => {
    setDisplayName(name);
  }, [name, setDisplayName]);
  return null;
}

// Project Spec S0278: the shell is exercised under the canonical Admin route
// structure -- bare /admin redirects to /admin/dashboard, and Dashboard /
// Dataset Detail each resolve at their single canonical path.
function renderAdminShell(indexElement: ReactNode = null, initialPath = "/admin/dashboard") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route element={<AdminShell />} path="/admin">
          <Route element={<Navigate replace to="/admin/dashboard" />} index />
          <Route element={indexElement} path="dashboard" />
          <Route element={null} path="dataset-detail" />
          <Route element={null} path="settings" />
          <Route element={null} path="help" />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("AdminShell profile block", () => {
  it("renders the design-aligned admin brand and navigation labels", () => {
    renderAdminShell();

    expect(screen.getByText("Atlas DataFlow")).toBeInTheDocument();
    expect(screen.getAllByText("Admin").length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute("href", "/admin/dashboard");
    expect(screen.getByRole("link", { name: "Public Home" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Dataset Detail" })).toHaveAttribute("href", "/admin/dataset-detail");
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/admin/settings");
    expect(screen.getByRole("link", { name: "Help" })).toHaveAttribute("href", "/admin/help");
  });

  it("marks only the Dashboard link active at its canonical route", () => {
    renderAdminShell(null, "/admin/dashboard");

    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Dataset Detail" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("link", { name: "Settings" })).not.toHaveAttribute("aria-current");
  });

  it("marks the Dataset Detail link active at its canonical route without leaking to Dashboard", () => {
    renderAdminShell(null, "/admin/dataset-detail");

    expect(screen.getByRole("link", { name: "Dataset Detail" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Dashboard" })).not.toHaveAttribute("aria-current");
  });

  it("renders the Atlas logo brand mark as a decorative image", () => {
    const { container } = renderAdminShell();

    const brandImage = container.querySelector(".admin-shell__brand-mark img");
    expect(brandImage).not.toBeNull();
    expect(brandImage).toHaveAttribute("alt", "");
  });

  it("renders a decorative icon inside every navigation link", () => {
    renderAdminShell();

    const labels = ["Dashboard", "Public Home", "Dataset Detail", "Settings", "Help"];
    for (const label of labels) {
      const link = screen.getByRole("link", { name: label });
      expect(link.querySelector("svg")).not.toBeNull();
    }
  });

  it("groups navigation into a primary section and a utility section", () => {
    renderAdminShell();

    const primaryNav = screen.getByRole("navigation", { name: "Admin sections" });
    const utilityNav = screen.getByRole("navigation", { name: "Admin utilities" });

    for (const label of ["Dashboard", "Public Home", "Dataset Detail"]) {
      expect(within(primaryNav).getByRole("link", { name: label })).toBeInTheDocument();
    }
    for (const label of ["Settings", "Help"]) {
      expect(within(utilityNav).getByRole("link", { name: label })).toBeInTheDocument();
    }
  });

  it("shows the default fallback display name before any settings are loaded", () => {
    renderAdminShell();

    expect(screen.getByLabelText("Current admin profile")).toHaveTextContent("Internal operator");
    expect(screen.getByLabelText("Current admin profile")).toHaveTextContent("Admin");
  });

  it("reflects a display name set on the shared admin settings context without a page reload", async () => {
    renderAdminShell(<DisplayNameSetter name="New operator name" />);

    expect(await screen.findByLabelText("Current admin profile")).toHaveTextContent("New operator name");
    expect(screen.getByLabelText("Current admin profile")).toHaveTextContent("NO");
  });

  it("does not expose misleading disabled global run or publishing controls", () => {
    renderAdminShell();

    expect(screen.queryByRole("button", { name: "Run discovery private" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Publishing unavailable" })).not.toBeInTheDocument();
  });
});
