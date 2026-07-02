import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Card, EmptyState, ErrorState, StatusPill } from "../components/ui";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "";

type DatasetListing = {
  dataset_slug: string;
  title: string;
  summary: string;
  domain: string;
  visibility: string;
  tags: string[];
};

type DatasetListingResponse = {
  datasets: DatasetListing[];
};

type HomeState =
  | { status: "loading" }
  | { status: "ready"; datasets: DatasetListing[] }
  | { status: "error" };

export default function HomePage() {
  const [state, setState] = useState<HomeState>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();

    fetch(`${apiBaseUrl}/datasets`, { signal: controller.signal })
      .then((res) => {
        if (!res.ok) {
          setState({ status: "error" });
          return;
        }
        return res.json() as Promise<DatasetListingResponse>;
      })
      .then((data) => {
        if (data && Array.isArray(data.datasets)) {
          setState({ status: "ready", datasets: data.datasets });
          return;
        }
        if (data) {
          setState({ status: "error" });
        }
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") {
          setState({ status: "error" });
        }
      });

    return () => controller.abort();
  }, []);

  return (
    <>
      <section className="intro" aria-labelledby="page-title">
        <p className="eyebrow">Atlas DataFlow</p>
        <h1 id="page-title">Datasets</h1>
      </section>

      {state.status === "loading" && (
        <Card aria-label="Loading datasets">
          <p>Loading datasets...</p>
        </Card>
      )}

      {state.status === "error" && (
        <ErrorState
          title="Datasets unavailable"
          message="Please check that the API is running."
        />
      )}

      {state.status === "ready" && (
        <section className="dataset-listing" aria-label="Available datasets">
          {state.datasets.length === 0 ? (
            <EmptyState title="No datasets available" message="Published datasets will appear here." />
          ) : (
            <ul>
              {state.datasets.map((ds) => (
                <li key={ds.dataset_slug}>
                  <Card>
                    <div>
                      <Link to={`/dataset/${ds.dataset_slug}`}>
                        {ds.title || ds.dataset_slug}
                      </Link>
                      {ds.summary && <p>{ds.summary}</p>}
                    </div>
                    <div className="dataset-listing__meta">
                      <StatusPill tone="info">{ds.visibility}</StatusPill>
                      {ds.domain && <Badge>{ds.domain}</Badge>}
                    </div>
                  </Card>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </>
  );
}
