import "./App.css";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "";

function App() {
  const apiConfigStatus = apiBaseUrl.trim().length > 0 ? "Configured" : "Not configured";

  return (
    <main className="app-shell">
      <section className="intro" aria-labelledby="page-title">
        <p className="eyebrow">Atlas DataFlow</p>
        <h1 id="page-title">Public web experience</h1>
        <p className="summary">
          Minimal public web bootstrap for the Atlas DataFlow runtime surface.
        </p>
      </section>

      <section className="status-panel" aria-label="Bootstrap status">
        <div>
          <span className="status-label">Web app</span>
          <strong>Loaded</strong>
        </div>
        <div>
          <span className="status-label">API base URL</span>
          <strong>{apiConfigStatus}</strong>
        </div>
      </section>
    </main>
  );
}

export default App;
