import { Link } from "react-router-dom";
import DatasetIdentityBadges from "../DatasetIdentityBadges/DatasetIdentityBadges";

export type DatasetDetailMetadataItem = {
  label: "Source" | "Instances" | "Features" | "Target" | "Release";
  value: string | null;
  hint?: string;
  href?: string;
};

type DatasetDetailHeaderProps = {
  datasetTitle: string;
  subtitle?: string;
  analysisType?: string;
  performanceFocusId?: string | null;
  modelDisplayName?: string | null;
  metadata: DatasetDetailMetadataItem[];
};

export default function DatasetDetailHeader({
  datasetTitle,
  subtitle,
  analysisType,
  performanceFocusId,
  modelDisplayName,
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
        <DatasetIdentityBadges
          problemLabel={analysisType}
          performanceFocusId={performanceFocusId}
          modelDisplayName={modelDisplayName}
          groupClassName="dataset-detail-header__badges"
        />
      </div>

      {subtitle && <p className="dataset-detail-header__subtitle">{subtitle}</p>}

      <dl className="dataset-detail-header__metadata" aria-label="Dataset metadata summary">
        {metadata.map((item) => (
          <div key={item.label} className="dataset-detail-header__metadata-item">
            <dt>{item.label}</dt>
            <dd>
              {item.value && item.href ? (
                <a href={item.href} target="_blank" rel="noreferrer noopener">
                  {item.value}
                </a>
              ) : item.value ?? (
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
