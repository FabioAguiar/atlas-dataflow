import { Link } from "react-router-dom";

// Project Spec S0117: the three bounded public Dataset Detail access
// states DatasetPage.tsx/DatasetViewPage.tsx render when their primary
// route request is not "ready". "maintenance" and "not_found" both come
// from the public error envelope's error_code; "unavailable" covers every
// other non-success response (registry/release failures, unexpected
// errors, malformed error bodies, network failures) -- classification
// must never rely on HTTP status alone, since multiple public routes use
// 503 for different meanings.
export type DatasetAccessStateKind = "maintenance" | "not_found" | "unavailable";

type Props = {
  kind: DatasetAccessStateKind;
};

type Copy = {
  heading: string;
  body: string;
  showBackToDatasets: boolean;
};

const COPY: Record<DatasetAccessStateKind, Copy> = {
  maintenance: {
    heading: "Dataset page under maintenance",
    body: "This dataset page is temporarily unavailable. Please try again later.",
    showBackToDatasets: true,
  },
  not_found: {
    heading: "Dataset not found",
    body: "The dataset or link you tried to access does not exist.",
    showBackToDatasets: true,
  },
  unavailable: {
    heading: "Dataset information is currently unavailable",
    body: "Please try again later.",
    showBackToDatasets: false,
  },
};

// This component never fetches data and never receives or renders any
// private backend detail (visibility state, review state, active release,
// or a blocker list) -- only the generic, dataset-agnostic copy above.
export default function DatasetAccessState({ kind }: Props) {
  const copy = COPY[kind];

  return (
    <div className="dataset-access-state" data-access-state={kind}>
      <div className="dataset-access-state__panel">
        <h1 className="dataset-access-state__heading">{copy.heading}</h1>
        <p className="dataset-access-state__body">{copy.body}</p>
        {copy.showBackToDatasets && (
          <Link className="dataset-access-state__action" to="/">
            Back to datasets
          </Link>
        )}
      </div>
    </div>
  );
}

// Shared classifier for the public error envelope
// ({ error_type, error_code, message }) both public route pages parse from
// their primary request's non-success response body. A malformed/unparsable
// body (or any error_code other than the two named below) always becomes
// "unavailable".
export function classifyDatasetAccessError(body: unknown): DatasetAccessStateKind {
  const errorCode =
    body && typeof body === "object" && !Array.isArray(body)
      ? (body as Record<string, unknown>).error_code
      : null;

  if (errorCode === "DATASET_MAINTENANCE") {
    return "maintenance";
  }
  if (errorCode === "DATASET_NOT_FOUND") {
    return "not_found";
  }
  return "unavailable";
}
