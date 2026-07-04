import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import InferenceResult from "./InferenceResult";

describe("InferenceResult heading/aria-label copy (M39-03)", () => {
  it("renders the design's 'Result' title as both the visible heading and the section's accessible name", () => {
    render(<InferenceResult result={{ label: "positive", confidence: 0.9 }} />);

    expect(screen.getByRole("heading", { level: 3, name: "Result" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Result" })).toBeInTheDocument();
    expect(screen.queryByText("Prediction Result")).not.toBeInTheDocument();
  });
});
