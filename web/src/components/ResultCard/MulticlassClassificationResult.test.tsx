import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import MulticlassClassificationResult from "./MulticlassClassificationResult";
import { GENERIC_MULTICLASS_RESULT_PRESENTATION, type MulticlassClassificationResult as ResultData } from "./types";

const result: ResultData = {
  schema_version: "multiclass-classification-result.v1",
  problem_type: "multiclass_classification",
  predicted_class: { class_id: "b", display_label: "Class B" },
  class_probabilities: [
    { class_id: "a", display_label: "Class A", probability: 0.002 },
    { class_id: "b", display_label: "Class B", probability: 0.6 },
    { class_id: "c", display_label: "Class C", probability: 0.199 },
    { class_id: "d", display_label: "Class D", probability: 0.199 },
  ],
  decision: { strategy: "argmax" },
  model_descriptor: { model_family: "fixture", display_name: "Fixture model" },
};

describe("MulticlassClassificationResult", () => {
  it("renders the prediction, full stable distribution, model, and accessible probabilities without mutation", () => {
    const original = result.class_probabilities.map((entry) => entry.class_id);
    const { container } = render(<MulticlassClassificationResult result={result} presentation={GENERIC_MULTICLASS_RESULT_PRESENTATION} />);
    expect(screen.getAllByText("Class B")).toHaveLength(2);
    expect(screen.getAllByText("60%")).toHaveLength(2);
    expect(screen.getByText("0.2%")).toBeInTheDocument();
    expect(screen.getByText("Fixture model")).toBeInTheDocument();
    expect(screen.getAllByRole("progressbar")).toHaveLength(4);
    expect(container.querySelectorAll(".multiclass-probability-list__item")[1]).toHaveTextContent("Class C");
    expect(container.querySelectorAll(".multiclass-probability-list__item")[2]).toHaveTextContent("Class D");
    expect(result.class_probabilities.map((entry) => entry.class_id)).toEqual(original);
    expect(container).not.toHaveTextContent(/confidence|threshold|risk/i);
  });
});
