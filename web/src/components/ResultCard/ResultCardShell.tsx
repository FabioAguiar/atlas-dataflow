import type { ReactNode } from "react";

/**
 * Project Spec S0112: the stable visual and accessible Result Card boundary
 * shared by both public dataset routes. Owns idle, unavailable, submitting,
 * error, and success states behind one exact, stable accessible contract so
 * S0113 can later reuse it in Dataset Admin without a public-route
 * dependency.
 */
export type ResultCardShellProps =
  | { state: "idle" }
  | { state: "unavailable" }
  | { state: "submitting" }
  | { state: "error"; message: string }
  | { state: "success"; children: ReactNode };

export default function ResultCardShell(props: ResultCardShellProps) {
  return (
    <section
      className={`inference-result result-panel result-panel--${props.state}`}
      aria-label="Prediction result"
      aria-live="polite"
    >
      <h3 className="result-panel__heading">Result</h3>

      {props.state === "idle" && (
        <p className="result-panel__placeholder">Submit the form to see the prediction.</p>
      )}

      {props.state === "unavailable" && (
        <p className="result-panel__unavailable">
          This active release does not currently expose a compatible result.
        </p>
      )}

      {props.state === "submitting" && (
        <p className="result-panel__loading">Generating prediction…</p>
      )}

      {props.state === "error" && (
        <p className="result-panel__error" role="alert">
          {props.message}
        </p>
      )}

      {props.state === "success" && <div className="result-panel__content">{props.children}</div>}
    </section>
  );
}
