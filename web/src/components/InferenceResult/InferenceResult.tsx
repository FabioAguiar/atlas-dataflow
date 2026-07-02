import { StatusPill } from "../ui";
import { confidenceTone, formatResultLabel } from "./resultPresentation";

export type PredictionResult = {
  label: string;
  confidence: number;
};

type Props = {
  result: PredictionResult;
};

export default function InferenceResult({ result }: Props) {
  const confidencePercent = Math.round(result.confidence * 100) + "%";

  return (
    <section aria-label="Prediction Result">
      <h3>Prediction Result</h3>
      <p>
        <strong>Prediction:</strong> {formatResultLabel(result.label)}
      </p>
      <p>
        <strong>Confidence:</strong>{" "}
        <StatusPill tone={confidenceTone(result.confidence)}>{confidencePercent}</StatusPill>
      </p>
    </section>
  );
}
