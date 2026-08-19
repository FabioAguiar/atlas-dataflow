import type { ContinuousRegressionResult as ResultData, ContinuousRegressionResultPresentation } from "./types";

type Props = { result: ResultData; presentation: ContinuousRegressionResultPresentation };

/**
 * Project Spec S0229: display formatting is presentation-only -- the raw
 * technical predicted_value is never mutated or rounded, only its rendered
 * text uses presentation.decimal_places.
 */
function formatPredictedValue(value: number, decimalPlaces: number): string {
  return value.toFixed(decimalPlaces);
}

export default function ContinuousRegressionResult({ result, presentation }: Props) {
  const formattedValue = formatPredictedValue(result.predicted_value, presentation.decimal_places);

  return (
    <div className="continuous-regression-result">
      <div className="continuous-regression-result__prediction">
        <p className="continuous-regression-result__label">{presentation.predicted_value_label}</p>
        <p className="continuous-regression-result__prediction-value">
          <strong>{formattedValue}</strong>
          {presentation.value_unit_label && (
            <span className="continuous-regression-result__unit">{presentation.value_unit_label}</span>
          )}
        </p>
      </div>
      <div className="continuous-regression-result__model">
        <p className="continuous-regression-result__label">{presentation.model_section_label}</p>
        <p className="continuous-regression-result__model-value">{result.model_descriptor.display_name}</p>
      </div>
    </div>
  );
}
