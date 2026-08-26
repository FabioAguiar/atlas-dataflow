import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import InferenceForm, {
  normalizeAdminInferenceGuidance,
  normalizeInferenceRuntimeDiagnostic,
  normalizeInferenceValidationIssues,
  type ContractPayload,
  type ForecastingContractPayload,
  type InferenceExecutionResult,
  type InferenceExecutorPayload,
  type InferenceLifecycleEvent,
} from "./InferenceForm";
import type {
  BinaryResultContract,
  BinaryResultPresentation,
  ResultContract,
  UnivariateForecastingResultPresentation,
} from "../ResultCard/types";

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

// Test-only narrowing helper: these tests exercise a scalar contract, so the
// executor payload is always the scalar shape at runtime -- this cast only
// avoids re-declaring InferenceExecutorPayload's full union at each mock
// call-args assertion site.
function asScalarPayload(payload: InferenceExecutorPayload): Record<string, unknown> {
  return payload as Record<string, unknown>;
}

const slug = "synthetic-demo-dataset";

const contract: ContractPayload = {
  schema_version: "1.0.0",
  features: [
    {
      name: "tenure",
      label: "Tenure",
      input_type: "number",
      optional: true,
      display_order: 1,
    },
  ],
};

const availableContract: BinaryResultContract = {
  status: "available",
  semantics: {
    schema_version: "binary-result-semantics.v1",
    problem_type: "binary_classification",
    result_schema_version: "binary-classification-result.v1",
    primary_output: "positive_class_probability",
    positive_class: { class_id: "Yes", event_label: "Churn" },
    negative_class: { class_id: "No" },
    decision: { threshold: 0.5 },
    interpretation: {
      preset: "risk",
      bands: [
        { band_id: "low", lower_bound: 0, upper_bound: 0.35 },
        { band_id: "medium", lower_bound: 0.35, upper_bound: 0.65 },
        { band_id: "high", lower_bound: 0.65, upper_bound: 1.0 },
      ],
    },
    model_descriptor: { model_family: "gradient_boosting", display_name: "Gradient Boosting" },
  },
};

const unavailableContract: BinaryResultContract = {
  status: "unavailable",
  reason: "binary_result_semantics_unavailable",
};

const presentation: BinaryResultPresentation = {
  schema_version: "binary-result-presentation.v1",
  positive_class_probability_label: "Churn probability",
  predicted_outcome_label: "Predicted outcome",
  positive_outcome_copy: "Likely to churn",
  negative_outcome_copy: "Unlikely to churn",
  model_section_label: "Model",
  interpretation: {
    preset: "risk",
    labels: { high: "High risk", medium: "Medium risk", low: "Low risk" },
  },
};

const validResult = {
  schema_version: "binary-classification-result.v1",
  problem_type: "binary_classification",
  predicted_class: { class_id: "Yes" },
  positive_class: { class_id: "Yes", event_label: "Churn" },
  positive_class_probability: 0.68,
  class_probabilities: [
    { class_id: "No", probability: 0.32 },
    { class_id: "Yes", probability: 0.68 },
  ],
  decision: { threshold: 0.5, predicted_positive: true },
  interpretation: {
    preset: "risk",
    band_id: "high",
    bands: availableContract.semantics.interpretation.bands,
  },
  model_descriptor: { model_family: "gradient_boosting", display_name: "Gradient Boosting" },
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("InferenceForm multiclass result dispatch (S0214)", () => {
  const multiclassContract: ResultContract = {
    status: "available",
    semantics: {
      schema_version: "multiclass-result-semantics.v1",
      problem_type: "multiclass_classification",
      result_schema_version: "multiclass-classification-result.v1",
      classes: ["a", "b", "c"].map((class_id) => ({ class_id, display_label: `Class ${class_id.toUpperCase()}` })),
      primary_output: "predicted_class",
      probability_output: "class_probabilities",
      decision: { strategy: "argmax" },
      model_descriptor: { model_family: "fixture", display_name: "Fixture model" },
    },
  };
  const multiclassResult = {
    schema_version: "multiclass-classification-result.v1",
    problem_type: "multiclass_classification",
    predicted_class: { class_id: "b", display_label: "Class B" },
    class_probabilities: [
      { class_id: "a", display_label: "Class A", probability: 0.2 },
      { class_id: "b", display_label: "Class B", probability: 0.6 },
      { class_id: "c", display_label: "Class C", probability: 0.2 },
    ],
    decision: { strategy: "argmax" },
    model_descriptor: { model_family: "fixture", display_name: "Fixture model" },
  };

  it("renders a contract-matched multiclass result and emits success", async () => {
    const events: InferenceLifecycleEvent[] = [];
    render(<InferenceForm contract={contract} slug={slug} resultContract={multiclassContract}
      executeInference={async () => ({ ok: true, result: multiclassResult })}
      onLifecycleEvent={(event) => events.push(event)} initialResultProbability={0} />);
    expect(screen.getByText("Submit the form to see the prediction.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    expect(await screen.findAllByText("Class B")).toHaveLength(2);
    expect(screen.getAllByText("60%")).toHaveLength(2);
    expect(events).toEqual([{ type: "started" }, { type: "succeeded" }]);
  });

  it("fails safely when the response family does not match", async () => {
    render(<InferenceForm contract={contract} slug={slug} resultContract={multiclassContract}
      executeInference={async () => ({ ok: true, result: validResult })} />);
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong");
  });
});

describe("InferenceForm continuous regression result dispatch (S0229)", () => {
  const regressionContract: ResultContract = {
    status: "available",
    semantics: {
      schema_version: "continuous-regression-result-semantics.v1",
      problem_type: "continuous_regression",
      result_schema_version: "continuous-regression-result.v1",
      primary_output: "predicted_value",
      output_value_kind: "continuous_numeric",
      model_descriptor: { model_family: "gradient_boosting", display_name: "Gradient Boosting Regressor" },
    },
  };
  const regressionResult = {
    schema_version: "continuous-regression-result.v1",
    problem_type: "continuous_regression",
    predicted_value: 42.73,
    model_descriptor: { model_family: "gradient_boosting", display_name: "Gradient Boosting Regressor" },
  };

  it("enables submit and renders a contract-matched continuous regression result with no fabricated initial prediction", async () => {
    const events: InferenceLifecycleEvent[] = [];
    render(<InferenceForm contract={contract} slug={slug} resultContract={regressionContract}
      executeInference={async () => ({ ok: true, result: regressionResult })}
      onLifecycleEvent={(event) => events.push(event)} initialResultProbability={0} />);
    expect(screen.getByRole("button", { name: "Submit" })).not.toBeDisabled();
    // Project Spec S0229: continuous regression behaves like multiclass in
    // idle state -- initialResultProbability is binary-only and must never
    // fabricate a regression card.
    expect(screen.getByText("Submit the form to see the prediction.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    expect(await screen.findByText("42.73")).toBeInTheDocument();
    expect(screen.getByText("Gradient Boosting Regressor")).toBeInTheDocument();
    expect(events).toEqual([{ type: "started" }, { type: "succeeded" }]);
  });

  it("fails safely when the response family does not match (binary result against a regression contract)", async () => {
    render(<InferenceForm contract={contract} slug={slug} resultContract={regressionContract}
      executeInference={async () => ({ ok: true, result: validResult })} />);
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong");
  });

  it("fails safely for a non-finite predicted_value", async () => {
    render(<InferenceForm contract={contract} slug={slug} resultContract={regressionContract}
      executeInference={async () => ({ ok: true, result: { ...regressionResult, predicted_value: Number.POSITIVE_INFINITY } })} />);
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong");
  });

  it("fails safely for a boolean predicted_value", async () => {
    render(<InferenceForm contract={contract} slug={slug} resultContract={regressionContract}
      executeInference={async () => ({ ok: true, result: { ...regressionResult, predicted_value: true } })} />);
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong");
  });

  it("fails safely for a model descriptor mismatch against the active contract", async () => {
    render(<InferenceForm contract={contract} slug={slug} resultContract={regressionContract}
      executeInference={async () => ({
        ok: true,
        result: { ...regressionResult, model_descriptor: { model_family: "random_forest", display_name: "Random Forest Regressor" } },
      })} />);
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong");
  });

  it("fails safely for a wrong result schema version", async () => {
    render(<InferenceForm contract={contract} slug={slug} resultContract={regressionContract}
      executeInference={async () => ({ ok: true, result: { ...regressionResult, schema_version: "continuous-regression-result.v2" } })} />);
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong");
  });

  it("fails safely for extra/unknown technical keys", async () => {
    render(<InferenceForm contract={contract} slug={slug} resultContract={regressionContract}
      executeInference={async () => ({ ok: true, result: { ...regressionResult, confidence: 0.9 } })} />);
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong");
  });
});

describe("InferenceForm private numeric guidance (Project Spec S0148)", () => {
  it("renders decimal min/max/step and associates description plus range guidance", () => {
    const describedContract: ContractPayload = {
      ...contract,
      features: [{ ...contract.features[0], description: "Months as a customer." }],
    };
    render(
      <InferenceForm
        contract={describedContract}
        slug={slug}
        previewMode
        adminInferenceGuidance={[
          { field_name: "tenure", required: false, numeric_domain: { min: 18.25, max: 118.75 } },
        ]}
      />,
    );

    const input = screen.getByLabelText("Tenure");
    expect(input).toHaveAttribute("min", "18.25");
    expect(input).toHaveAttribute("max", "118.75");
    expect(input).toHaveAttribute("step", "any");
    expect(screen.getByText("Accepted range: 18.25 to 118.75.")).toBeInTheDocument();
    expect(input).toHaveAttribute("aria-describedby", "field-tenure-helper field-tenure-range");
  });

  it("keeps numeric step any without inventing bounds when guidance is absent", () => {
    render(<InferenceForm contract={contract} slug={slug} previewMode />);
    expect(screen.getByLabelText("Tenure")).toHaveAttribute("step", "any");
    expect(screen.getByLabelText("Tenure")).not.toHaveAttribute("min");
    expect(screen.getByLabelText("Tenure")).not.toHaveAttribute("max");
  });

  it("drops unknown, duplicate, non-finite, inverted, and non-number domains", () => {
    const mixedContract: ContractPayload = {
      schema_version: "1.0.0",
      features: [
        ...contract.features,
        { name: "auto_pay", label: "AutoPay", input_type: "checkbox", optional: true, display_order: 2 },
      ],
    };
    expect(normalizeAdminInferenceGuidance([
      { field_name: "missing", required: true, numeric_domain: { min: 1 } },
      { field_name: "tenure", required: false, numeric_domain: { min: 10, max: 1 } },
      { field_name: "tenure", required: false, numeric_domain: { min: 2 } },
      { field_name: "auto_pay", required: true, numeric_domain: { min: 0, max: 1 } },
    ], mixedContract.features)).toEqual([
      { field_name: "tenure", required: false },
      { field_name: "auto_pay", required: true },
    ]);
  });
});

describe("InferenceForm public execution (Project Spec S0112)", () => {
  it("renders the idle ResultCardShell alongside the form when the result contract is available", () => {
    render(
      <InferenceForm
        contract={contract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
      />,
    );

    expect(screen.getByText("Submit the form to see the prediction.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Submit" })).toBeEnabled();
  });

  it("disables submission and shows the unavailable shell when the result contract is unavailable, without removing the input form", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(<InferenceForm contract={contract} slug={slug} resultContract={unavailableContract} />);

    expect(
      screen.getByText("This active release does not currently expose a compatible result."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();
    expect(screen.getByLabelText("Tenure")).toBeInTheDocument();
  });

  it("never issues the POST request while the result contract is unavailable, even if the form is submitted directly", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const { container } = render(
      <InferenceForm contract={contract} slug={slug} resultContract={unavailableContract} />,
    );

    fireEvent.submit(container.querySelector("form")!);

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    ["missing negative class", { ...availableContract, semantics: { ...availableContract.semantics, negative_class: undefined } }],
    ["blank negative class", { ...availableContract, semantics: { ...availableContract.semantics, negative_class: { class_id: " " } } }],
    ["equal class identities", { ...availableContract, semantics: { ...availableContract.semantics, negative_class: { class_id: "Yes" } } }],
  ])("disables submission and never POSTs for a malformed available contract: %s", (_case, malformedContract) => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const { container } = render(
      <InferenceForm contract={contract} slug={slug} resultContract={malformedContract as BinaryResultContract} />,
    );

    expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();
    fireEvent.submit(container.querySelector("form")!);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows Submitting… on the button and the loading shell while a request is in flight", async () => {
    let releaseFetch: ((value: MockResponse) => void) | null = null;
    const fetchMock = vi.fn(
      () =>
        new Promise<MockResponse>((resolve) => {
          releaseFetch = resolve;
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(
      <InferenceForm
        contract={contract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    expect(await screen.findByRole("button", { name: "Submitting…" })).toBeInTheDocument();
    expect(screen.getByText("Generating prediction…")).toBeInTheDocument();

    releaseFetch!(jsonResponse({ dataset_slug: slug, result: validResult }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
  });

  it("parses body.result on success and renders the shared BinaryClassificationResult", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ dataset_slug: slug, result: validResult })));

    render(
      <InferenceForm
        contract={contract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    expect(await screen.findByText("Likely to churn")).toBeInTheDocument();
    expect(screen.getByText("68%")).toBeInTheDocument();
    expect(screen.getByText("Gradient Boosting")).toBeInTheDocument();
  });

  it("enters the safe error state, not a crash, when the success payload is malformed", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ dataset_slug: slug, result: { schema_version: "binary-classification-result.v1" } })),
    );

    render(<InferenceForm contract={contract} slug={slug} resultContract={availableContract} resultPresentation={presentation} />);

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong. Please try again later.");
  });

  it("never falls back to a legacy body.prediction field", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ dataset_slug: slug, prediction: { label: "Yes", confidence: 0.9 } })),
    );

    render(<InferenceForm contract={contract} slug={slug} resultContract={availableContract} resultPresentation={presentation} />);

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText(/confidence/i)).not.toBeInTheDocument();
    expect(screen.queryByText("90%")).not.toBeInTheDocument();
  });

  it("maps a non-ok API error response to safe user-facing copy", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ error_code: "INFERENCE_FAILURE" }, 503)));

    render(<InferenceForm contract={contract} slug={slug} resultContract={availableContract} resultPresentation={presentation} />);

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The prediction service is temporarily unavailable. Please try again later.",
    );
  });

  it("falls back to the generic bounded presentation when resultPresentation is absent", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ dataset_slug: slug, result: validResult })));

    render(<InferenceForm contract={contract} slug={slug} resultContract={availableContract} />);

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    expect(await screen.findByText("Positive outcome")).toBeInTheDocument();
  });
});

// Project Spec S0141: DatasetPage.tsx opts into a local, presentation-only
// zero-probability initial Result Card projection via initialResultProbability.
// Every other caller (Predict View, Admin Live Preview) omits this prop and
// keeps the pre-existing idle-placeholder behavior asserted above.
describe("InferenceForm initial Result Card projection (Project Spec S0141)", () => {
  it("renders exactly one complete Result Card at 0% -- not the idle placeholder -- and issues no POST request", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const { container } = render(
      <InferenceForm
        contract={contract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
        initialResultProbability={0}
      />,
    );

    expect(screen.queryByText("Submit the form to see the prediction.")).not.toBeInTheDocument();
    expect(container.querySelectorAll(".inference-result")).toHaveLength(1);
    expect(
      screen.getByText("0%", { selector: ".binary-classification-result__probability-value" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Model")).toBeInTheDocument();
    expect(screen.getByText("Gradient Boosting")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("derives the outcome/band from the governed threshold at probability zero (below a positive threshold)", () => {
    render(
      <InferenceForm
        contract={contract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
        initialResultProbability={0}
      />,
    );

    // availableContract's threshold is 0.5, so 0 >= 0.5 is false: negative
    // outcome copy and the governed "low" band, never hardcoded English text.
    expect(screen.getByText("Unlikely to churn")).toBeInTheDocument();
    expect(screen.getByText("Low risk")).toBeInTheDocument();
  });

  it("marks the initial projection with a distinct shell state from a real successful result", () => {
    const { container } = render(
      <InferenceForm
        contract={contract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
        initialResultProbability={0}
      />,
    );

    expect(container.querySelector(".result-panel--initial")).toBeInTheDocument();
    expect(container.querySelector(".result-panel--success")).not.toBeInTheDocument();
  });

  it("replaces the initial projection with the real result after a valid submission, keeping exactly one card", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ dataset_slug: slug, result: validResult })));

    const { container } = render(
      <InferenceForm
        contract={contract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
        initialResultProbability={0}
      />,
    );

    expect(
      screen.getByText("0%", { selector: ".binary-classification-result__probability-value" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    expect(await screen.findByText("68%")).toBeInTheDocument();
    expect(container.querySelectorAll(".inference-result")).toHaveLength(1);
    expect(container.querySelector(".result-panel--success")).toBeInTheDocument();
    expect(container.querySelector(".result-panel--initial")).not.toBeInTheDocument();
  });

  it("does not render the initial projection while the result contract is unavailable, and keeps submission disabled", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(
      <InferenceForm
        contract={contract}
        slug={slug}
        resultContract={unavailableContract}
        resultPresentation={presentation}
        initialResultProbability={0}
      />,
    );

    expect(screen.queryByText("0%", { selector: ".binary-classification-result__probability-value" })).not.toBeInTheDocument();
    expect(
      screen.getByText("This active release does not currently expose a compatible result."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("falls back to the idle placeholder when initialResultProbability is omitted, preserving Predict View's current behavior", () => {
    render(
      <InferenceForm
        contract={contract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
      />,
    );

    expect(screen.getByText("Submit the form to see the prediction.")).toBeInTheDocument();
  });
});

describe("InferenceForm preview mode (Admin Live Preview compatibility)", () => {
  it("performs no POST and renders no public ResultCardShell state, regardless of resultContract", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const { container } = render(
      <InferenceForm contract={contract} slug={slug} previewMode submitButtonLabel="Run prediction" />,
    );

    expect(screen.getByRole("button", { name: "Run prediction" })).toBeDisabled();
    expect(screen.queryByLabelText("Prediction result")).not.toBeInTheDocument();

    fireEvent.submit(container.querySelector("form")!);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("InferenceForm scoped visual structure (Project Spec S0135)", () => {
  it("renders the Inference heading and a scoped field-grid for an ungrouped form, without inventing a legend", () => {
    const { container } = render(<InferenceForm contract={contract} slug={slug} previewMode />);

    expect(screen.getByRole("heading", { name: "Inference" })).toHaveClass("public-inference-form__heading");
    expect(container.querySelector("fieldset")).not.toBeInTheDocument();

    const fieldGrid = container.querySelector(".public-inference-form__field-grid");
    expect(fieldGrid).toBeInTheDocument();
    expect(fieldGrid!.querySelector(".public-inference-form__field")).toBeInTheDocument();
  });

  it("gives every visible field a stable scoped wrapper, label, control and helper text", () => {
    const singleFieldContract: ContractPayload = {
      schema_version: "1.0.0",
      features: [
        {
          name: "tenure",
          label: "Tenure",
          input_type: "number",
          optional: true,
          display_order: 1,
          description: "Months as a customer.",
        },
      ],
    };

    const { container } = render(<InferenceForm contract={singleFieldContract} slug={slug} previewMode />);

    const field = container.querySelector(".public-inference-form__field");
    expect(field).toBeInTheDocument();
    expect(field!.querySelector(".public-inference-form__label")).toHaveTextContent("Tenure");
    expect(field!.querySelector(".public-inference-form__control")).toHaveAttribute("type", "number");
    expect(field!.querySelector(".public-inference-form__helper")).toHaveTextContent("Months as a customer.");
    expect(field!.querySelector(".public-inference-form__required")).not.toBeInTheDocument();
  });

  it("marks required fields with a scoped required marker", () => {
    const requiredFieldContract: ContractPayload = {
      schema_version: "1.0.0",
      features: [
        { name: "tenure", label: "Tenure", input_type: "number", optional: false, display_order: 1 },
      ],
    };

    const { container } = render(<InferenceForm contract={requiredFieldContract} slug={slug} previewMode />);

    expect(container.querySelector(".public-inference-form__required")).toBeInTheDocument();
  });

  it("uses a dedicated scoped row treatment for checkbox fields while preserving native semantics and label association", () => {
    const checkboxContract: ContractPayload = {
      schema_version: "1.0.0",
      features: [
        { name: "auto_pay", label: "AutoPay", input_type: "checkbox", optional: true, display_order: 1 },
      ],
    };

    render(<InferenceForm contract={checkboxContract} slug={slug} previewMode />);

    const checkbox = screen.getByLabelText("AutoPay");
    expect(checkbox).toHaveAttribute("type", "checkbox");
    expect(checkbox).toHaveClass("public-inference-form__control--checkbox");
    expect(checkbox.closest(".public-inference-form__field")).toHaveClass("public-inference-form__field--checkbox");
  });

  it("preserves the S0134 synthetic customization fixture (two groups, group/field order, renamed label, helper text, hidden field, submit label) while applying scoped group structure", () => {
    const fixtureContract: ContractPayload = {
      schema_version: "1.0.0",
      features: [
        { name: "tenure", label: "Tenure", input_type: "number", optional: true, display_order: 1 },
        {
          name: "contract_type",
          label: "Contract Type",
          input_type: "select",
          optional: false,
          display_order: 2,
          options: [
            { value: "month", label: "Month-to-month" },
            { value: "year", label: "One year" },
          ],
        },
        { name: "auto_pay", label: "AutoPay", input_type: "checkbox", optional: true, display_order: 3 },
        { name: "internal_notes", label: "Internal Notes", input_type: "number", optional: true, display_order: 4 },
      ],
    };

    const fixtureCustomization = {
      groups: [
        { group_id: "account", label: "Account profile" },
        { group_id: "billing", label: "Billing", description: "Billing-related fields." },
      ],
      field_hints: [
        { field_name: "tenure", group: "account", display_order_hint: 1 },
        {
          field_name: "contract_type",
          group: "account",
          display_order_hint: 2,
          display_label: "Contract length",
          explanatory_copy: "Choose the current contract term.",
        },
        { field_name: "auto_pay", group: "billing", display_order_hint: 3 },
        { field_name: "internal_notes", hidden: true, display_order_hint: 4 },
      ],
      view_copy: { submit_button_label: "Run Prediction" },
    };

    const { container } = render(
      <InferenceForm
        contract={fixtureContract}
        slug={slug}
        customization={fixtureCustomization}
        previewMode
        submitButtonLabel={fixtureCustomization.view_copy.submit_button_label}
      />,
    );

    const groups = container.querySelectorAll(".public-inference-form__group");
    expect(groups).toHaveLength(2);
    expect(groups[0].querySelector(".public-inference-form__legend")).toHaveTextContent("Account profile");
    expect(groups[1].querySelector(".public-inference-form__legend")).toHaveTextContent("Billing");
    expect(groups[1].querySelector(".public-inference-form__group-description")).toHaveTextContent(
      "Billing-related fields.",
    );

    const accountLabels = groups[0].querySelectorAll(".public-inference-form__label");
    expect(accountLabels).toHaveLength(2);
    expect(accountLabels[0]).toHaveTextContent("Tenure");
    expect(accountLabels[1]).toHaveTextContent("Contract length");
    expect(groups[0].querySelector(".public-inference-form__helper")).toHaveTextContent(
      "Choose the current contract term.",
    );

    expect(groups[1].querySelector(".public-inference-form__label")).toHaveTextContent("AutoPay");

    expect(screen.queryByText("Internal Notes")).not.toBeInTheDocument();
    expect(container.querySelectorAll(".public-inference-form__field")).toHaveLength(3);

    expect(screen.getByRole("button", { name: "Run Prediction" })).toHaveClass("public-inference-form__submit");
  });
});

// Project Spec S0203: a select field's label shows only its configured
// display label -- the appended "(categorical field)" suffix is removed --
// while every other select behavior (label association, required marker,
// options, submission serialization) stays exactly as before.
describe("InferenceForm select field label copy (Project Spec S0203)", () => {
  const selectContract: ContractPayload = {
    schema_version: "1.0.0",
    features: [
      {
        name: "contract_type",
        label: "Contract Type",
        input_type: "select",
        optional: false,
        display_order: 1,
        options: [
          { value: "month", label: "Month-to-month" },
          { value: "year", label: "One year" },
        ],
      },
      {
        name: "payment_method",
        label: "Payment Method",
        input_type: "select",
        optional: true,
        display_order: 2,
        options: [
          { value: "card", label: "Card" },
          { value: "cash", label: "Cash" },
        ],
      },
    ],
  };

  it("shows only the configured display label, with no '(categorical field)' suffix, for a required and an optional select", () => {
    render(<InferenceForm contract={selectContract} slug={slug} previewMode />);

    expect(screen.getByText("Contract Type")).toBeInTheDocument();
    expect(screen.getByText("Payment Method")).toBeInTheDocument();
    expect(screen.queryByText(/\(categorical field\)/)).not.toBeInTheDocument();
  });

  it("keeps the select accessible by its label, with required/optional semantics and options unchanged", () => {
    render(<InferenceForm contract={selectContract} slug={slug} previewMode />);

    const requiredSelect = screen.getByLabelText(/^Contract Type/) as HTMLSelectElement;
    expect(requiredSelect.tagName).toBe("SELECT");
    expect(requiredSelect).toHaveAttribute("required");
    expect(Array.from(requiredSelect.options).map((option) => option.value)).toEqual(["month", "year"]);

    const optionalSelect = screen.getByLabelText("Payment Method") as HTMLSelectElement;
    expect(optionalSelect.tagName).toBe("SELECT");
    expect(optionalSelect).not.toHaveAttribute("required");
    expect(Array.from(optionalSelect.options).map((option) => option.value)).toEqual(["card", "cash"]);
  });

  it("submits the selected option's value unchanged", async () => {
    const executeInference = vi.fn(
      async (
        _slug: string,
        _payload: InferenceExecutorPayload,
      ): Promise<InferenceExecutionResult> => ({ ok: true, result: validResult }),
    );

    render(
      <InferenceForm
        contract={selectContract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
        executeInference={executeInference}
      />,
    );

    fireEvent.change(screen.getByLabelText(/^Contract Type/), { target: { value: "year" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    await waitFor(() => expect(executeInference).toHaveBeenCalledTimes(1));
    expect(executeInference).toHaveBeenLastCalledWith(slug, { contract_type: "year", payment_method: "card" });
  });
});

// Project Spec S0146: a rendered checkbox always represents a complete
// two-state boolean -- checked/true and unchecked/false are both valid and
// complete -- so a contract-required checkbox must never carry the native
// HTML `required` constraint (which means "must be checked") or its visual
// required marker, while required number/select controls keep both.
describe("InferenceForm boolean checkbox false-state submission (Project Spec S0146)", () => {
  const requiredCheckboxContract: ContractPayload = {
    schema_version: "1.0.0",
    features: [{ name: "consent", label: "Consent", input_type: "checkbox", optional: false, display_order: 1 }],
  };

  const optionalCheckboxContract: ContractPayload = {
    schema_version: "1.0.0",
    features: [{ name: "consent", label: "Consent", input_type: "checkbox", optional: true, display_order: 1 }],
  };

  const mixedRequiredContract: ContractPayload = {
    schema_version: "1.0.0",
    features: [
      { name: "tenure", label: "Tenure", input_type: "number", optional: false, display_order: 1 },
      {
        name: "contract_type",
        label: "Contract Type",
        input_type: "select",
        optional: false,
        display_order: 2,
        options: [
          { value: "month", label: "Month-to-month" },
          { value: "year", label: "One year" },
        ],
      },
      { name: "auto_pay", label: "AutoPay", input_type: "checkbox", optional: false, display_order: 3 },
    ],
  };

  const optionalNumberSelectContract: ContractPayload = {
    schema_version: "1.0.0",
    features: [
      { name: "tenure", label: "Tenure", input_type: "number", optional: true, display_order: 1 },
      {
        name: "contract_type",
        label: "Contract Type",
        input_type: "select",
        optional: true,
        display_order: 2,
        options: [
          { value: "month", label: "Month-to-month" },
          { value: "year", label: "One year" },
        ],
      },
    ],
  };

  it("renders a contract-required checkbox without the native required attribute", () => {
    render(<InferenceForm contract={requiredCheckboxContract} slug={slug} previewMode />);
    expect(screen.getByLabelText("Consent")).not.toHaveAttribute("required");
  });

  it("renders a contract-optional checkbox without the native required attribute", () => {
    render(<InferenceForm contract={optionalCheckboxContract} slug={slug} previewMode />);
    expect(screen.getByLabelText("Consent")).not.toHaveAttribute("required");
  });

  it("does not render a required marker for a contract-required checkbox", () => {
    const { container } = render(<InferenceForm contract={requiredCheckboxContract} slug={slug} previewMode />);
    expect(container.querySelector(".public-inference-form__required")).not.toBeInTheDocument();
  });

  it("keeps the required marker and native required attribute on required number/select fields while omitting both from a required checkbox in the same form", () => {
    const { container } = render(<InferenceForm contract={mixedRequiredContract} slug={slug} previewMode />);

    expect(screen.getByLabelText(/^Tenure/)).toHaveAttribute("required");
    expect(screen.getByLabelText(/Contract Type/)).toHaveAttribute("required");
    expect(screen.getByLabelText("AutoPay")).not.toHaveAttribute("required");
    expect(container.querySelectorAll(".public-inference-form__required")).toHaveLength(2);
  });

  it("keeps optional number and select fields optional, with no required marker", () => {
    const { container } = render(<InferenceForm contract={optionalNumberSelectContract} slug={slug} previewMode />);

    expect(screen.getByLabelText("Tenure")).not.toHaveAttribute("required");
    expect(screen.getByLabelText(/Contract Type/)).not.toHaveAttribute("required");
    expect(container.querySelector(".public-inference-form__required")).not.toBeInTheDocument();
  });

  it("never marks a required checkbox invalid via native constraint validation, in either checked state", () => {
    render(<InferenceForm contract={requiredCheckboxContract} slug={slug} previewMode />);
    const checkbox = screen.getByLabelText("Consent") as HTMLInputElement;

    expect(checkbox.checkValidity()).toBe(true);
    expect(checkbox.validationMessage).toBe("");

    fireEvent.click(checkbox);
    expect(checkbox.checked).toBe(true);
    expect(checkbox.checkValidity()).toBe(true);
    expect(checkbox.validationMessage).toBe("");
  });

  it("submits an unchecked contract-required checkbox to the injected executor as boolean false, and still emits the started lifecycle event", async () => {
    const executeInference = vi.fn(
      async (
        _slug: string,
        _payload: InferenceExecutorPayload,
      ): Promise<InferenceExecutionResult> => ({ ok: true, result: validResult }),
    );
    const events: InferenceLifecycleEvent[] = [];

    render(
      <InferenceForm
        contract={requiredCheckboxContract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
        executeInference={executeInference}
        onLifecycleEvent={(event) => events.push(event)}
      />,
    );

    expect(screen.getByLabelText("Consent")).not.toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    await waitFor(() => expect(executeInference).toHaveBeenCalledTimes(1));
    expect(executeInference).toHaveBeenCalledWith(slug, { consent: false });
    expect(typeof asScalarPayload(executeInference.mock.calls[0][1]).consent).toBe("boolean");
    expect(events[0]).toEqual({ type: "started" });
  });

  it("submits a checked contract-required checkbox to the injected executor as boolean true", async () => {
    const executeInference = vi.fn(
      async (
        _slug: string,
        _payload: InferenceExecutorPayload,
      ): Promise<InferenceExecutionResult> => ({ ok: true, result: validResult }),
    );

    render(
      <InferenceForm
        contract={requiredCheckboxContract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
        executeInference={executeInference}
      />,
    );

    fireEvent.click(screen.getByLabelText("Consent"));
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    await waitFor(() => expect(executeInference).toHaveBeenCalledTimes(1));
    expect(executeInference).toHaveBeenCalledWith(slug, { consent: true });
    expect(typeof asScalarPayload(executeInference.mock.calls[0][1]).consent).toBe("boolean");
  });
});

// Project Spec S0143: the injectable execution boundary a private Admin
// Live Preview executor plugs into, plus the resetKey stale-response guard
// and lifecycle seam it relies on -- exercised here independently of any
// specific caller (DatasetAdminPage.tsx wires the real private executor).
describe("InferenceForm injectable execution boundary (Project Spec S0143)", () => {
  it("uses the injected executor instead of the default public fetch", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const executeInference = vi.fn(
      async (): Promise<InferenceExecutionResult> => ({ ok: true, result: validResult }),
    );

    render(
      <InferenceForm
        contract={contract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
        executeInference={executeInference}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    expect(await screen.findByText("68%")).toBeInTheDocument();
    expect(executeInference).toHaveBeenCalledWith(slug, expect.any(Object));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("Project Spec S0152 regression: an empty optional numeric input is omitted entirely from the request payload, and a provided value is included", async () => {
    const executeInference = vi.fn(
      async (): Promise<InferenceExecutionResult> => ({ ok: true, result: validResult }),
    );

    const { unmount } = render(
      <InferenceForm
        contract={contract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
        executeInference={executeInference}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await waitFor(() => expect(executeInference).toHaveBeenCalledTimes(1));
    expect(executeInference).toHaveBeenLastCalledWith(slug, {});
    unmount();

    const executeInferenceWithValue = vi.fn(
      async (): Promise<InferenceExecutionResult> => ({ ok: true, result: validResult }),
    );
    render(
      <InferenceForm
        contract={contract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
        executeInference={executeInferenceWithValue}
      />,
    );
    fireEvent.change(screen.getByLabelText("Tenure"), { target: { value: "24" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await waitFor(() => expect(executeInferenceWithValue).toHaveBeenCalledTimes(1));
    expect(executeInferenceWithValue).toHaveBeenLastCalledWith(slug, { tenure: 24 });
  });

  it("renders the safe error state when the injected executor reports a bounded failure", async () => {
    const executeInference = vi.fn(
      async (): Promise<InferenceExecutionResult> => ({ ok: false, errorCode: "INFERENCE_FAILURE" }),
    );

    render(
      <InferenceForm
        contract={contract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
        executeInference={executeInference}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The prediction service is temporarily unavailable. Please try again later.",
    );
  });

  it("emits started/succeeded lifecycle events with no raw payload or response data", async () => {
    const executeInference = vi.fn(
      async (): Promise<InferenceExecutionResult> => ({ ok: true, result: validResult }),
    );
    const events: InferenceLifecycleEvent[] = [];

    render(
      <InferenceForm
        contract={contract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
        executeInference={executeInference}
        onLifecycleEvent={(event) => events.push(event)}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await screen.findByText("68%");

    expect(events).toEqual([{ type: "started" }, { type: "succeeded" }]);
    for (const event of events) {
      expect(Object.keys(event)).toEqual(["type"]);
    }
  });

  it("emits a validation_failed lifecycle event for an INVALID_PAYLOAD executor outcome", async () => {
    const executeInference = vi.fn(
      async (): Promise<InferenceExecutionResult> => ({ ok: false, errorCode: "INVALID_PAYLOAD" }),
    );
    const events: InferenceLifecycleEvent[] = [];

    render(
      <InferenceForm
        contract={contract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
        executeInference={executeInference}
        onLifecycleEvent={(event) => events.push(event)}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await screen.findByRole("alert");

    expect(events).toEqual([{ type: "started" }, { type: "validation_failed" }]);
  });

  it("emits an execution_failed lifecycle event for a malformed success payload", async () => {
    const executeInference = vi.fn(
      async (): Promise<InferenceExecutionResult> => ({
        ok: true,
        result: { schema_version: "binary-classification-result.v1" },
      }),
    );
    const events: InferenceLifecycleEvent[] = [];

    render(
      <InferenceForm
        contract={contract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
        executeInference={executeInference}
        onLifecycleEvent={(event) => events.push(event)}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await screen.findByRole("alert");

    expect(events).toEqual([{ type: "started" }, { type: "execution_failed" }]);
  });

  it("resets the submission back to the initial 0% projection when resetKey changes", async () => {
    const executeInference = vi.fn(
      async (): Promise<InferenceExecutionResult> => ({ ok: true, result: validResult }),
    );

    const { rerender } = render(
      <InferenceForm
        contract={contract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
        initialResultProbability={0}
        executeInference={executeInference}
        resetKey="dataset-a::view-1"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await screen.findByText("68%");

    rerender(
      <InferenceForm
        contract={contract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
        initialResultProbability={0}
        executeInference={executeInference}
        resetKey="dataset-b::view-1"
      />,
    );

    expect(
      screen.getByText("0%", { selector: ".binary-classification-result__probability-value" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("68%")).not.toBeInTheDocument();
  });

  it("never lets a response from a previous identity overwrite the current identity's state", async () => {
    let resolveExecutor: ((value: InferenceExecutionResult) => void) | null = null;
    const executeInference = vi.fn(
      () =>
        new Promise<InferenceExecutionResult>((resolve) => {
          resolveExecutor = resolve;
        }),
    );

    const { rerender } = render(
      <InferenceForm
        contract={contract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
        initialResultProbability={0}
        executeInference={executeInference}
        resetKey="dataset-a::view-1"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await screen.findByRole("button", { name: "Submitting…" });

    // The selected dataset/view identity changes before the in-flight
    // request for the previous identity resolves.
    rerender(
      <InferenceForm
        contract={contract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
        initialResultProbability={0}
        executeInference={executeInference}
        resetKey="dataset-b::view-1"
      />,
    );

    expect(
      screen.getByText("0%", { selector: ".binary-classification-result__probability-value" }),
    ).toBeInTheDocument();

    resolveExecutor!({ ok: true, result: validResult });

    // Give the resolved promise's continuation a turn to run, then confirm
    // the stale response never replaced the reset 0% projection.
    await waitFor(() => expect(executeInference).toHaveBeenCalledTimes(1));
    expect(screen.queryByText("68%")).not.toBeInTheDocument();
    expect(
      screen.getByText("0%", { selector: ".binary-classification-result__probability-value" }),
    ).toBeInTheDocument();
  });
});

// Project Spec S0156: typed select serialization must follow explicit
// public-contract metadata (select_value_type), never the selected option's
// text or the field name -- and a contract-declared conditional blank field
// must reach the backend with its declared blank representation instead of
// being silently omitted.
describe("InferenceForm typed select serialization and conditional blank policy (Project Spec S0156)", () => {
  const stringSelectContract: ContractPayload = {
    schema_version: "1.0.0",
    features: [
      {
        name: "plan_type",
        label: "Plan Type",
        input_type: "select",
        optional: false,
        display_order: 1,
        select_value_type: "string",
        options: [
          { value: "basic", label: "Basic" },
          { value: "pro", label: "Pro" },
        ],
      },
    ],
  };

  const integerSelectContract: ContractPayload = {
    schema_version: "1.0.0",
    features: [
      {
        name: "account_id_flag",
        label: "Account Id Flag",
        input_type: "select",
        optional: false,
        display_order: 1,
        select_value_type: "integer",
        options: [
          { value: 0, label: "0" },
          { value: 1, label: "1" },
        ],
      },
    ],
  };

  const conditionalBlankNumericContract: ContractPayload = {
    schema_version: "1.0.0",
    features: [
      {
        name: "total_amount",
        label: "Total Amount",
        input_type: "number",
        optional: false,
        display_order: 1,
        conditional_blank_policy: { accepted_representation: "blank_string_after_trim" },
      },
    ],
  };

  it("submits an integer categorical select as a JSON integer", async () => {
    const executeInference = vi.fn(
      async (
        _slug: string,
        _payload: InferenceExecutorPayload,
      ): Promise<InferenceExecutionResult> => ({ ok: true, result: validResult }),
    );

    render(
      <InferenceForm
        contract={integerSelectContract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
        executeInference={executeInference}
      />,
    );

    fireEvent.change(screen.getByLabelText(/Account Id Flag/), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    await waitFor(() => expect(executeInference).toHaveBeenCalledTimes(1));
    expect(executeInference).toHaveBeenLastCalledWith(slug, { account_id_flag: 1 });
    expect(typeof asScalarPayload(executeInference.mock.calls[0][1]).account_id_flag).toBe("number");
  });

  it("submits a string categorical select as a JSON string", async () => {
    const executeInference = vi.fn(
      async (
        _slug: string,
        _payload: InferenceExecutorPayload,
      ): Promise<InferenceExecutionResult> => ({ ok: true, result: validResult }),
    );

    render(
      <InferenceForm
        contract={stringSelectContract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
        executeInference={executeInference}
      />,
    );

    fireEvent.change(screen.getByLabelText(/Plan Type/), { target: { value: "pro" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    await waitFor(() => expect(executeInference).toHaveBeenCalledTimes(1));
    expect(executeInference).toHaveBeenLastCalledWith(slug, { plan_type: "pro" });
    expect(typeof asScalarPayload(executeInference.mock.calls[0][1]).plan_type).toBe("string");
  });

  it("submits the declared blank representation for a conditional blank field left empty, instead of omitting it", async () => {
    const executeInference = vi.fn(
      async (): Promise<InferenceExecutionResult> => ({ ok: true, result: validResult }),
    );

    render(
      <InferenceForm
        contract={conditionalBlankNumericContract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
        executeInference={executeInference}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    await waitFor(() => expect(executeInference).toHaveBeenCalledTimes(1));
    expect(executeInference).toHaveBeenLastCalledWith(slug, { total_amount: "" });
  });

  it("submits a provided numeric value unchanged for a conditional blank field, ignoring the blank-policy exception", async () => {
    const executeInference = vi.fn(
      async (): Promise<InferenceExecutionResult> => ({ ok: true, result: validResult }),
    );

    render(
      <InferenceForm
        contract={conditionalBlankNumericContract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
        executeInference={executeInference}
      />,
    );

    fireEvent.change(screen.getByLabelText(/Total Amount/), { target: { value: "42.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    await waitFor(() => expect(executeInference).toHaveBeenCalledTimes(1));
    expect(executeInference).toHaveBeenLastCalledWith(slug, { total_amount: 42.5 });
  });

  it("Project Spec S0152 regression: an ordinary optional empty numeric field with no conditional policy is still omitted entirely", async () => {
    const executeInference = vi.fn(
      async (): Promise<InferenceExecutionResult> => ({ ok: true, result: validResult }),
    );

    render(
      <InferenceForm
        contract={contract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
        executeInference={executeInference}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    await waitFor(() => expect(executeInference).toHaveBeenCalledTimes(1));
    expect(executeInference).toHaveBeenLastCalledWith(slug, {});
  });
});

// Project Spec S0147: normalizeInferenceValidationIssues is the sole
// boundary that may turn an unknown backend `errors` value into a safe,
// bounded InferenceValidationIssue list -- exercised directly here (pure
// function, no DOM, no network) for every normalization invariant.
describe("normalizeInferenceValidationIssues (Project Spec S0147)", () => {
  it("normalizes a valid API issues array into bounded canonical field+violation pairs", () => {
    const errors = [
      { error_code: "MISSING_REQUIRED_FIELD", field: "tenure", violation: "missing_required_field", message: "raw backend message" },
      { error_code: "DOMAIN_VIOLATION", field: "MonthlyCharges", violation: "domain_violation", message: "raw backend message" },
    ];

    expect(normalizeInferenceValidationIssues(errors)).toEqual([
      { field: "tenure", violation: "missing_required_field" },
      { field: "MonthlyCharges", violation: "domain_violation" },
    ]);
  });

  it("ignores malformed issue entries (non-object, missing field, blank field, non-string violation)", () => {
    const errors = [
      null,
      "raw-string",
      42,
      {},
      { field: "" },
      { field: "   " },
      { field: "tenure" },
      { field: "tenure", violation: 123 },
      { field: 123, violation: "type_mismatch" },
    ];

    expect(normalizeInferenceValidationIssues(errors)).toBeUndefined();
  });

  it("ignores unknown violation values", () => {
    expect(normalizeInferenceValidationIssues([{ field: "tenure", violation: "some_unknown_violation" }])).toBeUndefined();
  });

  it("deduplicates identical canonical field+violation pairs, preserving first-seen backend order", () => {
    const errors = [
      { field: "tenure", violation: "missing_required_field" },
      { field: "MonthlyCharges", violation: "domain_violation" },
      { field: "tenure", violation: "missing_required_field" },
    ];

    expect(normalizeInferenceValidationIssues(errors)).toEqual([
      { field: "tenure", violation: "missing_required_field" },
      { field: "MonthlyCharges", violation: "domain_violation" },
    ]);
  });

  it("retains at most 20 unique issues from one failed response", () => {
    const errors = Array.from({ length: 25 }, (_, index) => ({ field: `field_${index}`, violation: "type_mismatch" }));

    const result = normalizeInferenceValidationIssues(errors);

    expect(result).toHaveLength(20);
    expect(result?.[0]).toEqual({ field: "field_0", violation: "type_mismatch" });
    expect(result?.[19]).toEqual({ field: "field_19", violation: "type_mismatch" });
  });

  it("ignores an oversized field string rather than exposing arbitrary content", () => {
    const oversizedField = "x".repeat(500);
    expect(normalizeInferenceValidationIssues([{ field: oversizedField, violation: "type_mismatch" }])).toBeUndefined();
  });

  it("returns undefined for a non-array, empty, or entirely-invalid errors value", () => {
    expect(normalizeInferenceValidationIssues(undefined)).toBeUndefined();
    expect(normalizeInferenceValidationIssues(null)).toBeUndefined();
    expect(normalizeInferenceValidationIssues("errors")).toBeUndefined();
    expect(normalizeInferenceValidationIssues({})).toBeUndefined();
    expect(normalizeInferenceValidationIssues([])).toBeUndefined();
  });
});

// Project Spec S0147: the private Admin audit flow's structured
// diagnostics -- contract filtering, display-label resolution, and the
// bounded validation_failed lifecycle event -- exercised through the real
// InferenceForm submission path, exactly as DatasetAdminPage's private
// executor and Publishing console consume it.
describe("InferenceForm structured validation diagnostics (Project Spec S0147)", () => {
  const diagnosticsContract: ContractPayload = {
    schema_version: "1.0.0",
    features: [
      { name: "tenure", label: "Tenure", input_type: "number", optional: true, display_order: 1 },
      { name: "MonthlyCharges", label: "Monthly charges", input_type: "number", optional: true, display_order: 2 },
      {
        name: "contract_type",
        label: "Contract Type",
        input_type: "select",
        optional: true,
        display_order: 3,
        options: [{ value: "month", label: "Month-to-month" }],
      },
    ],
  };

  const diagnosticsCustomization = {
    field_hints: [{ field_name: "contract_type", display_label: "Contract length" }],
    groups: [],
  };

  it("filters out non-contract fields, resolves customization label precedence, retains a payload type_mismatch, and preserves normalized order", async () => {
    const executeInference = vi.fn(
      async (): Promise<InferenceExecutionResult> => ({
        ok: false,
        errorCode: "INVALID_PAYLOAD",
        validationIssues: [
          { field: "tenure", violation: "missing_required_field" },
          { field: "contract_type", violation: "domain_violation" },
          { field: "MonthlyCharges", violation: "type_mismatch" },
          { field: "totally_unrelated_field", violation: "type_mismatch" },
          { field: "payload", violation: "type_mismatch" },
          { field: "payload", violation: "missing_required_field" },
        ],
      }),
    );
    const events: InferenceLifecycleEvent[] = [];

    render(
      <InferenceForm
        contract={diagnosticsContract}
        slug={slug}
        customization={diagnosticsCustomization}
        resultContract={availableContract}
        resultPresentation={presentation}
        executeInference={executeInference}
        onLifecycleEvent={(event) => events.push(event)}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    // Project Spec S0147: the shared visible form/Result Card error stays
    // generic -- the field-level diagnosis belongs to the Publishing
    // console only.
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Some inputs are invalid. Please check your answers and try again.",
    );

    expect(events.find((event) => event.type === "validation_failed")).toEqual({
      type: "validation_failed",
      issues: [
        { field: "tenure", fieldLabel: "Tenure", violation: "missing_required_field" },
        { field: "contract_type", fieldLabel: "Contract length", violation: "domain_violation" },
        { field: "MonthlyCharges", fieldLabel: "Monthly charges", violation: "type_mismatch" },
        { field: "payload", fieldLabel: "Inference payload", violation: "type_mismatch" },
      ],
    });
  });

  it("falls back to the contract feature label, then the canonical feature name, when no customization label applies", async () => {
    const blankLabelContract: ContractPayload = {
      schema_version: "1.0.0",
      features: [
        { name: "internal_score", label: "", input_type: "number", optional: true, display_order: 1 },
        { name: "tenure", label: "Tenure", input_type: "number", optional: true, display_order: 2 },
      ],
    };
    const executeInference = vi.fn(
      async (): Promise<InferenceExecutionResult> => ({
        ok: false,
        errorCode: "INVALID_PAYLOAD",
        validationIssues: [
          { field: "internal_score", violation: "type_mismatch" },
          { field: "tenure", violation: "missing_required_field" },
        ],
      }),
    );
    const events: InferenceLifecycleEvent[] = [];

    render(
      <InferenceForm
        contract={blankLabelContract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
        executeInference={executeInference}
        onLifecycleEvent={(event) => events.push(event)}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await screen.findByRole("alert");

    expect(events.find((event) => event.type === "validation_failed")).toEqual({
      type: "validation_failed",
      issues: [
        { field: "internal_score", fieldLabel: "internal_score", violation: "type_mismatch" },
        { field: "tenure", fieldLabel: "Tenure", violation: "missing_required_field" },
      ],
    });
  });

  it("emits the existing issue-free validation_failed event when the executor reports no structured details", async () => {
    const executeInference = vi.fn(
      async (): Promise<InferenceExecutionResult> => ({ ok: false, errorCode: "INVALID_PAYLOAD" }),
    );
    const events: InferenceLifecycleEvent[] = [];

    render(
      <InferenceForm
        contract={contract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
        executeInference={executeInference}
        onLifecycleEvent={(event) => events.push(event)}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await screen.findByRole("alert");

    expect(events).toEqual([{ type: "started" }, { type: "validation_failed" }]);
  });

  it("emits the existing issue-free validation_failed event when every reported field is unrelated to the active contract", async () => {
    const executeInference = vi.fn(
      async (): Promise<InferenceExecutionResult> => ({
        ok: false,
        errorCode: "INVALID_PAYLOAD",
        validationIssues: [{ field: "totally_unrelated_field", violation: "type_mismatch" }],
      }),
    );
    const events: InferenceLifecycleEvent[] = [];

    render(
      <InferenceForm
        contract={contract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
        executeInference={executeInference}
        onLifecycleEvent={(event) => events.push(event)}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await screen.findByRole("alert");

    expect(events).toEqual([{ type: "started" }, { type: "validation_failed" }]);
  });

  it("never carries validation issues on an execution_failed lifecycle event, even if the executor attaches them", async () => {
    const executeInference = vi.fn(
      async (): Promise<InferenceExecutionResult> => ({
        ok: false,
        errorCode: "INFERENCE_FAILURE",
        validationIssues: [{ field: "tenure", violation: "type_mismatch" }],
      }),
    );
    const events: InferenceLifecycleEvent[] = [];

    render(
      <InferenceForm
        contract={contract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
        executeInference={executeInference}
        onLifecycleEvent={(event) => events.push(event)}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await screen.findByRole("alert");

    expect(events).toEqual([{ type: "started" }, { type: "execution_failed" }]);
  });

  it("never exposes a submitted field value anywhere in the emitted lifecycle events", async () => {
    const executeInference = vi.fn(
      async (): Promise<InferenceExecutionResult> => ({
        ok: false,
        errorCode: "INVALID_PAYLOAD",
        validationIssues: [{ field: "tenure", violation: "domain_violation" }],
      }),
    );
    const events: InferenceLifecycleEvent[] = [];

    render(
      <InferenceForm
        contract={contract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
        executeInference={executeInference}
        onLifecycleEvent={(event) => events.push(event)}
      />,
    );

    fireEvent.change(screen.getByLabelText("Tenure"), { target: { value: "999999" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await screen.findByRole("alert");

    expect(JSON.stringify(events)).not.toContain("999999");
  });
});

// Project Spec S0151: normalizeInferenceRuntimeDiagnostic is the sole
// boundary that may turn an unknown backend `runtime_diagnostic` value into
// a safe, bounded InferenceRuntimeDiagnostic -- exercised directly here (pure
// function, no DOM, no network) for every normalization invariant.
describe("normalizeInferenceRuntimeDiagnostic (Project Spec S0151)", () => {
  it("normalizes every allowlisted diagnostic code", () => {
    const codes = [
      "INFERENCE_BUNDLE_UNAVAILABLE",
      "MODEL_ARTIFACT_UNAVAILABLE",
      "MODEL_ARTIFACT_HASH_MISMATCH",
      "RUNTIME_DEPENDENCY_UNAVAILABLE",
      "MODEL_DESERIALIZATION_FAILED",
      "PREDICTION_EXECUTION_FAILED",
      "RESULT_VALIDATION_FAILED",
      // Project Spec S0152
      "RUNTIME_INPUT_CONTRACT_INCONSISTENT",
    ];
    for (const code of codes) {
      expect(normalizeInferenceRuntimeDiagnostic({ code })).toEqual({ code });
    }
  });

  it("drops an unknown code", () => {
    expect(normalizeInferenceRuntimeDiagnostic({ code: "SOME_UNKNOWN_CODE" })).toBeUndefined();
  });

  it("drops a non-object, an array, and a missing code", () => {
    expect(normalizeInferenceRuntimeDiagnostic(undefined)).toBeUndefined();
    expect(normalizeInferenceRuntimeDiagnostic(null)).toBeUndefined();
    expect(normalizeInferenceRuntimeDiagnostic("RUNTIME_DEPENDENCY_UNAVAILABLE")).toBeUndefined();
    expect(normalizeInferenceRuntimeDiagnostic(["RUNTIME_DEPENDENCY_UNAVAILABLE"])).toBeUndefined();
    expect(normalizeInferenceRuntimeDiagnostic({})).toBeUndefined();
  });

  it("never retains a backend message or additional property", () => {
    const result = normalizeInferenceRuntimeDiagnostic({
      code: "RUNTIME_DEPENDENCY_UNAVAILABLE",
      message: "joblib is not installed",
      package: "joblib",
    });
    expect(result).toEqual({ code: "RUNTIME_DEPENDENCY_UNAVAILABLE" });
    expect(Object.keys(result!)).toEqual(["code"]);
  });
});

describe("InferenceForm runtime diagnostic propagation (Project Spec S0151)", () => {
  it("carries a normalized runtime diagnostic on the execution_failed lifecycle event", async () => {
    const executeInference = vi.fn(
      async (): Promise<InferenceExecutionResult> => ({
        ok: false,
        errorCode: "INFERENCE_FAILURE",
        runtimeDiagnostic: { code: "RUNTIME_DEPENDENCY_UNAVAILABLE" },
      }),
    );
    const events: InferenceLifecycleEvent[] = [];

    render(
      <InferenceForm
        contract={contract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
        executeInference={executeInference}
        onLifecycleEvent={(event) => events.push(event)}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await screen.findByRole("alert");

    expect(events).toEqual([
      { type: "started" },
      { type: "execution_failed", runtimeDiagnostic: { code: "RUNTIME_DEPENDENCY_UNAVAILABLE" } },
    ]);
  });

  it("carries the S0152 RUNTIME_INPUT_CONTRACT_INCONSISTENT diagnostic on the execution_failed lifecycle event", async () => {
    const executeInference = vi.fn(
      async (): Promise<InferenceExecutionResult> => ({
        ok: false,
        errorCode: "INFERENCE_FAILURE",
        runtimeDiagnostic: { code: "RUNTIME_INPUT_CONTRACT_INCONSISTENT" },
      }),
    );
    const events: InferenceLifecycleEvent[] = [];

    render(
      <InferenceForm
        contract={contract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
        executeInference={executeInference}
        onLifecycleEvent={(event) => events.push(event)}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await screen.findByRole("alert");

    expect(events).toEqual([
      { type: "started" },
      { type: "execution_failed", runtimeDiagnostic: { code: "RUNTIME_INPUT_CONTRACT_INCONSISTENT" } },
    ]);
  });

  it("emits the existing diagnostic-free execution_failed event when the executor reports none", async () => {
    const executeInference = vi.fn(
      async (): Promise<InferenceExecutionResult> => ({ ok: false, errorCode: "INFERENCE_FAILURE" }),
    );
    const events: InferenceLifecycleEvent[] = [];

    render(
      <InferenceForm
        contract={contract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
        executeInference={executeInference}
        onLifecycleEvent={(event) => events.push(event)}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await screen.findByRole("alert");

    expect(events).toEqual([{ type: "started" }, { type: "execution_failed" }]);
  });

  it("never carries a runtime diagnostic on a validation_failed lifecycle event, even if the executor attaches one", async () => {
    const executeInference = vi.fn(
      async (): Promise<InferenceExecutionResult> => ({
        ok: false,
        errorCode: "INVALID_PAYLOAD",
        runtimeDiagnostic: { code: "RUNTIME_DEPENDENCY_UNAVAILABLE" },
      }),
    );
    const events: InferenceLifecycleEvent[] = [];

    render(
      <InferenceForm
        contract={contract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
        executeInference={executeInference}
        onLifecycleEvent={(event) => events.push(event)}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await screen.findByRole("alert");

    expect(events).toEqual([{ type: "started" }, { type: "validation_failed" }]);
  });

  it("the public default executor never surfaces a runtime diagnostic even when the response body includes one", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(
          {
            error_code: "INFERENCE_FAILURE",
            runtime_diagnostic: { code: "RUNTIME_DEPENDENCY_UNAVAILABLE" },
          },
          503,
        ),
      ),
    );
    const events: InferenceLifecycleEvent[] = [];

    render(
      <InferenceForm
        contract={contract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
        onLifecycleEvent={(event) => events.push(event)}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await screen.findByRole("alert");

    expect(events).toEqual([{ type: "started" }, { type: "execution_failed" }]);
  });
});

// Project Spec S0250: forecasting input contract (public-contract v2
// history_series) dispatch, submission, result rendering, and validation
// normalization -- exercised independently of the scalar-feature coverage
// above, which must remain unaffected (confirmed by every prior describe
// block in this file still passing unchanged).
describe("InferenceForm univariate-forecasting dispatch (Project Spec S0250)", () => {
  const forecastingContract: ForecastingContractPayload = {
    schema_version: "2.0.0",
    problem_type: "univariate_forecasting",
    input_kind: "history_series",
    history_series: {
      time_index_field: { name: "period", label: "Period", value_kind: "calendar_period", display_order: 1 },
      target_field: { name: "passengers", label: "Passengers", value_kind: "number", display_order: 2 },
      frequency: "Monthly",
    },
    forecast: { forecast_horizon: 3, horizon_user_editable: false },
  };

  const availableForecastingResultContract: ResultContract = {
    status: "available",
    semantics: {
      schema_version: "univariate-forecasting-result-semantics.v1",
      problem_type: "univariate_forecasting",
      result_schema_version: "univariate-forecasting-result.v1",
      primary_output: "forecast_series",
      output_structure: "ordered_forecast_points",
      forecast_value_kind: "continuous_numeric",
      forecast_count_source: "forecast_horizon",
      model_descriptor: { model_family: "deterministic_seasonal_trend_ols", display_name: "Seasonal Trend" },
    },
  };

  const forecastingPresentation: UnivariateForecastingResultPresentation = {
    schema_version: "univariate-forecasting-result-presentation.v1",
    forecast_series_label: "Forecast",
    future_time_index_label: "Period",
    forecast_value_label: "Passengers",
    model_section_label: "Model",
    decimal_places: 1,
  };

  const validForecastResult = {
    schema_version: "univariate-forecasting-result.v1",
    problem_type: "univariate_forecasting",
    forecast_origin: "2026-01",
    frequency: "Monthly",
    forecast_horizon: 3,
    forecast_points: [
      { horizon_step: 1, future_time_index: "2026-02", forecast: 120.4 },
      { horizon_step: 2, future_time_index: "2026-03", forecast: 121.1 },
      { horizon_step: 3, future_time_index: "2026-04", forecast: 119.8 },
    ],
    model_descriptor: { model_family: "deterministic_seasonal_trend_ols", display_name: "Seasonal Trend" },
  };

  function fillFirstRow(periodValue: string, passengersValue: string) {
    fireEvent.change(screen.getAllByLabelText("Period")[0], { target: { value: periodValue } });
    fireEvent.change(screen.getAllByLabelText("Passengers")[0], { target: { value: passengersValue } });
  }

  it("renders HistorySeriesInput instead of the scalar field grid", () => {
    render(
      <InferenceForm
        contract={forecastingContract}
        slug={slug}
        resultContract={availableForecastingResultContract}
        resultPresentation={forecastingPresentation}
      />,
    );

    expect(screen.getByLabelText("Period")).toBeInTheDocument();
    expect(screen.getByLabelText("Passengers")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add row" })).toBeInTheDocument();
  });

  it("enables submit when the forecasting result contract is available", () => {
    render(
      <InferenceForm
        contract={forecastingContract}
        slug={slug}
        resultContract={availableForecastingResultContract}
        resultPresentation={forecastingPresentation}
      />,
    );

    expect(screen.getByRole("button", { name: "Submit" })).not.toBeDisabled();
  });

  it("disables submit when a forecasting input contract is paired with a non-forecasting result contract", () => {
    render(
      <InferenceForm
        contract={forecastingContract}
        slug={slug}
        resultContract={availableContract}
        resultPresentation={presentation}
      />,
    );

    expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();
  });

  it("disables submit when a scalar input contract is paired with a forecasting result contract", () => {
    render(
      <InferenceForm
        contract={contract}
        slug={slug}
        resultContract={availableForecastingResultContract}
        resultPresentation={forecastingPresentation}
      />,
    );

    expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();
  });

  it("submits the exact governed history payload shape, preserving user row order, with no horizon/frequency", async () => {
    const executeInference = vi.fn(
      async (): Promise<InferenceExecutionResult> => ({ ok: true, result: validForecastResult }),
    );

    render(
      <InferenceForm
        contract={forecastingContract}
        slug={slug}
        resultContract={availableForecastingResultContract}
        resultPresentation={forecastingPresentation}
        executeInference={executeInference}
      />,
    );

    fillFirstRow("2026-01", "100");
    fireEvent.click(screen.getByRole("button", { name: "Add row" }));
    fireEvent.change(screen.getAllByLabelText("Period")[1], { target: { value: "2025-12" } });
    fireEvent.change(screen.getAllByLabelText("Passengers")[1], { target: { value: "95" } });

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    await waitFor(() => expect(executeInference).toHaveBeenCalledTimes(1));
    expect(executeInference).toHaveBeenCalledWith(slug, {
      history: [
        { period: "2026-01", passengers: 100 },
        { period: "2025-12", passengers: 95 },
      ],
    });
  });

  it("serializes an ordinal_time index as a JSON integer and the target as a JSON number", async () => {
    const ordinalContract: ForecastingContractPayload = {
      ...forecastingContract,
      history_series: {
        ...forecastingContract.history_series,
        time_index_field: { name: "step", label: "Step", value_kind: "ordinal_time", display_order: 1 },
      },
    };
    const executeInference = vi.fn(
      async (_slug: string, _payload: InferenceExecutorPayload): Promise<InferenceExecutionResult> => ({
        ok: true,
        result: validForecastResult,
      }),
    );

    render(
      <InferenceForm
        contract={ordinalContract}
        slug={slug}
        resultContract={availableForecastingResultContract}
        resultPresentation={forecastingPresentation}
        executeInference={executeInference}
      />,
    );

    fireEvent.change(screen.getByLabelText("Step"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Passengers"), { target: { value: "12.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    await waitFor(() => expect(executeInference).toHaveBeenCalledTimes(1));
    const payload = executeInference.mock.calls[0][1] as { history: Array<Record<string, unknown>> };
    expect(payload.history[0].step).toBe(5);
    expect(Number.isInteger(payload.history[0].step)).toBe(true);
    expect(payload.history[0].passengers).toBe(12.5);
    expect(typeof payload.history[0].passengers).toBe("number");
  });

  it("renders the shared UnivariateForecastingResult on a valid forecast response, never ContinuousRegressionResult", async () => {
    const executeInference = vi.fn(
      async (): Promise<InferenceExecutionResult> => ({ ok: true, result: validForecastResult }),
    );

    render(
      <InferenceForm
        contract={forecastingContract}
        slug={slug}
        resultContract={availableForecastingResultContract}
        resultPresentation={forecastingPresentation}
        executeInference={executeInference}
      />,
    );

    fillFirstRow("2026-01", "100");
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    await waitFor(() => expect(screen.getByText("120.4")).toBeInTheDocument());
    expect(screen.getByText("Seasonal Trend")).toBeInTheDocument();
    expect(screen.queryByText(/Predicted value/)).not.toBeInTheDocument();
  });

  it("treats a malformed forecast success payload as the shared safe error state", async () => {
    const malformed = { ...validForecastResult, forecast_points: [] };
    const executeInference = vi.fn(
      async (): Promise<InferenceExecutionResult> => ({ ok: true, result: malformed }),
    );
    const events: InferenceLifecycleEvent[] = [];

    render(
      <InferenceForm
        contract={forecastingContract}
        slug={slug}
        resultContract={availableForecastingResultContract}
        resultPresentation={forecastingPresentation}
        executeInference={executeInference}
        onLifecycleEvent={(event) => events.push(event)}
      />,
    );

    fillFirstRow("2026-01", "100");
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong");
    expect(events.some((event) => event.type === "execution_failed")).toBe(true);
  });

  it("normalizes forecasting validation issues into resolved-label lifecycle events with no raw submitted values", async () => {
    const executeInference = vi.fn(
      async (): Promise<InferenceExecutionResult> => ({
        ok: false,
        errorCode: "INVALID_PAYLOAD",
        validationIssues: [
          { field: "history", violation: "forecasting_invalid_history_shape" },
          { field: "history[0]", violation: "forecasting_invalid_history_row" },
          { field: "history[0].period", violation: "forecasting_invalid_time_index" },
          { field: "history[0].passengers", violation: "forecasting_invalid_target_value" },
          { field: "some_unrecognized_path", violation: "forecasting_unknown_top_level_field" },
        ],
      }),
    );
    const events: InferenceLifecycleEvent[] = [];

    render(
      <InferenceForm
        contract={forecastingContract}
        slug={slug}
        resultContract={availableForecastingResultContract}
        resultPresentation={forecastingPresentation}
        executeInference={executeInference}
        onLifecycleEvent={(event) => events.push(event)}
      />,
    );

    fillFirstRow("2026-01", "100");
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    await waitFor(() => expect(events.some((event) => event.type === "validation_failed")).toBe(true));
    const validationEvent = events.find((event) => event.type === "validation_failed") as Extract<
      InferenceLifecycleEvent,
      { type: "validation_failed" }
    >;
    expect(validationEvent.issues).toEqual([
      { field: "history", fieldLabel: "History", violation: "forecasting_invalid_history_shape" },
      { field: "history[0]", fieldLabel: "History row", violation: "forecasting_invalid_history_row" },
      { field: "history[0].period", fieldLabel: "Period", violation: "forecasting_invalid_time_index" },
      { field: "history[0].passengers", fieldLabel: "Passengers", violation: "forecasting_invalid_target_value" },
      { field: "some_unrecognized_path", fieldLabel: "Field", violation: "forecasting_unknown_top_level_field" },
    ]);
    expect(JSON.stringify(validationEvent.issues)).not.toContain("2026-01");
  });

  it("never POSTs in previewMode, even for a forecasting contract", () => {
    const executeInference = vi.fn();

    render(
      <InferenceForm
        contract={forecastingContract}
        slug={slug}
        previewMode
        resultContract={availableForecastingResultContract}
        resultPresentation={forecastingPresentation}
        executeInference={executeInference}
      />,
    );

    fillFirstRow("2026-01", "100");
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    expect(executeInference).not.toHaveBeenCalled();
  });
});

// Project Spec S0266: bounded contract-derived explanation for a
// forecasting_minimum_history_not_met INVALID_PAYLOAD outcome, sourced only
// from the active forecasting public contract's S0266 input_guidance --
// never the backend's raw message. Exercised independently of the S0250
// forecasting dispatch coverage above.
describe("InferenceForm forecasting minimum-history contract-derived error message (Project Spec S0266)", () => {
  const forecastingContractWithGuidance: ForecastingContractPayload = {
    schema_version: "2.0.0",
    problem_type: "univariate_forecasting",
    input_kind: "history_series",
    history_series: {
      time_index_field: { name: "period", label: "Period", value_kind: "calendar_period", display_order: 1 },
      target_field: { name: "passengers", label: "Passengers", value_kind: "number", display_order: 2 },
      frequency: "Monthly",
      input_guidance: {
        minimum_observation_count: 1,
        required_anchor: { display_value: "1938-12" },
        continuity: "consecutive_by_frequency",
      },
    },
    forecast: {
      forecast_horizon: 3,
      horizon_user_editable: false,
      origin_behavior: "starts_after_last_history_observation",
    },
  };

  const forecastingContractWithoutGuidance: ForecastingContractPayload = {
    schema_version: "2.0.0",
    problem_type: "univariate_forecasting",
    input_kind: "history_series",
    history_series: {
      time_index_field: { name: "period", label: "Period", value_kind: "calendar_period", display_order: 1 },
      target_field: { name: "passengers", label: "Passengers", value_kind: "number", display_order: 2 },
      frequency: "Monthly",
    },
    forecast: { forecast_horizon: 3, horizon_user_editable: false },
  };

  const availableForecastingResultContract: ResultContract = {
    status: "available",
    semantics: {
      schema_version: "univariate-forecasting-result-semantics.v1",
      problem_type: "univariate_forecasting",
      result_schema_version: "univariate-forecasting-result.v1",
      primary_output: "forecast_series",
      output_structure: "ordered_forecast_points",
      forecast_value_kind: "continuous_numeric",
      forecast_count_source: "forecast_horizon",
      model_descriptor: { model_family: "deterministic_seasonal_trend_ols", display_name: "Seasonal Trend" },
    },
  };

  const forecastingPresentation: UnivariateForecastingResultPresentation = {
    schema_version: "univariate-forecasting-result-presentation.v1",
    forecast_series_label: "Forecast",
    future_time_index_label: "Period",
    forecast_value_label: "Passengers",
    model_section_label: "Model",
    decimal_places: 1,
  };

  function fillFirstRow(periodValue: string, passengersValue: string) {
    fireEvent.change(screen.getAllByLabelText("Period")[0], { target: { value: periodValue } });
    fireEvent.change(screen.getAllByLabelText("Passengers")[0], { target: { value: passengersValue } });
  }

  it("shows a bounded specific message for forecasting_minimum_history_not_met when valid guidance is present", async () => {
    const executeInference = vi.fn(
      async (): Promise<InferenceExecutionResult> => ({
        ok: false,
        errorCode: "INVALID_PAYLOAD",
        validationIssues: [{ field: "history", violation: "forecasting_minimum_history_not_met" }],
      }),
    );

    render(
      <InferenceForm
        contract={forecastingContractWithGuidance}
        slug={slug}
        resultContract={availableForecastingResultContract}
        resultPresentation={forecastingPresentation}
        executeInference={executeInference}
      />,
    );

    fillFirstRow("2026-01", "100");
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "History must include 1938-12 and contain at least 1 observation(s).",
    );
  });

  it("uses only public-contract values in the message, never the raw backend message text", async () => {
    const executeInference = vi.fn(
      async (): Promise<InferenceExecutionResult> => ({
        ok: false,
        errorCode: "INVALID_PAYLOAD",
        validationIssues: [{ field: "history", violation: "forecasting_minimum_history_not_met" }],
      }),
    );

    render(
      <InferenceForm
        contract={forecastingContractWithGuidance}
        slug={slug}
        resultContract={availableForecastingResultContract}
        resultPresentation={forecastingPresentation}
        executeInference={executeInference}
      />,
    );

    fillFirstRow("2026-01", "100");
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    const alert = await screen.findByRole("alert");
    expect(alert).not.toHaveTextContent(/development|training|holdout|fold/i);
  });

  it("falls back to the existing generic INVALID_PAYLOAD message for a legacy contract without guidance", async () => {
    const executeInference = vi.fn(
      async (): Promise<InferenceExecutionResult> => ({
        ok: false,
        errorCode: "INVALID_PAYLOAD",
        validationIssues: [{ field: "history", violation: "forecasting_minimum_history_not_met" }],
      }),
    );

    render(
      <InferenceForm
        contract={forecastingContractWithoutGuidance}
        slug={slug}
        resultContract={availableForecastingResultContract}
        resultPresentation={forecastingPresentation}
        executeInference={executeInference}
      />,
    );

    fillFirstRow("2026-01", "100");
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Some inputs are invalid. Please check your answers and try again.",
    );
  });

  it("preserves the existing generic message for another INVALID_PAYLOAD violation even when guidance is present", async () => {
    const executeInference = vi.fn(
      async (): Promise<InferenceExecutionResult> => ({
        ok: false,
        errorCode: "INVALID_PAYLOAD",
        validationIssues: [{ field: "history[0].period", violation: "forecasting_invalid_time_index" }],
      }),
    );

    render(
      <InferenceForm
        contract={forecastingContractWithGuidance}
        slug={slug}
        resultContract={availableForecastingResultContract}
        resultPresentation={forecastingPresentation}
        executeInference={executeInference}
      />,
    );

    fillFirstRow("2026-01", "100");
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Some inputs are invalid. Please check your answers and try again.",
    );
  });

  it("preserves the existing generic message when no validationIssues accompany INVALID_PAYLOAD", async () => {
    const executeInference = vi.fn(
      async (): Promise<InferenceExecutionResult> => ({ ok: false, errorCode: "INVALID_PAYLOAD" }),
    );

    render(
      <InferenceForm
        contract={forecastingContractWithGuidance}
        slug={slug}
        resultContract={availableForecastingResultContract}
        resultPresentation={forecastingPresentation}
        executeInference={executeInference}
      />,
    );

    fillFirstRow("2026-01", "100");
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Some inputs are invalid. Please check your answers and try again.",
    );
  });
});
