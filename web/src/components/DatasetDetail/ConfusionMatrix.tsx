import type { CSSProperties } from "react";
import { Card } from "../ui";
import type { VisualizationsPayload } from "./TargetDistribution";

type ConfusionMatrixProps = {
  visualizations: VisualizationsPayload | null;
};

type ValidConfusionMatrix = {
  orderedClassIds: string[];
  matrix: number[][];
};

const ROW_SUM_TOLERANCE = 1e-3;

/**
 * Project Spec S0215: defensive re-validation of the public confusion_matrix
 * projection, independent of the backend's own bounded projection --
 * requires at least 3 unique class ids, an exact NxN shape, every cell
 * finite in [0,1], and every true-class row to sum to 1 within a small
 * display-tolerance. Anything malformed renders nothing at all (never a
 * placeholder), so a binary release (which never carries this field) stays
 * visually unchanged.
 */
function getValidConfusionMatrix(source: unknown): ValidConfusionMatrix | null {
  if (!source || typeof source !== "object") {
    return null;
  }
  const candidate = source as Record<string, unknown>;
  const orderedClassIds = candidate.ordered_class_ids;
  const matrix = candidate.matrix;

  if (
    !Array.isArray(orderedClassIds) ||
    orderedClassIds.length < 3 ||
    !orderedClassIds.every((id): id is string => typeof id === "string" && id.length > 0) ||
    new Set(orderedClassIds).size !== orderedClassIds.length
  ) {
    return null;
  }
  const classCount = orderedClassIds.length;
  if (!Array.isArray(matrix) || matrix.length !== classCount) {
    return null;
  }
  for (const row of matrix) {
    if (!Array.isArray(row) || row.length !== classCount) {
      return null;
    }
    let rowSum = 0;
    for (const cell of row) {
      if (typeof cell !== "number" || !Number.isFinite(cell) || cell < 0 || cell > 1) {
        return null;
      }
      rowSum += cell;
    }
    if (Math.abs(rowSum - 1) > ROW_SUM_TOLERANCE) {
      return null;
    }
  }

  return { orderedClassIds, matrix: matrix as number[][] };
}

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

/**
 * Renders every cell's percentage as text -- color intensity (driven by a
 * CSS custom property consumed in App.css) is a secondary visual
 * enhancement only, never the sole channel conveying a cell's value.
 */
function cellStyle(value: number): CSSProperties {
  return { "--confusion-matrix-cell-intensity": value } as CSSProperties;
}

export default function ConfusionMatrix({ visualizations }: ConfusionMatrixProps) {
  const validated = getValidConfusionMatrix(visualizations?.confusion_matrix);
  if (!validated) {
    return null;
  }
  const { orderedClassIds, matrix } = validated;

  return (
    <Card className="dataset-detail-visualization dataset-detail-visualization--confusion-matrix">
      <h3>Confusion Matrix</h3>
      <p className="confusion-matrix__caption">
        Each row shows how the model classified actual instances of one class, as a share of that class&apos;s total.
      </p>
      <div className="confusion-matrix__scroll">
        <table aria-label="Confusion matrix" className="confusion-matrix__table">
          <thead>
            <tr>
              <th className="confusion-matrix__corner" scope="col">
                <span className="confusion-matrix__axis-label confusion-matrix__axis-label--row">Actual class</span>
                <span className="confusion-matrix__axis-label confusion-matrix__axis-label--column">Predicted class</span>
              </th>
              {orderedClassIds.map((classId) => (
                <th key={classId} scope="col">
                  {classId}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {matrix.map((row, rowIndex) => (
              <tr key={orderedClassIds[rowIndex]}>
                <th scope="row">{orderedClassIds[rowIndex]}</th>
                {row.map((value, columnIndex) => (
                  <td key={orderedClassIds[columnIndex]} style={cellStyle(value)}>
                    {formatPercent(value)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="confusion-matrix__legend">Rows are actual classes; columns are predicted classes.</p>
    </Card>
  );
}
