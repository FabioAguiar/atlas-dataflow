import { Link } from "react-router-dom";

export type PredictViewItem = {
  view_id: string;
  dataset_slug: string;
  display: { title?: string; summary?: string };
  intent: { prediction_goal?: string; audience?: string; usage_notes?: string };
  release_mode: string | null;
};

type PredictViewListProps = {
  views: PredictViewItem[];
  slug: string;
};

export default function PredictViewList({ views, slug }: PredictViewListProps) {
  if (views.length === 0) {
    return (
      <section aria-label="Predict views">
        <p>No predict views are available for this dataset.</p>
      </section>
    );
  }

  return (
    <section aria-label="Predict views">
      <h2>Predict Views</h2>
      <ul className="predict-view-list">
        {views.map((view) => (
          <li key={view.view_id}>
            <Link to={`/dataset/${slug}/view/${view.view_id}`}>
              <strong>{view.display.title ?? view.view_id}</strong>
            </Link>
            {view.display.summary && <p>{view.display.summary}</p>}
          </li>
        ))}
      </ul>
    </section>
  );
}
