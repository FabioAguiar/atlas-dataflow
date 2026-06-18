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
        <strong>Prediction:</strong> {result.label}
      </p>
      <p>
        <strong>Confidence:</strong> {confidencePercent}
      </p>
    </section>
  );
}
