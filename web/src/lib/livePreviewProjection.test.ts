import { describe, expect, it } from "vitest";

import {
  negativeScenarioProbability,
  positiveScenarioProbability,
  projectBinaryResultPreview,
  projectDatasetDetailPreview,
  projectHomeCardPreview,
  projectPerformanceFocusPreview,
} from "./livePreviewProjection";
import type { BinaryResultPresentation, BinaryResultSemantics } from "../components/ResultCard/types";

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
  source_name: "Atlas Release Registry",
  release_date_label: "2026-07-04",
  date_format: "yyyy-mm-dd" as const,
  home_card_icon: "telecom" as const,
  short_description: "Curated home card copy",
};

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
});

describe("projectDatasetDetailPreview", () => {
  it("keeps Source and Release metadata projected from the draft form", () => {
    const preview = projectDatasetDetailPreview(
      dataset,
      draftForm,
      {
        title: "Context title",
        summary: "Context summary",
        problem_type: "binary_classification",
        prediction_target_description: "Customer churn",
      },
      {
        fields: [{ name: "tenure" }, { name: "MonthlyCharges" }],
      },
      {
        evaluation: {
          sample_size: 7043,
        },
      },
    );

    expect(preview.metadata).toEqual([
      { label: "Source", value: "Atlas Release Registry" },
      { label: "Instances", value: "7,043" },
      { label: "Features", value: "2" },
      { label: "Target", value: "Customer churn" },
      {
        label: "Release",
        value: "2026-07-04",
        hint: "Format: yyyy-mm-dd",
      },
    ]);
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
