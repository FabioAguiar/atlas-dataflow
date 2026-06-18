import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import DatasetHeader from "../components/DatasetHeader";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "";

type DatasetMetadata = {
  dataset_slug: string;
  title: string;
  summary: string;
  domain: string;
  visibility: string;
  tags: string[];
};

type PageState =
  | { status: "loading" }
  | { status: "ready"; data: DatasetMetadata }
  | { status: "not_found" }
  | { status: "unavailable" };

export default function DatasetPage() {
  const { slug } = useParams<{ slug: string }>();
  const [state, setState] = useState<PageState>({ status: "loading" });

  useEffect(() => {
    if (!slug) {
      setState({ status: "not_found" });
      return;
    }

    const controller = new AbortController();

    fetch(`${apiBaseUrl}/datasets/${encodeURIComponent(slug)}`, {
      signal: controller.signal,
    })
      .then((res) => {
        if (res.status === 404) {
          setState({ status: "not_found" });
          return null;
        }
        if (!res.ok) {
          setState({ status: "unavailable" });
          return null;
        }
        return res.json() as Promise<DatasetMetadata>;
      })
      .then((data) => {
        if (data) {
          setState({ status: "ready", data });
        }
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") {
          setState({ status: "unavailable" });
        }
      });

    return () => controller.abort();
  }, [slug]);

  if (state.status === "loading") {
    return (
      <main className="app-shell">
        <p>Loading…</p>
      </main>
    );
  }

  if (state.status === "not_found") {
    return (
      <main className="app-shell">
        <p>Dataset not found.</p>
      </main>
    );
  }

  if (state.status === "unavailable") {
    return (
      <main className="app-shell">
        <p>Dataset information is currently unavailable. Please try again later.</p>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <DatasetHeader title={state.data.title} summary={state.data.summary} />
    </main>
  );
}
