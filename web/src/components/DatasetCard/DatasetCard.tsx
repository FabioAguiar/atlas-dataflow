import type { ReactElement } from "react";
import { Link } from "react-router-dom";
import { Badge, Card } from "../ui";
import { getDatasetIcon, getProblemTypeLabel, type DatasetIconName } from "../../lib/datasetPresentation";

type DatasetCardProps = {
  slug: string;
  title: string;
  summary: string;
  domain?: string;
  tags?: string[];
  problemType?: string;
};

function TelecomIcon() {
  return (
    <svg viewBox="0 0 24 24">
      <path d="M8 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm8 0a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM3.5 19a4.5 4.5 0 0 1 9 0m-1.5-5.5A5.5 5.5 0 0 1 20.5 19" />
    </svg>
  );
}

function BankIcon() {
  return (
    <svg viewBox="0 0 24 24">
      <path d="M4 10h16L12 5 4 10Zm2 0v8m4-8v8m4-8v8m4-8v8M4 19h16" />
    </svg>
  );
}

function GenericDatasetIcon() {
  return (
    <svg viewBox="0 0 24 24">
      <path d="M4 19h2V9H4v10Zm7 0h2V5h-2v14Zm7 0h2v-7h-2v7Z" />
    </svg>
  );
}

const DATASET_ICONS: Record<DatasetIconName, ReactElement> = {
  telecom: <TelecomIcon />,
  bank: <BankIcon />,
  generic: <GenericDatasetIcon />,
};

export default function DatasetCard({ slug, title, summary, domain, tags = [], problemType }: DatasetCardProps) {
  const icon = getDatasetIcon(domain, tags);
  const analysisLabel = getProblemTypeLabel(problemType);

  return (
    <Card className="dataset-card">
      <Link
        to={`/dataset/${slug}`}
        className="dataset-card__link-overlay"
        aria-label={`Explorar dataset ${title}`}
      />
      <span className="dataset-card__icon" aria-hidden="true">
        {DATASET_ICONS[icon]}
      </span>
      <div className="dataset-card__body">
        <h3 className="dataset-card__title">{title}</h3>
        <Badge className="dataset-card__badge">{analysisLabel}</Badge>
        {summary && <p className="dataset-card__description">{summary}</p>}
      </div>
      <span className="dataset-card__action" aria-hidden="true">
        Explorar dataset <span aria-hidden="true">→</span>
      </span>
    </Card>
  );
}
