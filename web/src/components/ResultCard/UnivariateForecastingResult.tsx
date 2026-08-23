import type { UnivariateForecastingResult as ResultData, UnivariateForecastingResultPresentation } from "./types";

type Props = { result: ResultData; presentation: UnivariateForecastingResultPresentation };

/**
 * Project Spec S0249: display formatting is presentation-only -- the raw
 * technical forecast value is never mutated or rounded, only its rendered
 * text uses presentation.decimal_places.
 */
function formatForecastValue(value: number, decimalPlaces: number): string {
  return value.toFixed(decimalPlaces);
}

export default function UnivariateForecastingResult({ result, presentation }: Props) {
  return (
    <div className="univariate-forecasting-result">
      <div className="univariate-forecasting-result__series">
        <p className="univariate-forecasting-result__label">{presentation.forecast_series_label}</p>
        <table className="univariate-forecasting-result__table">
          <thead>
            <tr>
              <th scope="col">{presentation.future_time_index_label}</th>
              <th scope="col">{presentation.forecast_value_label}</th>
            </tr>
          </thead>
          <tbody>
            {result.forecast_points.map((point) => (
              <tr key={point.horizon_step}>
                <td>{point.future_time_index}</td>
                <td className="univariate-forecasting-result__value">
                  {formatForecastValue(point.forecast, presentation.decimal_places)}
                  {presentation.value_unit_label && (
                    <span className="univariate-forecasting-result__unit"> {presentation.value_unit_label}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="univariate-forecasting-result__model">
        <p className="univariate-forecasting-result__label">Model</p>
        <p className="univariate-forecasting-result__model-value">{result.model_descriptor.display_name}</p>
      </div>
    </div>
  );
}
