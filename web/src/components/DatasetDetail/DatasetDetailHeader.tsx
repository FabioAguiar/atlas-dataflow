import { Link } from "react-router-dom";
import { Badge } from "../ui";

export type DatasetDetailMetadataItem = {
  label: "Source" | "Instances" | "Features" | "Target" | "Release";
  value: string | null;
  hint?: string;
};

type DatasetDetailHeaderProps = {
  datasetTitle: string;
  subtitle?: string;
  analysisType?: string;
  metadata: DatasetDetailMetadataItem[];
};

export default function DatasetDetailHeader({
  datasetTitle,
  subtitle,
  analysisType,
  metadata,
}: DatasetDetailHeaderProps) {
  return (
    <header className="dataset-detail-header">
      <nav className="dataset-detail-header__breadcrumb" aria-label="Breadcrumb">
        <Link to="/">Datasets</Link>
        <span aria-hidden="true"> › </span>
        <span>{datasetTitle}</span>
      </nav>

      <div className="dataset-detail-header__heading">
        <h1>{datasetTitle}</h1>
        {analysisType && <Badge>{analysisType}</Badge>}
      </div>

      {subtitle && <p className="dataset-detail-header__subtitle">{subtitle}</p>}

      <dl className="dataset-detail-header__metadata" aria-label="Dataset metadata summary">
        {metadata.map((item) => (
          <div key={item.label} className="dataset-detail-header__metadata-item">
            <dt>{item.label}</dt>
            <dd>
              {item.value ?? (
                <span className="dataset-detail-header__metadata-pending">Pending</span>
              )}
            </dd>
            {item.hint && <p className="dataset-detail-header__metadata-hint">{item.hint}</p>}
          </div>
        ))}
      </dl>
    </header>
  );
}
