import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// M51-03: LoginPage is exercised against a fake Admin auth context so no
// Supabase client is involved. All credentials below are obviously fake.
const authMock = vi.hoisted(() => ({
  signInWithEmailPassword: vi.fn(),
  status: "unauthenticated" as "loading" | "authenticated" | "unauthenticated" | "unrecoverable",
}));

vi.mock("../../auth/AdminAuthContext", () => ({
  useAdminAuth: () => ({
    signInWithEmailPassword: authMock.signInWithEmailPassword,
    signOut: vi.fn(),
    status: authMock.status,
  }),
}));

import LoginPage from "./LoginPage";

function LocationProbe() {
  return <span data-testid="pathname">{useLocation().pathname}</span>;
}

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={["/admin/login"]}>
      <LocationProbe />
      <Routes>
        <Route element={<LoginPage />} path="/admin/login" />
        <Route element={<div>Dashboard route</div>} path="/admin/dashboard" />
      </Routes>
    </MemoryRouter>,
  );
}

function submit(email: string, password: string) {
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: email } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: password } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("LoginPage (M51-03)", () => {
  beforeEach(() => {
    authMock.status = "unauthenticated";
    authMock.signInWithEmailPassword.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("signs in with the entered credentials and lands on /admin/dashboard", async () => {
    authMock.signInWithEmailPassword.mockResolvedValue(true);
    renderLogin();

    submit("operator@example.test", "fake-password");

    await waitFor(() => expect(screen.getByTestId("pathname")).toHaveTextContent("/admin/dashboard"));
    expect(authMock.signInWithEmailPassword).toHaveBeenCalledWith("operator@example.test", "fake-password");
    expect(screen.getByText("Dashboard route")).toBeInTheDocument();
  });

  it("shows only a generic message on failure and clears the password", async () => {
    authMock.signInWithEmailPassword.mockResolvedValue(false);
    renderLogin();

    submit("operator@example.test", "fake-password");

    expect(await screen.findByText("Sign-in failed. Check your credentials and try again.")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toHaveValue("");
    expect(screen.getByTestId("pathname")).toHaveTextContent("/admin/login");
  });

  it("renders a generic unavailable message with a non-submittable form when unrecoverable", () => {
    authMock.status = "unrecoverable";
    renderLogin();

    expect(screen.getByText("Admin sign-in is unavailable.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeDisabled();
    fireEvent.submit(screen.getByRole("button", { name: "Sign in" }).closest("form") as HTMLFormElement);
    expect(authMock.signInWithEmailPassword).not.toHaveBeenCalled();
  });

  it("renders no form while the session is loading", () => {
    authMock.status = "loading";
    const { container } = renderLogin();

    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
    expect(container.querySelector("form")).toBeNull();
  });

  it("redirects an authenticated visitor to /admin/dashboard", () => {
    authMock.status = "authenticated";
    renderLogin();

    expect(screen.getByTestId("pathname")).toHaveTextContent("/admin/dashboard");
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
  });

  it("offers only email and password sign-in, with no excluded account controls", () => {
    const { container } = renderLogin();

    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(container.querySelectorAll("a")).toHaveLength(0);
    expect(
      screen.queryByText(/sign ?up|register|create account|magic link|forgot|reset|recover|google|github|oauth|social|anonymous|guest|role|mfa|two-factor|one-time/i),
    ).not.toBeInTheDocument();
  });
});
