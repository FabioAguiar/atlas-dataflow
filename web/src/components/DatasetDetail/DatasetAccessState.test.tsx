import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import DatasetAccessState, { classifyDatasetAccessError } from "./DatasetAccessState";

afterEach(() => {
  cleanup();
});

function renderState(kind: "maintenance" | "not_found" | "unavailable") {
  return render(
    <MemoryRouter>
      <DatasetAccessState kind={kind} />
    </MemoryRouter>,
  );
}

describe("DatasetAccessState", () => {
  it("renders the maintenance heading, body, and a keyboard-accessible Back to datasets action", () => {
    renderState("maintenance");

    expect(screen.getByRole("heading", { level: 1, name: "Dataset page under maintenance" })).toBeInTheDocument();
    expect(
      screen.getByText("This dataset page is temporarily unavailable. Please try again later."),
    ).toBeInTheDocument();

    const action = screen.getByRole("link", { name: "Back to datasets" });
    expect(action).toBeInTheDocument();
    expect(action).toHaveAttribute("href", "/");
  });

  it("renders the not-found heading, body, and a Back to datasets action", () => {
    renderState("not_found");

    expect(screen.getByRole("heading", { level: 1, name: "Dataset not found" })).toBeInTheDocument();
    expect(
      screen.getByText("The dataset or link you tried to access does not exist."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to datasets" })).toBeInTheDocument();
  });

  it("renders the generic unavailable heading and body without a Back to datasets action", () => {
    renderState("unavailable");

    expect(
      screen.getByRole("heading", { level: 1, name: "Dataset information is currently unavailable" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Please try again later.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Back to datasets" })).not.toBeInTheDocument();
  });

  it("never renders private diagnostic content (dataset name, slug, visibility, or review state)", () => {
    renderState("maintenance");

    expect(screen.queryByText(/telco/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/visibility/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/review/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/release/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/admin/i)).not.toBeInTheDocument();
  });
});

describe("classifyDatasetAccessError", () => {
  it("classifies DATASET_MAINTENANCE as maintenance", () => {
    expect(classifyDatasetAccessError({ error_type: "dataset_maintenance", error_code: "DATASET_MAINTENANCE", message: "x" })).toBe(
      "maintenance",
    );
  });

  it("classifies DATASET_NOT_FOUND as not_found", () => {
    expect(classifyDatasetAccessError({ error_type: "dataset_not_found", error_code: "DATASET_NOT_FOUND", message: "x" })).toBe(
      "not_found",
    );
  });

  it("classifies every other error_code as unavailable, never by status alone", () => {
    expect(classifyDatasetAccessError({ error_type: "release_unavailable", error_code: "RELEASE_UNAVAILABLE", message: "x" })).toBe(
      "unavailable",
    );
    expect(classifyDatasetAccessError({ error_type: "registry_unavailable", error_code: "REGISTRY_UNAVAILABLE", message: "x" })).toBe(
      "unavailable",
    );
    expect(classifyDatasetAccessError({ error_type: "unexpected_error", error_code: "UNEXPECTED_ERROR", message: "x" })).toBe(
      "unavailable",
    );
  });

  it("classifies a malformed or non-object body as unavailable", () => {
    expect(classifyDatasetAccessError(null)).toBe("unavailable");
    expect(classifyDatasetAccessError(undefined)).toBe("unavailable");
    expect(classifyDatasetAccessError("not json")).toBe("unavailable");
    expect(classifyDatasetAccessError([])).toBe("unavailable");
    expect(classifyDatasetAccessError({})).toBe("unavailable");
  });
});
