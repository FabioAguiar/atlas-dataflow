import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import SettingsPage from "./SettingsPage";

type MockResponse = {
  ok: boolean;
  status: number;
  json: () => Promise<unknown>;
};

function jsonResponse(body: unknown, status = 200): MockResponse {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

function installFetchMock(options: { rejectSave?: boolean } = {}) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);

    if (url.endsWith("/admin/settings") && init?.method === "PUT") {
      if (options.rejectSave) {
        return jsonResponse(
          {
            error_type: "admin_settings_invalid",
            error_code: "ADMIN_SETTINGS_INVALID",
            message: "The admin settings payload failed validation.",
            errors: [{ field: "display_name", code: "SCHEMA_VALIDATION_ERROR", message: "display_name is required." }],
          },
          422,
        );
      }
      const body = typeof init.body === "string" ? (JSON.parse(init.body) as { display_name?: string }) : {};
      return jsonResponse({ saved: true, settings: { display_name: body.display_name ?? "" }, errors: [] });
    }
    if (url.endsWith("/admin/settings")) {
      return jsonResponse({ settings: { display_name: "Internal operator" } });
    }

    return jsonResponse({}, 404);
  });

  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function loadSettings() {
  fireEvent.change(screen.getByLabelText("Operator token"), { target: { value: "operator-token" } });
  fireEvent.click(screen.getByRole("button", { name: "Load settings" }));
  await screen.findByText("Current display name loaded from the private/admin settings endpoint.");
}

describe("SettingsPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the display-name-only edit form with no unsupported settings controls", () => {
    installFetchMock();
    render(<SettingsPage />);

    expect(screen.getByRole("heading", { name: "Admin settings" })).toBeInTheDocument();
    expect(screen.getByLabelText("Display name")).toBeInTheDocument();
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/account/i)).not.toBeInTheDocument();
  });

  it("requires an operator token before loading settings", () => {
    installFetchMock();
    render(<SettingsPage />);

    fireEvent.click(screen.getByRole("button", { name: "Load settings" }));

    expect(screen.getByText("Enter the operator token to load Admin Settings.")).toBeInTheDocument();
  });

  it("loads the current display name through GET /admin/settings", async () => {
    installFetchMock();
    render(<SettingsPage />);

    await loadSettings();

    expect(screen.getByLabelText("Display name")).toHaveValue("Internal operator");
  });

  it("saves an edited display name through PUT /admin/settings", async () => {
    installFetchMock();
    render(<SettingsPage />);

    await loadSettings();
    fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "New operator name" } });
    fireEvent.click(screen.getByRole("button", { name: "Save display name" }));

    expect(await screen.findByText("Display name saved.")).toBeInTheDocument();
    expect(screen.getByLabelText("Display name")).toHaveValue("New operator name");
  });

  it("surfaces backend validation errors without clearing the entered display name", async () => {
    installFetchMock({ rejectSave: true });
    render(<SettingsPage />);

    await loadSettings();
    fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save display name" }));

    expect(await screen.findByText("Admin settings rejected by backend validation")).toBeInTheDocument();
    expect(screen.getByText(/display_name - SCHEMA_VALIDATION_ERROR/)).toBeInTheDocument();
  });
});
