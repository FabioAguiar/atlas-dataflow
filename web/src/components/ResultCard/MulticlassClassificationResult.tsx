import type { CSSProperties } from "react";
import type { MulticlassClassificationResult as ResultData, MulticlassResultPresentation } from "./types";

type Props = { result: ResultData; presentation: MulticlassResultPresentation };

function formatProbability(value: number): string {
  const rounded = Math.round(value * 1000) / 10;
  return `${Number.isInteger(rounded) ? rounded : rounded.toFixed(1)}%`;
}

export default function MulticlassClassificationResult({ result, presentation }: Props) {
  const predicted = result.class_probabilities.find((entry) => entry.class_id === result.predicted_class.class_id)!;
  const sorted = result.class_probabilities
    .map((entry, index) => ({ entry, index }))
    .sort((left, right) => right.entry.probability - left.entry.probability || left.index - right.index);

  return (
    <div className="multiclass-classification-result">
      <div className="multiclass-classification-result__prediction">
        <p className="multiclass-classification-result__label">{presentation.predicted_class_label}</p>
        <p className="multiclass-classification-result__prediction-value">
          <span>{result.predicted_class.display_label}</span>
          <strong>{formatProbability(predicted.probability)}</strong>
        </p>
      </div>
      <div className="multiclass-classification-result__distribution">
        <p className="multiclass-classification-result__label">{presentation.class_probability_distribution_label}</p>
        <ul className="multiclass-probability-list">
          {sorted.map(({ entry }) => {
            const formatted = formatProbability(entry.probability);
            const percentageValue = Math.round(entry.probability * 1000) / 10;
            return (
              <li className="multiclass-probability-list__item" key={entry.class_id}>
                <div className="multiclass-probability-list__copy"><span>{entry.display_label}</span><strong>{formatted}</strong></div>
                <div className="multiclass-probability-list__track" role="progressbar" aria-label={`${entry.display_label} probability`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percentageValue} aria-valuetext={formatted}>
                  <span className="multiclass-probability-list__bar" style={{ "--multiclass-probability": `${entry.probability * 100}%` } as CSSProperties} />
                </div>
              </li>
            );
          })}
        </ul>
      </div>
      <div className="multiclass-classification-result__model">
        <p className="multiclass-classification-result__label">{presentation.model_section_label}</p>
        <p className="multiclass-classification-result__model-value">{result.model_descriptor.display_name}</p>
      </div>
    </div>
  );
}
