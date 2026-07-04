import { StatusPill } from "../ui";
import { confidenceTone, formatResultLabel, type ConfidenceTone } from "./resultPresentation";

export type PredictionResult = {
  label: string;
  confidence: number;
};

/**
 * Optional, presentation-only label overrides -- sourced from a dataset's
 * result_card curated copy (probability_label, model_label, badge_labels) in
 * admin Live Preview. Undefined fields fall back to this component's
 * existing hardcoded defaults, so the real public predict flow (which never
 * passes previewLabels) renders exactly as before.
 */
export type ResultPreviewLabels = {
  confidenceLabel?: string;
  modelLabel?: string;
  toneLabels?: Partial<Record<ConfidenceTone, string>>;
};

type Props = {
  result: PredictionResult;
  previewLabels?: ResultPreviewLabels;
};

export default function InferenceResult({ result, previewLabels }: Props) {
  const confidencePercent = Math.round(result.confidence * 100) + "%";
  const tone = confidenceTone(result.confidence);
  const toneLabel = previewLabels?.toneLabels?.[tone];

  return (
    <section aria-label="Result">
      <h3>Result</h3>
      <p>
        <strong>Prediction:</strong> {formatResultLabel(result.label)}
      </p>
      <p>
        <strong>{previewLabels?.confidenceLabel?.trim() || "Confidence:"}</strong>{" "}
        <StatusPill tone={tone}>{toneLabel?.trim() || confidencePercent}</StatusPill>
      </p>
      {previewLabels?.modelLabel?.trim() && (
        <p>
          <strong>Model:</strong> {previewLabels.modelLabel.trim()}
        </p>
      )}
    </section>
  );
}
