import type { ReactElement } from "react";
import { Link } from "react-router-dom";
import { Badge, Card } from "../ui";
import { getDatasetIcon, getProblemTypeLabel, isSafeHomeCardMediaReference, type DatasetIconName } from "../../lib/datasetPresentation";

type DatasetCardProps = {
  slug: string;
  title: string;
  summary: string;
  domain?: string;
  tags?: string[];
  problemType?: string;
  iconOverride?: DatasetIconName;
  mediaRef?: string | null;
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

// DatasetIconName now spans Atlas's full curated icon bank (see
// contracts/dataset-public-profile.schema.json's home_card.icon enum), but
// this component only ships bespoke artwork for the three original icons.
// Deliberately Partial (not an exhaustive Record): any other curated value
// renders the generic icon below until dedicated artwork is added, instead
// of an undefined lookup.
const DATASET_ICONS: Partial<Record<DatasetIconName, ReactElement>> = {
  telecom: <TelecomIcon />,
  bank: <BankIcon />,
  generic: <GenericDatasetIcon />,
  "telecom-users": <TelecomIcon />,
  "bank-building": <BankIcon />,
  "chart-line": <svg viewBox="0 0 24 24"><path d="M4 19V5m0 14h16M7 15l4-4 3 2 5-6" /></svg>,
  heart: <svg viewBox="0 0 24 24"><path d="M12 20S4 15.5 4 9.5A4.5 4.5 0 0 1 12 6a4.5 4.5 0 0 1 8 3.5C20 15.5 12 20 12 20Z" /></svg>,
  "shopping-cart": <svg viewBox="0 0 24 24"><path d="M3 5h2l2 10h10l3-7H6m3 11h.01M17 19h.01" /></svg>,
  airplane: <svg viewBox="0 0 24 24"><path d="m3 13 18-8-7 15-3-6-8-1Zm8 1 4-4" /></svg>,
  shield: <svg viewBox="0 0 24 24"><path d="M12 3 19 6v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6l7-3Z" /></svg>,
  "education-cap": <svg viewBox="0 0 24 24"><path d="m3 9 9-5 9 5-9 5-9-5Zm4 3v5c3 2 7 2 10 0v-5m4-3v6" /></svg>,
  "energy-bolt": <svg viewBox="0 0 24 24"><path d="m13 2-8 12h7l-1 8 8-12h-7l1-8Z" /></svg>,
  "home-house": <svg viewBox="0 0 24 24"><path d="m3 11 9-8 9 8v10h-6v-6H9v6H3V11Z" /></svg>,
  "agro-leaf": <svg viewBox="0 0 24 24"><path d="M20 4C10 4 5 9 5 16c7 1 13-3 15-12ZM4 20c3-6 7-9 12-12" /></svg>,
  "logistics-truck": <svg viewBox="0 0 24 24"><path d="M3 6h11v11H3V6Zm11 4h4l3 3v4h-7v-7ZM7 20a2 2 0 1 0 0-4 2 2 0 0 0 0 4Zm10 0a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z" /></svg>,
  factory: <svg viewBox="0 0 24 24"><path d="M3 21V10l6 3V9l6 4V4h4v17H3Zm4-4h2m3 0h2m3 0h2" /></svg>,
  "weather-cloud": <svg viewBox="0 0 24 24"><path d="M7 18h11a4 4 0 0 0 0-8 6 6 0 0 0-11.5-1.5A4.8 4.8 0 0 0 7 18Z" /></svg>,
  database: <svg viewBox="0 0 24 24"><path d="M4 6c0-2 16-2 16 0s-16 2-16 0Zm0 0v6c0 2 16 2 16 0V6m-16 6v6c0 2 16 2 16 0v-6" /></svg>,
  "money-dollar": <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" /><path d="M15 8.5c-.7-.7-1.7-1-3-1-1.7 0-3 .9-3 2.2 0 3.5 6 1.4 6 4.8 0 1.4-1.3 2.3-3 2.3-1.3 0-2.5-.4-3.3-1.2M12 5.5v13" /></svg>,
  globe: <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3c2.4 2.5 3.5 5.5 3.5 9S14.4 18.5 12 21c-2.4-2.5-3.5-5.5-3.5-9S9.6 5.5 12 3Z" /></svg>,
  flask: <svg viewBox="0 0 24 24"><path d="M9 3h6m-5 0v6l-5.5 9.2A1.8 1.8 0 0 0 6 21h12a1.8 1.8 0 0 0 1.5-2.8L14 9V3M7 15h10" /></svg>,
  "cpu-chip": <svg viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="2" /><rect x="9" y="9" width="6" height="6" /><path d="M9 2v4m6-4v4M9 18v4m6-4v4M2 9h4m-4 6h4m12-6h4m-4 6h4" /></svg>,
};

export function DatasetIcon({ name }: { name: DatasetIconName }) {
  return DATASET_ICONS[name] ?? <GenericDatasetIcon />;
}

export default function DatasetCard({
  slug,
  title,
  summary,
  domain,
  tags = [],
  problemType,
  iconOverride,
  mediaRef,
}: DatasetCardProps) {
  const icon = iconOverride ?? getDatasetIcon(domain, tags);
  const analysisLabel = getProblemTypeLabel(problemType);
  const safeMediaRef = isSafeHomeCardMediaReference(mediaRef) ? mediaRef : null;

  return (
    <Card className="dataset-card">
      <Link
        to={`/dataset/${slug}`}
        className="dataset-card__link-overlay"
        aria-label={`Explore dataset ${title}`}
      />
      {safeMediaRef ? (
        <div className="dataset-card__media" style={{ backgroundImage: `url(${JSON.stringify(safeMediaRef)})` }} data-testid="home-card-media">
          <span aria-hidden="true" className="dataset-card__media-gradient" data-testid="home-card-media-gradient" />
        </div>
      ) : (
        <span className="dataset-card__icon" aria-hidden="true"><DatasetIcon name={icon} /></span>
      )}
      <div className="dataset-card__body">
        <h3 className="dataset-card__title">{title}</h3>
        <Badge className="dataset-card__badge">{analysisLabel}</Badge>
        {summary && <p className="dataset-card__description">{summary}</p>}
      </div>
      <span className="dataset-card__action" aria-hidden="true">
        Explore dataset <span aria-hidden="true">→</span>
      </span>
    </Card>
  );
}
