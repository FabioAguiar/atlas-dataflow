import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import InferenceForm, { type ContractPayload } from "./InferenceForm";
import type { BinaryResultContract, BinaryResultPresentation } from "../ResultCard/types";

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
