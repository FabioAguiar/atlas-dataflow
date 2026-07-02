import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { Tabs, type TabItem } from "../../components/ui";

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

type DatasetState =
  | { status: "loading" }
  | { status: "ready"; datasets: DatasetListing[] }
  | { status: "error" };

const adminTabs: TabItem[] = [
  { id: "public-content", label: "Public Content" },
  { id: "metadata-card", label: "Metadata & Card" },
  { id: "theme-preset", label: "Theme Preset" },
  { id: "inference-form", label: "Inference Form" },
  { id: "result-card", label: "Result Card" },
  { id: "publishing", label: "Publishing" },
  { id: "live-preview", label: "Live Preview" },
];

const pageStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-5)",
};

const headerStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-4)",
};

const headerControlsStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-3)",
  gridTemplateColumns: "minmax(16rem, 1fr) auto",
  alignItems: "end",
};

const fieldStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-2)",
};

const labelStyle: CSSProperties = {
  color: "var(--atlas-color-text-subtle)",
  fontSize: "var(--atlas-text-xs)",
  fontWeight: 800,
  textTransform: "uppercase",
};

const selectStyle: CSSProperties = {
  width: "100%",
  minHeight: "2.75rem",
  border: "1px solid var(--atlas-color-border-strong)",
  borderRadius: "var(--atlas-radius-md)",
  padding: "0 var(--atlas-space-3)",
  color: "var(--atlas-color-text)",
  font: "inherit",
  fontWeight: 700,
  background: "var(--atlas-color-surface)",
};

const panelStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-4)",
  border: "1px solid var(--atlas-color-border)",
  borderRadius: "var(--atlas-radius-md)",
  padding: "var(--atlas-space-5)",
  background: "var(--atlas-color-surface)",
  boxShadow: "var(--atlas-shadow-sm)",
};

const tabPanelStyle: CSSProperties = {
  ...panelStyle,
  minHeight: "24rem",
  alignContent: "start",
};

const sectionGridStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-4)",
  gridTemplateColumns: "repeat(auto-fit, minmax(14rem, 1fr))",
};

const readOnlyFieldStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-1)",
  border: "1px solid var(--atlas-color-border)",
  borderRadius: "var(--atlas-radius-md)",
  padding: "var(--atlas-space-3)",
  background: "var(--atlas-color-surface-muted)",
};

const readOnlyValueStyle: CSSProperties = {
  margin: 0,
  color: "var(--atlas-color-text)",
  fontWeight: 700,
};

const mutedTextStyle: CSSProperties = {
  margin: 0,
  color: "var(--atlas-color-text-muted)",
};

const disabledButtonStyle: CSSProperties = {
  minHeight: "2.5rem",
  border: "1px solid var(--atlas-color-border-strong)",
  borderRadius: "var(--atlas-radius-md)",
  padding: "0 var(--atlas-space-4)",
  color: "var(--atlas-color-text-subtle)",
  font: "inherit",
  fontWeight: 700,
  background: "var(--atlas-color-surface-muted)",
  cursor: "not-allowed",
};

const previewCardStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-3)",
  border: "1px solid var(--atlas-color-border-strong)",
  borderRadius: "var(--atlas-radius-md)",
  padding: "var(--atlas-space-4)",
  background: "var(--atlas-color-canvas)",
};

const tagListStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: "var(--atlas-space-2)",
  margin: 0,
  padding: 0,
  listStyle: "none",
};

const tagStyle: CSSProperties = {
  border: "1px solid var(--atlas-color-border)",
  borderRadius: "999px",
  padding: "0.25rem 0.65rem",
  color: "var(--atlas-color-text-muted)",
  fontSize: "var(--atlas-text-xs)",
  fontWeight: 800,
  background: "var(--atlas-color-surface)",
};

const previewModeButtonStyle: CSSProperties = {
  minHeight: "2.25rem",
  border: "1px solid var(--atlas-color-border-strong)",
  borderRadius: "var(--atlas-radius-md)",
  padding: "0 var(--atlas-space-3)",
  color: "var(--atlas-color-text)",
  font: "inherit",
  fontSize: "var(--atlas-text-sm)",
  fontWeight: 800,
  background: "var(--atlas-color-surface)",
};

function getDatasetLabel(dataset?: DatasetListing) {
  if (!dataset) {
    return "No dataset selected";
  }

  return dataset.title || dataset.dataset_slug;
}

function ReadOnlyField({ label, value }: { label: string; value: string }) {
  return (
    <div style={readOnlyFieldStyle}>
      <span style={labelStyle}>{label}</span>
      <p style={readOnlyValueStyle}>{value || "Not provided"}</p>
    </div>
  );
}

function DatasetTags({ tags }: { tags: string[] }) {
  if (tags.length === 0) {
    return <p style={mutedTextStyle}>No tags available.</p>;
  }

  return (
    <ul style={tagListStyle}>
      {tags.map((tag) => (
        <li key={tag} style={tagStyle}>
          {tag}
        </li>
      ))}
    </ul>
  );
}

function DatasetPreview({ dataset, mode }: { dataset?: DatasetListing; mode: "card" | "detail" }) {
  return (
    <article aria-label={`${mode === "detail" ? "Detail" : "Card"} preview`} style={previewCardStyle}>
      <span className="atlas-status-pill">
        {dataset?.visibility || "visibility unavailable"}
      </span>
      <h3 style={{ margin: 0 }}>{getDatasetLabel(dataset)}</h3>
      <p style={mutedTextStyle}>{dataset?.summary || "Dataset metadata will appear after the listing loads."}</p>
      {mode === "detail" && (
        <div style={sectionGridStyle}>
          <ReadOnlyField label="Slug" value={dataset?.dataset_slug || ""} />
          <ReadOnlyField label="Domain" value={dataset?.domain || ""} />
        </div>
      )}
      <DatasetTags tags={dataset?.tags ?? []} />
    </article>
  );
}

function PublicContentTab({ dataset }: { dataset?: DatasetListing }) {
  return (
    <>
      <div>
        <h2 style={{ marginTop: 0 }}>Public Content</h2>
        <p style={mutedTextStyle}>Public profile fields are represented from the current dataset listing.</p>
      </div>
      <div style={sectionGridStyle}>
        <ReadOnlyField label="Display title" value={dataset?.title || dataset?.dataset_slug || ""} />
        <ReadOnlyField label="Subtitle" value={dataset?.domain || ""} />
        <ReadOnlyField label="Canonical slug" value={dataset?.dataset_slug || ""} />
        <ReadOnlyField label="Visibility" value={dataset?.visibility || ""} />
      </div>
      <ReadOnlyField label="Problem summary" value={dataset?.summary || ""} />
    </>
  );
}

function MetadataCardTab({ dataset }: { dataset?: DatasetListing }) {
  return (
    <>
      <div>
        <h2 style={{ marginTop: 0 }}>Metadata & Card</h2>
        <p style={mutedTextStyle}>Card metadata is read-only in this shell.</p>
      </div>
      <div style={sectionGridStyle}>
        <ReadOnlyField label="Card title" value={getDatasetLabel(dataset)} />
        <ReadOnlyField label="Domain" value={dataset?.domain || ""} />
        <ReadOnlyField label="Icon preset" value="Dataset" />
        <ReadOnlyField label="Primary metric" value="Configured later" />
      </div>
      <DatasetPreview dataset={dataset} mode="card" />
    </>
  );
}

function ThemePresetTab() {
  return (
    <>
      <div>
        <h2 style={{ marginTop: 0 }}>Theme Preset</h2>
        <p style={mutedTextStyle}>Theme presets are visible here without creating arbitrary color settings.</p>
      </div>
      <div style={sectionGridStyle}>
        {["Atlas Green", "Signal Blue", "Graphite", "High Contrast"].map((preset, index) => (
          <div key={preset} style={readOnlyFieldStyle}>
            <span style={labelStyle}>{index === 0 ? "Selected preset" : "Available preset"}</span>
            <p style={readOnlyValueStyle}>{preset}</p>
          </div>
        ))}
      </div>
    </>
  );
}

function InferenceFormTab({ dataset }: { dataset?: DatasetListing }) {
  return (
    <>
      <div>
        <h2 style={{ marginTop: 0 }}>Inference Form</h2>
        <p style={mutedTextStyle}>The form builder shell is scoped to layout and dataset context only.</p>
      </div>
      <div style={sectionGridStyle}>
        <ReadOnlyField label="Dataset context" value={getDatasetLabel(dataset)} />
        <ReadOnlyField label="Form groups" value="Draft layout unavailable" />
        <ReadOnlyField label="Field bank" value="Runtime contract fields unavailable" />
        <ReadOnlyField label="Validation mode" value="Not active" />
      </div>
    </>
  );
}

function ResultCardTab({ dataset }: { dataset?: DatasetListing }) {
  return (
    <>
      <div>
        <h2 style={{ marginTop: 0 }}>Result Card</h2>
        <p style={mutedTextStyle}>Result presentation controls remain disabled until later profile editing work.</p>
      </div>
      <div style={sectionGridStyle}>
        <ReadOnlyField label="Dataset" value={getDatasetLabel(dataset)} />
        <ReadOnlyField label="Primary result label" value="Prediction result" />
        <ReadOnlyField label="Confidence display" value="Preset" />
        <ReadOnlyField label="Explanation block" value="Not configured" />
      </div>
    </>
  );
}

function PublishingTab({ dataset }: { dataset?: DatasetListing }) {
  return (
    <>
      <div>
        <h2 style={{ marginTop: 0 }}>Publishing</h2>
        <p style={mutedTextStyle}>Publishing controls are present but disabled for M35-01.</p>
      </div>
      <div style={sectionGridStyle}>
        <ReadOnlyField label="Selected dataset" value={getDatasetLabel(dataset)} />
        <ReadOnlyField label="Profile draft" value="Read-only" />
        <ReadOnlyField label="Public visibility" value="No semantic change" />
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--atlas-space-2)" }}>
        <button disabled style={disabledButtonStyle} type="button">
          Save draft disabled
        </button>
        <button disabled style={disabledButtonStyle} type="button">
          Preview disabled
        </button>
        <button disabled style={disabledButtonStyle} type="button">
          Publish disabled
        </button>
      </div>
    </>
  );
}

function LivePreviewTab({ dataset }: { dataset?: DatasetListing }) {
  const [previewMode, setPreviewMode] = useState<"detail" | "card">("detail");

  return (
    <>
      <div>
        <h2 style={{ marginTop: 0 }}>Live Preview</h2>
        <p style={mutedTextStyle}>Preview uses the selected dataset listing without saving profile changes.</p>
      </div>
      <div aria-label="Preview mode" style={{ display: "flex", flexWrap: "wrap", gap: "var(--atlas-space-2)" }}>
        {(["detail", "card"] as const).map((mode) => (
          <button
            key={mode}
            onClick={() => setPreviewMode(mode)}
            style={{
              ...previewModeButtonStyle,
              background:
                previewMode === mode ? "var(--atlas-color-accent-muted)" : "var(--atlas-color-surface)",
              color: previewMode === mode ? "var(--atlas-color-accent-strong)" : "var(--atlas-color-text)",
            }}
            type="button"
          >
            {mode === "detail" ? "Dataset detail" : "Home card"}
          </button>
        ))}
      </div>
      <DatasetPreview dataset={dataset} mode={previewMode} />
    </>
  );
}

function renderSelectedTab(selectedTab: string, dataset?: DatasetListing) {
  switch (selectedTab) {
    case "metadata-card":
      return <MetadataCardTab dataset={dataset} />;
    case "theme-preset":
      return <ThemePresetTab />;
    case "inference-form":
      return <InferenceFormTab dataset={dataset} />;
    case "result-card":
      return <ResultCardTab dataset={dataset} />;
    case "publishing":
      return <PublishingTab dataset={dataset} />;
    case "live-preview":
      return <LivePreviewTab dataset={dataset} />;
    case "public-content":
    default:
      return <PublicContentTab dataset={dataset} />;
  }
}

export default function DatasetAdminPage() {
  const [state, setState] = useState<DatasetState>({ status: "loading" });
  const [selectedSlug, setSelectedSlug] = useState("");
  const [selectedTab, setSelectedTab] = useState(adminTabs[0].id);

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
        if (!data) {
          return;
        }

        if (!Array.isArray(data.datasets)) {
          setState({ status: "error" });
          return;
        }

        setState({ status: "ready", datasets: data.datasets });
        setSelectedSlug((current) => current || data.datasets[0]?.dataset_slug || "");
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") {
          setState({ status: "error" });
        }
      });

    return () => controller.abort();
  }, []);

  const datasets = state.status === "ready" ? state.datasets : [];
  const selectedDataset = useMemo(
    () => datasets.find((dataset) => dataset.dataset_slug === selectedSlug) ?? datasets[0],
    [datasets, selectedSlug],
  );

  return (
    <section aria-labelledby="dataset-admin-title" style={pageStyle}>
      <header style={headerStyle}>
        <div>
          <p className="eyebrow">Dataset Admin</p>
          <h1 id="dataset-admin-title">Dataset administration</h1>
          <p className="summary">
            Private workspace for composing public dataset profile surfaces from the current dataset registry state.
          </p>
        </div>

        <div style={headerControlsStyle}>
          <label style={fieldStyle}>
            <span style={labelStyle}>Dataset</span>
            <select
              disabled={state.status !== "ready" || datasets.length === 0}
              onChange={(event) => setSelectedSlug(event.target.value)}
              style={selectStyle}
              value={selectedDataset?.dataset_slug ?? ""}
            >
              {state.status === "loading" && <option value="">Loading datasets...</option>}
              {state.status === "error" && <option value="">Datasets unavailable</option>}
              {state.status === "ready" && datasets.length === 0 && <option value="">No datasets available</option>}
              {datasets.map((dataset) => (
                <option key={dataset.dataset_slug} value={dataset.dataset_slug}>
                  {dataset.title || dataset.dataset_slug}
                </option>
              ))}
            </select>
          </label>

          <span className="atlas-status-pill atlas-status-pill--warning">Read-only shell</span>
        </div>
      </header>

      {state.status === "error" && (
        <article role="status" style={panelStyle}>
          <strong>Dataset listing unavailable</strong>
          <p style={mutedTextStyle}>The admin shell remains available, but dataset-specific fields cannot be loaded.</p>
        </article>
      )}

      <section aria-label="Dataset profile workspace" style={panelStyle}>
        <Tabs ariaLabel="Dataset admin tabs" items={adminTabs} onSelect={setSelectedTab} selectedId={selectedTab} />
        <div
          aria-label={`${adminTabs.find((tab) => tab.id === selectedTab)?.label ?? "Selected"} tab panel`}
          role="tabpanel"
          style={tabPanelStyle}
        >
          {renderSelectedTab(selectedTab, selectedDataset)}
        </div>
      </section>
    </section>
  );
}
