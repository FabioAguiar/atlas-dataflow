import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import HelpPage from "./HelpPage";

describe("HelpPage", () => {
  it("renders truthful Dashboard guidance without implying promotion is available", () => {
    render(<HelpPage />);

    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByText(/is intentionally disabled/)).toBeInTheDocument();
    expect(screen.getByText(/does not create drafts, release/)).toBeInTheDocument();
  });

  it("renders Dataset Admin guidance describing Publish Changes and Visible Publicly as distinct actions", () => {
    render(<HelpPage />);

    expect(screen.getByRole("heading", { name: "Dataset Admin" })).toBeInTheDocument();
    expect(screen.getByText("Save Draft")).toBeInTheDocument();
    expect(screen.getByText("Publish Changes")).toBeInTheDocument();
    expect(screen.getByText("Visible Publicly")).toBeInTheDocument();
    expect(screen.getByText(/do not imply each other/)).toBeInTheDocument();
  });

  it("renders the dataset onboarding path as a manual, multi-step process rather than a numeric limit", () => {
    render(<HelpPage />);

    expect(screen.getByRole("heading", { name: "Public/private boundary and dataset onboarding" })).toBeInTheDocument();
    expect(screen.getByText(/manually operated action/)).toBeInTheDocument();
    expect(screen.getByText(/does not exist yet/)).toBeInTheDocument();
  });

  it("does not retain the previous placeholder framing", () => {
    render(<HelpPage />);

    expect(screen.queryByText(/Placeholder for future operator guidance/)).not.toBeInTheDocument();
  });
});
