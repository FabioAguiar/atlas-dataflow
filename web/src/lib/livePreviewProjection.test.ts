import { describe, expect, it } from "vitest";

import { projectDatasetDetailPreview, projectHomeCardPreview, projectPerformanceFocusPreview } from "./livePreviewProjection";

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
