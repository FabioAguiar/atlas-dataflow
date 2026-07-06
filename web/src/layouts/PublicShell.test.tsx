import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import PublicShell from "./PublicShell";

function mockMatchMedia(matches: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

function renderPublicShell() {
  return render(
    <MemoryRouter>
      <PublicShell>
        <div>content</div>
      </PublicShell>
    </MemoryRouter>,
  );
}

function getOverlay() {
  return document.querySelector(".public-shell__nav-overlay");
}

describe("PublicShell nav overlay responsive behavior", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("defaults the nav open on desktop viewports", () => {
    mockMatchMedia(true);
    renderPublicShell();

    expect(screen.getByLabelText("Ocultar navegação")).toBeInTheDocument();
  });

  it("defaults the nav closed on mobile viewports", () => {
    mockMatchMedia(false);
    renderPublicShell();

    const toggle = screen.getByLabelText("Mostrar navegação");
    expect(toggle).toBeInTheDocument();
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveAttribute("aria-controls", "public-shell-nav");
  });

  it("does not render the nav overlay on desktop even though the nav is open by default", () => {
    mockMatchMedia(true);
    renderPublicShell();

    expect(getOverlay()).not.toBeInTheDocument();
  });

  it("renders the nav overlay on mobile once the nav is opened", () => {
    mockMatchMedia(false);
    renderPublicShell();

    fireEvent.click(screen.getByLabelText("Mostrar navegação"));

    expect(getOverlay()).toBeInTheDocument();
    expect(screen.getByLabelText("Ocultar navegação")).toHaveAttribute("aria-expanded", "true");
  });

  it("closes the nav when the mobile overlay is clicked", () => {
    mockMatchMedia(false);
    renderPublicShell();

    fireEvent.click(screen.getByLabelText("Mostrar navegação"));
    const overlay = getOverlay();
    expect(overlay).toBeInTheDocument();

    fireEvent.click(overlay as Element);

    expect(getOverlay()).not.toBeInTheDocument();
    expect(screen.getByLabelText("Mostrar navegação")).toBeInTheDocument();
  });

  it("closes the mobile nav when a nav link is clicked", () => {
    mockMatchMedia(false);
    renderPublicShell();

    fireEvent.click(screen.getByLabelText("Mostrar navegação"));
    expect(getOverlay()).toBeInTheDocument();

    fireEvent.click(screen.getByRole("link", { name: "Home" }));

    expect(getOverlay()).not.toBeInTheDocument();
    expect(screen.getByLabelText("Mostrar navegação")).toHaveAttribute("aria-expanded", "false");
  });

  it("closes the mobile nav with Escape and returns focus to the toggle", () => {
    mockMatchMedia(false);
    renderPublicShell();

    fireEvent.click(screen.getByLabelText("Mostrar navegação"));
    const toggle = screen.getByLabelText("Ocultar navegação");
    expect(getOverlay()).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });

    expect(getOverlay()).not.toBeInTheDocument();
    expect(screen.getByLabelText("Mostrar navegação")).toHaveFocus();
    expect(toggle).toHaveAttribute("aria-controls", "public-shell-nav");
  });

  it("preserves the existing nav item set and labels", () => {
    mockMatchMedia(true);
    renderPublicShell();

    expect(screen.getByRole("link", { name: "Home" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Projetos" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "GitHub" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Contato" })).toBeInTheDocument();
  });

  it("collapses the rail when the desktop nav toggle is clicked", () => {
    mockMatchMedia(true);
    const { container } = renderPublicShell();

    expect(container.querySelector(".public-shell")).toHaveClass("public-shell--nav-open");

    fireEvent.click(screen.getByLabelText("Ocultar navegação"));

    expect(container.querySelector(".public-shell")).not.toHaveClass("public-shell--nav-open");
    expect(screen.getByLabelText("Mostrar navegação")).toHaveAttribute("aria-expanded", "false");
  });
});
