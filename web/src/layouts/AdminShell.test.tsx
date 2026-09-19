import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useEffect, type ReactNode } from "react";
import { MemoryRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

// M51-03: AdminShell reads the optional Admin session context. The hook is
// mocked so existing stand-alone cases keep rendering with no provider (null)
// and the Sign out cases can supply a fake provider value.
const authMock = vi.hoisted(() => ({
  value: null as null | { signInWithEmailPassword: () => Promise<boolean>; signOut: () => Promise<void>; status: string },
}));

vi.mock("../auth/AdminAuthContext", () => ({
  useOptionalAdminAuth: () => authMock.value,
}));

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

describe("AdminShell Sign out (M51-03)", () => {
  afterEach(() => {
    authMock.value = null;
  });

  function LocationProbe() {
    return <span data-testid="pathname">{useLocation().pathname}</span>;
  }

  function renderWithLogin(indexElement: ReactNode = null) {
    return render(
      <MemoryRouter initialEntries={["/admin/dashboard"]}>
        <LocationProbe />
        <Routes>
          <Route element={<div>Login route</div>} path="/admin/login" />
          <Route element={<AdminShell />} path="/admin">
            <Route element={indexElement} path="dashboard" />
          </Route>
        </Routes>
      </MemoryRouter>,
    );
  }

  it("renders no Sign out control without an Admin auth provider", () => {
    renderWithLogin();

    expect(screen.queryByRole("button", { name: "Sign out" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Current admin profile")).toBeInTheDocument();
  });

  it("renders Sign out beside the profile block when a provider is present, and signs out to /admin/login", async () => {
    const signOut = vi.fn(async () => undefined);
    authMock.value = { signInWithEmailPassword: async () => true, signOut, status: "authenticated" };
    renderWithLogin();

    expect(screen.getByLabelText("Current admin profile")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));

    await waitFor(() => expect(screen.getByTestId("pathname")).toHaveTextContent("/admin/login"));
    expect(signOut).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Login route")).toBeInTheDocument();
  });

  it("does not replace the profile display name with session data", () => {
    authMock.value = {
      email: "fake-operator@example.test",
      signInWithEmailPassword: async () => true,
      signOut: async () => undefined,
      status: "authenticated",
    } as unknown as NonNullable<typeof authMock.value>;
    renderWithLogin(<DisplayNameSetter name="Ada Lovelace" />);

    const profile = screen.getByLabelText("Current admin profile");
    expect(within(profile).getByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.queryByText(/fake-operator@example\.test/)).not.toBeInTheDocument();
  });
});
