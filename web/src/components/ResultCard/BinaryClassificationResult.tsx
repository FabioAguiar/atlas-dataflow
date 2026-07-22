import { StatusPill } from "../ui";
import type { BinaryClassificationResult as BinaryClassificationResultData, BinaryResultPresentation, BinaryRiskBand } from "./types";

type Props = {
  result: BinaryClassificationResultData;
  presentation: BinaryResultPresentation;
};

type BandTone = "success" | "warning" | "danger";

const BAND_TONES: Record<string, BandTone> = {
  low: "success",
  medium: "warning",
  high: "danger",
};

function bandTone(bandId: string): BandTone {
  return BAND_TONES[bandId] ?? "warning";
}

/**
 * One deterministic formatting helper for probability-shaped [0,1] values --
 * always a percentage, at most one decimal place, and rounded (not simply
 * truncated) so small non-zero values do not collapse to "0%" when
 * avoidable. Every probability-shaped value in this component (positive-class
 * probability, threshold, band boundaries) goes through this single helper so
 * no value is rounded independently in more than one place.
 */
function formatProbability(value: number): string {
  const rounded = Math.round(value * 1000) / 10;
  const text = Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
  return `${text}%`;
}

function findBand(bands: BinaryRiskBand[], bandId: string): BinaryRiskBand | undefined {
  return bands.find((band) => band.band_id === bandId);
}

function interpretationLabel(presentation: BinaryResultPresentation, bandId: string): string {
  const labels = presentation.interpretation.labels as Record<string, string>;
  return labels[bandId]?.trim() || bandId;
}

export default function BinaryClassificationResult({ result, presentation }: Props) {
  const isPredictedPositive = result.decision.predicted_positive;
  const outcomeCopy = isPredictedPositive ? presentation.positive_outcome_copy : presentation.negative_outcome_copy;

  const selectedBandId = result.interpretation.band_id;
  const selectedBand = findBand(result.interpretation.bands, selectedBandId);
  const tone = bandTone(selectedBandId);
  const bandLabel = interpretationLabel(presentation, selectedBandId);

  const probabilityText = formatProbability(result.positive_class_probability);
  const thresholdText = formatProbability(result.decision.threshold);
  const rangeText = selectedBand
    ? `${formatProbability(selectedBand.lower_bound)}–${formatProbability(selectedBand.upper_bound)}`
    : null;

  const meterAccessibleLabel = `Positive class probability ${probabilityText}. Decision threshold ${thresholdText}. Band: ${bandLabel}.${
    rangeText ? ` Range: ${rangeText}.` : ""
  }`;

  return (
    <div className="binary-classification-result">
      <div className="binary-classification-result__outcome">
        <p className="binary-classification-result__label">{presentation.predicted_outcome_label}</p>
        <p className="binary-classification-result__outcome-value">{outcomeCopy}</p>
      </div>

      <div className="binary-classification-result__probability">
        <p className="binary-classification-result__label">{presentation.positive_class_probability_label}</p>
        <p className="binary-classification-result__probability-value">{probabilityText}</p>
      </div>

      <div
        className="probability-meter"
        role="img"
        aria-label={meterAccessibleLabel}
      >
        <div className="probability-meter__track">
          {result.interpretation.bands.map((band) => (
            <div
              key={band.band_id}
              className={`probability-meter__band probability-meter__band--${bandTone(band.band_id)}`}
              style={{
                left: `${band.lower_bound * 100}%`,
                width: `${Math.max(0, (band.upper_bound - band.lower_bound) * 100)}%`,
              }}
            />
          ))}
          <div className="probability-meter__threshold" style={{ left: `${result.decision.threshold * 100}%` }} />
          <div
            className="probability-meter__value"
            style={{ left: `${result.positive_class_probability * 100}%` }}
          />
        </div>
      </div>

      <p className="binary-classification-result__interpretation">
        <StatusPill tone={tone}>{bandLabel}</StatusPill>
      </p>

      <div className="binary-classification-result__model">
        <p className="binary-classification-result__label">{presentation.model_section_label}</p>
        <p className="binary-classification-result__model-value">{result.model_descriptor.display_name}</p>
      </div>
    </div>
  );
}
