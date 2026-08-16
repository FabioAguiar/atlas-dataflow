import { describe, expect, it } from "vitest";

import * as livePreviewProjection from "./livePreviewProjection";
import {
  negativeScenarioProbability,
  positiveScenarioProbability,
  projectBinaryResultPreview,
  projectDatasetDetailPreview,
  projectHomeCardPreview,
  projectPerformanceFocusPreview,
} from "./livePreviewProjection";
import type { BinaryResultPresentation, BinaryResultSemantics } from "../components/ResultCard/types";
import { resolveDatasetTargetDescription } from "./datasetPresentation";

const dataset = {
  dataset_slug: "telco-customer-churn",
  title: "Telco Customer Churn",
  summary: "Customer churn prediction dataset",
  domain: "telecom",
  visibility: "public",
  tags: ["telecom", "churn"],
};

const draftForm = {
  display_title: "Curated churn profile",
  display_subtitle: "Operator-authored public subtitle",
  problem_summary_title: "Curated problem summary title",
  problem_summary_body: "Curated problem summary body",
  source_name: "Atlas Release Registry",
  source_url: "https://example.org/registry",
  release_date_label: "2026-07-04",
  date_format: "yyyy-mm-dd" as const,
  canonical_name_fallback: true,
  home_card_icon: "telecom" as const,
  short_description: "Curated home card copy",
  performance_focus: { focus_id: "overall_discrimination" as const },
};

const context = {
  title: "Context title",
  summary: "Context summary",
  description: "Context description",
  use_case: "Context use case",
  problem_type: "binary_classification",
  prediction_target_description: "Customer churn",
};

const contract = { fields: [{ name: "tenure" }, { name: "MonthlyCharges" }] };
const metrics = { evaluation: { sample_size: 7043 } };
const multiclassResultContract = {
  status: "available" as const,
  semantics: {
    schema_version: "multiclass-result-semantics.v1" as const,
    problem_type: "multiclass_classification" as const,
    result_schema_version: "multiclass-classification-result.v1" as const,
    classes: [
      { class_id: "a", display_label: "A" },
      { class_id: "b", display_label: "B" },
      { class_id: "c", display_label: "C" },
    ],
    primary_output: "predicted_class" as const,
    probability_output: "class_probabilities" as const,
    decision: { strategy: "argmax" as const },
    model_descriptor: { model_family: "random_forest", display_name: "Forest" },
  },
};

describe("release-derived multiclass problem type", () => {
  it("overrides historical binary context on both previews", () => {
    expect(projectHomeCardPreview(dataset, draftForm, context, multiclassResultContract).problemType)
      .toBe("multiclass_classification");
    expect(projectDatasetDetailPreview(dataset, draftForm, context, contract, metrics, multiclassResultContract).analysisType)
      .toBe("multiclass_classification");
  });
});
// Project Spec S0205: the bounded public visualizations projection Instances
// now reads from -- metrics.evaluation.sample_size above no longer feeds it.
const visualizations = { charts: [], dataset_statistics: { instance_count: 7043 } };

describe("projectHomeCardPreview", () => {
  it("passes problemType from the loaded public context into the Home card props", () => {
    const preview = projectHomeCardPreview(
      dataset,
      draftForm,
      {
        title: "Telco Customer Churn",
        problem_type: "binary_classification",
      },
    );

    expect(preview.problemType).toBe("binary_classification");
    expect(preview.title).toBe("Curated churn profile");
    expect(preview.summary).toBe("Curated home card copy");
  });

  it("leaves problemType undefined when public context is unavailable", () => {
    const preview = projectHomeCardPreview(dataset, draftForm, null);

    expect(preview.problemType).toBeUndefined();
  });

  it("still owns short_description as the Home card summary (unchanged behavior)", () => {
    const preview = projectHomeCardPreview(
      dataset,
      { ...draftForm, short_description: "  ", display_subtitle: "Subtitle fallback" },
      null,
    );

    expect(preview.summary).toBe("Subtitle fallback");
  });
});

// Project Spec S0204: proves both Live Preview projection functions surface
// the current draft's Performance focus id (never a human label) so
// DatasetCard/DatasetDetailSurface can resolve the label through the shared
// performanceMetricMetadata authority.
describe("Live Preview projection: Performance focus id (Project Spec S0204)", () => {
  it("projectHomeCardPreview returns the current draft Performance focus id", () => {
    const preview = projectHomeCardPreview(dataset, draftForm, null);
    expect(preview.performanceFocusId).toBe("overall_discrimination");
  });

  it("projectHomeCardPreview's focus id changes deterministically with the draft", () => {
    const preview = projectHomeCardPreview(
      dataset,
      { ...draftForm, performance_focus: { focus_id: "probability_quality" } },
      null,
    );
    expect(preview.performanceFocusId).toBe("probability_quality");
  });

  it("projectHomeCardPreview never produces a human label, only the raw focus id", () => {
    const preview = projectHomeCardPreview(dataset, draftForm, null);
    expect(preview.performanceFocusId).not.toBe("Overall discrimination");
  });

  it("projectDatasetDetailPreview returns the current draft Performance focus id", () => {
    const preview = projectDatasetDetailPreview(dataset, draftForm, context, contract, metrics);
    expect(preview.performanceFocusId).toBe("overall_discrimination");
  });

  it("projectDatasetDetailPreview's focus id changes deterministically with the draft", () => {
    const preview = projectDatasetDetailPreview(
      dataset,
      { ...draftForm, performance_focus: { focus_id: "operational_decision" } },
      context,
      contract,
      metrics,
    );
    expect(preview.performanceFocusId).toBe("operational_decision");
  });

  it("projectDatasetDetailPreview never produces a human label, only the raw focus id", () => {
    const preview = projectDatasetDetailPreview(dataset, draftForm, context, contract, metrics);
    expect(preview.performanceFocusId).not.toBe("Overall discrimination");
  });
});

describe("projectDatasetDetailPreview: title precedence", () => {
  it("prefers the draft display_title over every fallback", () => {
    const preview = projectDatasetDetailPreview(dataset, draftForm, context, contract, metrics);
    expect(preview.datasetTitle).toBe("Curated churn profile");
  });

  it("falls back to technical context title when draft title is blank", () => {
    const preview = projectDatasetDetailPreview(
      dataset,
      { ...draftForm, display_title: "   " },
      context,
      contract,
      metrics,
    );
    expect(preview.datasetTitle).toBe("Context title");
  });

  it("falls back to the dataset listing title when draft and context titles are blank", () => {
    const preview = projectDatasetDetailPreview(
      dataset,
      { ...draftForm, display_title: "" },
      { ...context, title: undefined },
      contract,
      metrics,
    );
    expect(preview.datasetTitle).toBe("Telco Customer Churn");
  });

  it("never renders an empty title, falling back to the dataset slug", () => {
    const preview = projectDatasetDetailPreview(
      { ...dataset, title: "" },
      { ...draftForm, display_title: "" },
      { ...context, title: undefined },
      contract,
      metrics,
    );
    expect(preview.datasetTitle).toBe("telco-customer-churn");
  });
});

describe("projectDatasetDetailPreview: subtitle ownership", () => {
  it("uses the dedicated draft display_subtitle for the Dataset Detail subtitle", () => {
    const preview = projectDatasetDetailPreview(dataset, draftForm, context, contract, metrics);
    expect(preview.subtitle).toBe("Operator-authored public subtitle");
  });

  it("falls back to technical context summary, then description, when subtitle is blank", () => {
    const preview = projectDatasetDetailPreview(
      dataset,
      { ...draftForm, display_subtitle: "" },
      context,
      contract,
      metrics,
    );
    expect(preview.subtitle).toBe("Context summary");

    const descriptionOnly = projectDatasetDetailPreview(
      dataset,
      { ...draftForm, display_subtitle: "" },
      { ...context, summary: undefined },
      contract,
      metrics,
    );
    expect(descriptionOnly.subtitle).toBe("Context description");
  });

  it("never lets short_description or Home Card short description leak into the Dataset Detail subtitle", () => {
    const preview = projectDatasetDetailPreview(
      dataset,
      { ...draftForm, display_subtitle: "", short_description: "Home card only copy" } as typeof draftForm,
      { ...context, summary: undefined, description: undefined },
      contract,
      metrics,
    );
    expect(preview.subtitle).not.toBe("Home card only copy");
    expect(preview.subtitle).toBe(dataset.summary);
  });
});

describe("projectDatasetDetailPreview: Problem Summary", () => {
  it("prefers the draft Problem Summary title/body", () => {
    const preview = projectDatasetDetailPreview(dataset, draftForm, context, contract, metrics);
    expect(preview.problemSummaryTitle).toBe("Curated problem summary title");
    expect(preview.problemSummaryBody).toBe("Curated problem summary body");
  });

  it("falls back to 'Problem summary' when the draft title is blank", () => {
    const preview = projectDatasetDetailPreview(
      dataset,
      { ...draftForm, problem_summary_title: "   " },
      context,
      contract,
      metrics,
    );
    expect(preview.problemSummaryTitle).toBe("Problem summary");
  });

  it("falls back deterministically to technical context description, use_case, then summary", () => {
    const blankBody = { ...draftForm, problem_summary_body: "" };

    expect(
      projectDatasetDetailPreview(dataset, blankBody, context, contract, metrics).problemSummaryBody,
    ).toBe("Context description");

    expect(
      projectDatasetDetailPreview(
        dataset,
        blankBody,
        { ...context, description: undefined },
        contract,
        metrics,
      ).problemSummaryBody,
    ).toBe("Context use case");

    expect(
      projectDatasetDetailPreview(
        dataset,
        blankBody,
        { ...context, description: undefined, use_case: undefined },
        contract,
        metrics,
      ).problemSummaryBody,
    ).toBe("Context summary");

    expect(
      projectDatasetDetailPreview(
        dataset,
        blankBody,
        { ...context, description: undefined, use_case: undefined, summary: undefined },
        contract,
        metrics,
      ).problemSummaryBody,
    ).toBeNull();
  });

  it("never uses short_description as Problem Summary body", () => {
    const preview = projectDatasetDetailPreview(
      dataset,
      {
        ...draftForm,
        problem_summary_body: "",
        short_description: "Home card only copy",
      } as typeof draftForm,
      { ...context, description: undefined, use_case: undefined, summary: undefined },
      contract,
      metrics,
    );
    expect(preview.problemSummaryBody).toBeNull();
  });
});

describe("projectDatasetDetailPreview: Source", () => {
  it("links the Source name when the URL is safe", () => {
    const preview = projectDatasetDetailPreview(dataset, draftForm, context, contract, metrics);
    const source = preview.metadata.find((item) => item.label === "Source");
    expect(source).toEqual({ label: "Source", value: "Atlas Release Registry", href: "https://example.org/registry" });
  });

  it("renders the plain Source name when the URL is missing or unsafe", () => {
    const missingUrl = projectDatasetDetailPreview(
      dataset,
      { ...draftForm, source_url: "" },
      context,
      contract,
      metrics,
    );
    expect(missingUrl.metadata.find((item) => item.label === "Source")).toEqual({
      label: "Source",
      value: "Atlas Release Registry",
      href: undefined,
    });

    const unsafeUrl = projectDatasetDetailPreview(
      dataset,
      { ...draftForm, source_url: "javascript:alert(1)" },
      context,
      contract,
      metrics,
    );
    expect(unsafeUrl.metadata.find((item) => item.label === "Source")).toEqual({
      label: "Source",
      value: "Atlas Release Registry",
      href: undefined,
    });
  });

  it("renders Pending (a null value) when Source name is missing, even if a URL exists", () => {
    const preview = projectDatasetDetailPreview(
      dataset,
      { ...draftForm, source_name: "   " },
      context,
      contract,
      metrics,
    );
    expect(preview.metadata.find((item) => item.label === "Source")).toEqual({
      label: "Source",
      value: null,
      href: undefined,
    });
  });
});

describe("projectDatasetDetailPreview: Release date", () => {
  it("formats a valid date-only value in all three supported formats", () => {
    const ddmmyyyy = projectDatasetDetailPreview(
      dataset,
      { ...draftForm, release_date_label: "2026-07-12", date_format: "dd/mm/yyyy" },
      context,
      contract,
      metrics,
    );
    expect(ddmmyyyy.metadata.find((item) => item.label === "Release")).toEqual({
      label: "Release",
      value: "12/07/2026",
      hint: "dd/mm/yyyy",
    });

    const mmddyyyy = projectDatasetDetailPreview(
      dataset,
      { ...draftForm, release_date_label: "2026-07-12", date_format: "mm/dd/yyyy" },
      context,
      contract,
      metrics,
    );
    expect(mmddyyyy.metadata.find((item) => item.label === "Release")).toEqual({
      label: "Release",
      value: "07/12/2026",
      hint: "mm/dd/yyyy",
    });

    const yyyymmdd = projectDatasetDetailPreview(
      dataset,
      { ...draftForm, release_date_label: "2026-07-12", date_format: "yyyy-mm-dd" },
      context,
      contract,
      metrics,
    );
    expect(yyyymmdd.metadata.find((item) => item.label === "Release")).toEqual({
      label: "Release",
      value: "2026-07-12",
      hint: "yyyy-mm-dd",
    });
  });

  it("renders Pending with no hint for an invalid date-only value", () => {
    const preview = projectDatasetDetailPreview(
      dataset,
      { ...draftForm, release_date_label: "2026-02-30", date_format: "yyyy-mm-dd" },
      context,
      contract,
      metrics,
    );
    expect(preview.metadata.find((item) => item.label === "Release")).toEqual({
      label: "Release",
      value: null,
      hint: undefined,
    });
  });

  it("renders Pending with no hint for a missing date value", () => {
    const preview = projectDatasetDetailPreview(
      dataset,
      { ...draftForm, release_date_label: "", date_format: "yyyy-mm-dd" },
      context,
      contract,
      metrics,
    );
    expect(preview.metadata.find((item) => item.label === "Release")).toEqual({
      label: "Release",
      value: null,
      hint: undefined,
    });
  });
});

describe("projectDatasetDetailPreview: remaining metadata", () => {
  it("keeps Instances, Features and Target metadata from technical context/contract/visualizations", () => {
    const preview = projectDatasetDetailPreview(
      dataset,
      draftForm,
      context,
      contract,
      metrics,
      undefined,
      visualizations,
    );
    expect(preview.metadata).toEqual([
      { label: "Source", value: "Atlas Release Registry", href: "https://example.org/registry" },
      { label: "Instances", value: "7,043" },
      { label: "Features", value: "2" },
      { label: "Target", value: "Customer churn" },
      { label: "Release", value: "2026-07-04", hint: "yyyy-mm-dd" },
    ]);
  });
});

// Project Spec S0205: Instances now reads the bounded public visualizations
// projection's dataset_statistics.instance_count -- never
// metrics.evaluation.sample_size, and never a sum over chart values.
describe("projectDatasetDetailPreview: Instances metadata (Project Spec S0205)", () => {
  it("reads Instances from visualizations.dataset_statistics.instance_count, ignoring a conflicting metrics.evaluation.sample_size", () => {
    const conflictingMetrics = { evaluation: { sample_size: 999 } };
    const preview = projectDatasetDetailPreview(
      dataset,
      draftForm,
      context,
      contract,
      conflictingMetrics,
      undefined,
      visualizations,
    );
    expect(preview.metadata.find((item) => item.label === "Instances")?.value).toBe("7,043");
  });

  it("renders Pending (a null value) when visualizations carries no dataset_statistics", () => {
    const preview = projectDatasetDetailPreview(
      dataset,
      draftForm,
      context,
      contract,
      metrics,
      undefined,
      { charts: [] },
    );
    expect(preview.metadata.find((item) => item.label === "Instances")?.value).toBeNull();
  });

  it("renders Pending when no visualizations payload is provided at all", () => {
    const preview = projectDatasetDetailPreview(dataset, draftForm, context, contract, metrics);
    expect(preview.metadata.find((item) => item.label === "Instances")?.value).toBeNull();
  });

  it("never sums Target Distribution chart values -- only an already-declared dataset_statistics.instance_count is used", () => {
    const preview = projectDatasetDetailPreview(
      dataset,
      draftForm,
      context,
      contract,
      metrics,
      undefined,
      {
        charts: [
          {
            id: "target_distribution",
            title: "target distribution",
            type: "bar" as const,
            data: [
              { name: "No", value: 5174 },
              { name: "Yes", value: 1869 },
            ],
          },
        ],
      },
    );
    expect(preview.metadata.find((item) => item.label === "Instances")?.value).toBeNull();
  });

  it("leaves Source/Features/Target/Release metadata unaffected", () => {
    const preview = projectDatasetDetailPreview(
      dataset,
      draftForm,
      context,
      contract,
      metrics,
      undefined,
      visualizations,
    );
    expect(preview.metadata.find((item) => item.label === "Source")?.value).toBe("Atlas Release Registry");
    expect(preview.metadata.find((item) => item.label === "Features")?.value).toBe("2");
    expect(preview.metadata.find((item) => item.label === "Target")?.value).toBe("Customer churn");
    expect(preview.metadata.find((item) => item.label === "Release")?.value).toBe("2026-07-04");
  });
});

// Project Spec S0154: the shared, side-effect-free Target metadata helper --
// both the public Dataset Detail (DatasetPage.tsx) and this module's own
// projectDatasetDetailPreview call resolveDatasetTargetDescription directly,
// so this is the single owner of the precedence/formatting/fallback rule.
describe("resolveDatasetTargetDescription (shared Target helper, Project Spec S0154)", () => {
  const availableSemanticsContract = {
    status: "available" as const,
    semantics: {
      positive_class: { event_label: "Churn", class_id: "Yes" },
      negative_class: { class_id: "No" },
    },
  };

  it("prefers available result semantics over a conflicting context description", () => {
    expect(resolveDatasetTargetDescription(availableSemanticsContract, "A conflicting published description")).toBe(
      "Churn (Yes/No)",
    );
  });

  it("falls back to a nonblank context description when result semantics are unavailable", () => {
    expect(resolveDatasetTargetDescription({ status: "unavailable" }, "Customer churn")).toBe("Customer churn");
    expect(resolveDatasetTargetDescription({ status: "idle" }, "Customer churn")).toBe("Customer churn");
    expect(resolveDatasetTargetDescription({ status: "loading" }, "Customer churn")).toBe("Customer churn");
    expect(resolveDatasetTargetDescription({ status: "transport_failure" }, "Customer churn")).toBe(
      "Customer churn",
    );
    expect(resolveDatasetTargetDescription({ status: "incompatible" }, "Customer churn")).toBe("Customer churn");
  });

  it("returns null when neither result semantics nor a context description are available", () => {
    expect(resolveDatasetTargetDescription({ status: "unavailable" }, undefined)).toBeNull();
    expect(resolveDatasetTargetDescription(null, null)).toBeNull();
  });

  it("trims whitespace on every semantics field and the context description, treating whitespace-only as absent", () => {
    expect(
      resolveDatasetTargetDescription(
        {
          status: "available",
          semantics: {
            positive_class: { event_label: "  Churn  ", class_id: " Yes " },
            negative_class: { class_id: " No " },
          },
        },
        undefined,
      ),
    ).toBe("Churn (Yes/No)");

    expect(resolveDatasetTargetDescription({ status: "unavailable" }, "   ")).toBeNull();
  });

  it("falls back rather than emitting malformed punctuation when semantics are incomplete", () => {
    expect(
      resolveDatasetTargetDescription(
        { status: "available", semantics: { positive_class: { event_label: "Churn", class_id: "" }, negative_class: { class_id: "No" } } },
        "Fallback description",
      ),
    ).toBe("Fallback description");

    expect(
      resolveDatasetTargetDescription(
        { status: "available", semantics: { positive_class: { event_label: "", class_id: "Yes" }, negative_class: { class_id: "No" } } },
        "Fallback description",
      ),
    ).toBe("Fallback description");

    expect(
      resolveDatasetTargetDescription(
        { status: "available", semantics: { positive_class: { event_label: "Churn", class_id: "Yes" }, negative_class: { class_id: "" } } },
        "Fallback description",
      ),
    ).toBe("Fallback description");
  });

  it("never reads problem_type -- an object carrying only problem_type never produces Target content", () => {
    expect(
      resolveDatasetTargetDescription(
        { status: "available", problem_type: "binary_classification" } as unknown as Parameters<
          typeof resolveDatasetTargetDescription
        >[0],
        undefined,
      ),
    ).toBeNull();
  });

  it("also accepts bare result semantics passed directly (no status wrapper), treating them as available", () => {
    expect(
      resolveDatasetTargetDescription(
        { positive_class: { event_label: "Churn", class_id: "Yes" }, negative_class: { class_id: "No" } },
        "Fallback description",
      ),
    ).toBe("Churn (Yes/No)");
  });
});

// Project Spec S0154: proves the public Dataset Detail and the Dataset Admin
// Live Preview projection both derive Target through the exact same shared
// helper -- not two independently-maintained formatters that merely happen
// to agree today.
describe("projectDatasetDetailPreview: Target metadata parity (Project Spec S0154)", () => {
  const churnResultContract: { status: "available"; semantics: BinaryResultSemantics } = {
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
          { band_id: "high", lower_bound: 0.65, upper_bound: 1 },
        ],
      },
      model_descriptor: { model_family: "gradient_boosting", display_name: "Gradient Boosting" },
    },
  };

  it("renders through the shared helper's exact formatted output when available result semantics are fed in, even against a conflicting context description", () => {
    const preview = projectDatasetDetailPreview(
      dataset,
      draftForm,
      { ...context, prediction_target_description: "A conflicting published description" },
      contract,
      metrics,
      churnResultContract,
    );
    const target = preview.metadata.find((item) => item.label === "Target");
    expect(target?.value).toBe("Churn (Yes/No)");
    expect(target?.value).toBe(
      resolveDatasetTargetDescription(churnResultContract, "A conflicting published description"),
    );
  });

  it("no longer shows Pending when valid result semantics exist, even with no context description at all", () => {
    const preview = projectDatasetDetailPreview(
      dataset,
      draftForm,
      { ...context, prediction_target_description: undefined },
      contract,
      metrics,
      churnResultContract,
    );
    expect(preview.metadata.find((item) => item.label === "Target")?.value).toBe("Churn (Yes/No)");
  });

  it("shows Pending (a null value) only when both result semantics and a context description are unavailable", () => {
    const stillFallsBack = projectDatasetDetailPreview(
      dataset,
      draftForm,
      context,
      contract,
      metrics,
      { status: "unavailable" },
    );
    expect(stillFallsBack.metadata.find((item) => item.label === "Target")?.value).toBe("Customer churn");

    const pending = projectDatasetDetailPreview(
      dataset,
      draftForm,
      { ...context, prediction_target_description: undefined },
      contract,
      metrics,
      { status: "unavailable" },
    );
    expect(pending.metadata.find((item) => item.label === "Target")?.value).toBeNull();
  });

  it("never uses problem_type as the Target fallback even when the context carries one and semantics/description are both unavailable", () => {
    const preview = projectDatasetDetailPreview(
      dataset,
      draftForm,
      { ...context, prediction_target_description: undefined, problem_type: "binary_classification" },
      contract,
      metrics,
      { status: "incompatible" },
    );
    expect(preview.metadata.find((item) => item.label === "Target")?.value).toBeNull();
  });

  it("treats idle/loading/transport_failure/incompatible result-contract states identically to unavailable for Target fallback purposes", () => {
    for (const status of ["idle", "loading", "transport_failure", "incompatible"] as const) {
      const preview = projectDatasetDetailPreview(dataset, draftForm, context, contract, metrics, { status });
      expect(preview.metadata.find((item) => item.label === "Target")?.value).toBe("Customer churn");
    }
  });
});

describe("no Model Card projection export", () => {
  it("no longer exports a Model Card preview projection", () => {
    expect("projectModelCardPreview" in livePreviewProjection).toBe(false);
    expect("ModelCardPreview" in livePreviewProjection).toBe(false);
  });
});

describe("projectPerformanceFocusPreview", () => {
  it("projects checked scores in deterministic order and keeps the draft highlight", () => {
    expect(projectPerformanceFocusPreview({
      focus_id: "positive_class_detection",
      highlighted_score_id: "precision",
      scores: [
        { score_id: "recall", display_label: "Recall", value: "0.57", value_source: "manual", order: 9, visible: false },
        { score_id: "precision", display_label: "Precision", value: "0.68", value_source: "manual", order: 8, visible: true },
        { score_id: "f1_score", display_label: "F1-score", value: "0.62", value_source: "manual", order: 7, visible: true },
      ],
    })).toEqual({
      focus_id: "positive_class_detection",
      highlighted_score_id: "precision",
      visible_scores: [
        { score_id: "precision", display_label: "Precision", value: "0.68", value_source: "manual", order: 0 },
        { score_id: "f1_score", display_label: "F1-score", value: "0.62", value_source: "manual", order: 1 },
      ],
    });
  });

  it("returns null when no visible score can own the highlight", () => {
    expect(projectPerformanceFocusPreview({
      focus_id: "overall_discrimination",
      highlighted_score_id: "roc_auc",
      scores: [{ score_id: "roc_auc", display_label: "ROC-AUC", value: "0.85", value_source: "manual", order: 0, visible: false }],
    })).toBeNull();
  });
});

const semantics: BinaryResultSemantics = {
  schema_version: "binary-result-semantics.v1",
  problem_type: "binary_classification",
  result_schema_version: "binary-classification-result.v1",
  primary_output: "positive_class_probability",
  positive_class: { class_id: "churn", event_label: "Customer churns" },
  negative_class: { class_id: "retained" },
  decision: { threshold: 0.6 },
  interpretation: {
    preset: "risk",
    bands: [
      { band_id: "low", lower_bound: 0, upper_bound: 0.3 },
      { band_id: "medium", lower_bound: 0.3, upper_bound: 0.7 },
      { band_id: "high", lower_bound: 0.7, upper_bound: 1 },
    ],
  },
  model_descriptor: { model_family: "linear", display_name: "Retention model" },
};

const presentation: BinaryResultPresentation = {
  schema_version: "binary-result-presentation.v1",
  positive_class_probability_label: "Churn probability",
  predicted_outcome_label: "Predicted status",
  positive_outcome_copy: "Likely to churn",
  negative_outcome_copy: "Likely to stay",
  model_section_label: "Scoring model",
  interpretation: { preset: "risk", labels: { high: "Elevated", medium: "Watch", low: "Limited" } },
};

describe("projectBinaryResultPreview", () => {
  it("derives positive and negative results from the governed threshold", () => {
    const positive = projectBinaryResultPreview(semantics, presentation, 0.6);
    const negative = projectBinaryResultPreview(semantics, presentation, 0.2);

    expect(positive?.decision.predicted_positive).toBe(true);
    expect(positive?.predicted_class.class_id).toBe("churn");
    expect(positive?.interpretation.band_id).toBe("medium");
    expect(negative?.decision.predicted_positive).toBe(false);
    expect(negative?.predicted_class.class_id).toBe("retained");
    expect(negative?.class_probabilities.reduce((sum, item) => sum + item.probability, 0)).toBe(1);
  });

  it("uses the final band for probability one and rejects ambiguous bands", () => {
    expect(projectBinaryResultPreview(semantics, presentation, 1)?.interpretation.band_id).toBe("high");
    const invalid = { ...semantics, interpretation: { ...semantics.interpretation, bands: semantics.interpretation.bands.slice(0, 2) } };
    expect(projectBinaryResultPreview(invalid, presentation, 0.5)).toBeNull();
  });

  it("derives scenario values from threshold, including zero and one edges", () => {
    expect(positiveScenarioProbability(0.6)).toBe(0.8);
    expect(positiveScenarioProbability(1)).toBe(1);
    expect(negativeScenarioProbability(0.6)).toBe(0.3);
    expect(negativeScenarioProbability(0)).toBeNull();
  });
});
