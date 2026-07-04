import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { useEffect, type ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
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

function renderAdminShell(indexElement: ReactNode = null) {
  return render(
    <MemoryRouter initialEntries={["/admin"]}>
      <Routes>
        <Route element={<AdminShell />} path="/admin">
          <Route element={indexElement} index />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("AdminShell profile block", () => {
  it("shows the default fallback display name before any settings are loaded", () => {
    renderAdminShell();

    expect(screen.getByLabelText("Current admin profile")).toHaveTextContent("Internal operator");
  });

  it("reflects a display name set on the shared admin settings context without a page reload", async () => {
    renderAdminShell(<DisplayNameSetter name="New operator name" />);

    expect(await screen.findByLabelText("Current admin profile")).toHaveTextContent("New operator name");
  });
});
