import { useEffect, useState } from "react";
import { Routes, Route, Link } from "react-router-dom";
import "./App.css";
import DatasetPage from "./pages/DatasetPage";
import DatasetViewPage from "./pages/DatasetViewPage";

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

function Home() {
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
      .catch(() => {
        setState({ status: "error" });
      });

    return () => controller.abort();
  }, []);

  return (
    <main className="app-shell">
      <section className="intro" aria-labelledby="page-title">
        <p className="eyebrow">Atlas DataFlow</p>
        <h1 id="page-title">Datasets</h1>
      </section>

      {state.status === "loading" && (
        <section aria-label="Loading datasets">
          <p>Loading datasets…</p>
        </section>
      )}

      {state.status === "error" && (
        <section aria-label="Datasets unavailable">
          <p>Datasets unavailable. Please check that the API is running.</p>
        </section>
      )}

      {state.status === "ready" && (
        <section className="dataset-listing" aria-label="Available datasets">
          <ul>
            {state.datasets.map((ds) => (
              <li key={ds.dataset_slug}>
                <Link to={`/dataset/${ds.dataset_slug}`}>
                  {ds.title || ds.dataset_slug}
                </Link>
                {ds.summary && <p>{ds.summary}</p>}
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/dataset/:slug/view/:viewId" element={<DatasetViewPage />} />
      <Route path="/dataset/:slug" element={<DatasetPage />} />
      <Route path="/" element={<Home />} />
    </Routes>
  );
}
