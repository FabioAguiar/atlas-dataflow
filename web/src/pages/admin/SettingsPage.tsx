import { useState, type CSSProperties, type FormEvent } from "react";

import { useAdminSettings } from "../../layouts/AdminSettingsContext";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "";

type SettingsError = {
  code?: string;
  field?: string | null;
  message?: string;
};

type SettingsState =
  | { status: "idle"; message: string }
  | { status: "loading" }
  | { status: "ready" }
  | { status: "saved" }
  | { status: "invalid"; errors: SettingsError[] }
  | { status: "unavailable"; message: string };

const pageStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-5)",
};

const panelStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-3)",
  border: "1px solid var(--atlas-color-border)",
  borderRadius: "var(--atlas-radius-md)",
  padding: "var(--atlas-space-5)",
  background: "var(--atlas-color-surface)",
  boxShadow: "var(--atlas-shadow-sm)",
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

const inputStyle: CSSProperties = {
  width: "100%",
  minHeight: "2.75rem",
  border: "1px solid var(--atlas-color-border-strong)",
  borderRadius: "var(--atlas-radius-md)",
  padding: "0 var(--atlas-space-3)",
  color: "var(--atlas-color-text)",
  font: "inherit",
  background: "var(--atlas-color-surface)",
};

const buttonRowStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: "var(--atlas-space-2)",
  alignItems: "center",
};

const actionButtonStyle: CSSProperties = {
  minHeight: "2.5rem",
  border: "1px solid var(--atlas-color-accent)",
  borderRadius: "var(--atlas-radius-md)",
  padding: "0 var(--atlas-space-4)",
  color: "var(--atlas-color-surface)",
  font: "inherit",
  fontWeight: 800,
  background: "var(--atlas-color-accent)",
  cursor: "pointer",
};

const secondaryButtonStyle: CSSProperties = {
  ...actionButtonStyle,
  borderColor: "var(--atlas-color-border-strong)",
  color: "var(--atlas-color-accent-strong)",
  background: "var(--atlas-color-surface)",
};

const disabledButtonStyle: CSSProperties = {
  ...secondaryButtonStyle,
  color: "var(--atlas-color-text-subtle)",
  background: "var(--atlas-color-surface-muted)",
  cursor: "not-allowed",
};

const mutedTextStyle: CSSProperties = {
  margin: 0,
  color: "var(--atlas-color-text-muted)",
};

const alertStyle: CSSProperties = {
  display: "grid",
  gap: "var(--atlas-space-2)",
  border: "1px solid var(--atlas-color-warning)",
  borderRadius: "var(--atlas-radius-md)",
  padding: "var(--atlas-space-4)",
  color: "var(--atlas-color-text)",
  background: "var(--atlas-color-warning-muted)",
};

function SettingsStatusPanel({ state }: { state: SettingsState }) {
  if (state.status === "ready") {
    return (
      <article style={{ ...panelStyle, padding: "var(--atlas-space-3)" }}>
        <span className="atlas-status-pill atlas-status-pill--info">Loaded</span>
        <p style={mutedTextStyle}>Current display name loaded from the private/admin settings endpoint.</p>
      </article>
    );
  }
  if (state.status === "saved") {
    return (
      <article className="atlas-status-pill atlas-status-pill--success" role="status">
        Display name saved.
      </article>
    );
  }
  if (state.status === "invalid") {
    return (
      <article role="status" style={alertStyle}>
        <strong>Admin settings rejected by backend validation</strong>
        <ul style={{ margin: 0, paddingLeft: "var(--atlas-space-5)" }}>
          {state.errors.map((error, index) => (
            <li key={`${error.code ?? "error"}-${error.field ?? "field"}-${index}`}>
              {[error.field, error.code, error.message].filter(Boolean).join(" - ")}
            </li>
          ))}
        </ul>
      </article>
    );
  }
  if (state.status === "unavailable") {
    return (
      <article role="status" style={alertStyle}>
        <strong>Admin settings unavailable</strong>
        <p style={mutedTextStyle}>{state.message}</p>
      </article>
    );
  }
  if (state.status === "loading") {
    return <p style={mutedTextStyle}>Loading admin settings...</p>;
  }
  return <p style={mutedTextStyle}>{state.message}</p>;
}

export default function SettingsPage() {
  const { setDisplayName: setSharedDisplayName } = useAdminSettings();
  const [adminToken, setAdminToken] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [state, setState] = useState<SettingsState>({
    status: "idle",
    message: "Enter the operator token and load the current display name.",
  });

  function loadSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const token = adminToken.trim();
    if (!token) {
      setState({ status: "unavailable", message: "Enter the operator token to load Admin Settings." });
      return;
    }

    setState({ status: "loading" });
    fetch(`${apiBaseUrl}/admin/settings`, {
      headers: { "X-Admin-Token": token },
    })
      .then((response) => {
        if (!response.ok) {
          setState({ status: "unavailable", message: `Admin Settings unavailable (${response.status}).` });
          return null;
        }
        return response.json() as Promise<{ settings?: { display_name?: string } }>;
      })
      .then((data) => {
        if (!data) {
          return;
        }
        const loadedDisplayName = data.settings?.display_name ?? "";
        setDisplayName(loadedDisplayName);
        if (loadedDisplayName) {
          setSharedDisplayName(loadedDisplayName);
        }
        setState({ status: "ready" });
      })
      .catch(() => {
        setState({ status: "unavailable", message: "Admin Settings could not be loaded. Check API reachability." });
      });
  }

  function saveSettings() {
    const token = adminToken.trim();
    if (!token) {
      setState({ status: "unavailable", message: "Enter the operator token before saving." });
      return;
    }

    setState({ status: "loading" });
    fetch(`${apiBaseUrl}/admin/settings`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        "X-Admin-Token": token,
      },
      body: JSON.stringify({ display_name: displayName }),
    })
      .then((response) =>
        response.json().then((body: { settings?: { display_name?: string }; errors?: SettingsError[] }) => ({
          ok: response.ok,
          body,
        })),
      )
      .then((result) => {
        if (!result.ok) {
          setState({
            status: "invalid",
            errors: result.body.errors ?? [{ message: "Admin settings failed validation." }],
          });
          return;
        }
        const savedDisplayName = result.body.settings?.display_name ?? displayName;
        setDisplayName(savedDisplayName);
        if (savedDisplayName) {
          setSharedDisplayName(savedDisplayName);
        }
        setState({ status: "saved" });
      })
      .catch(() => {
        setState({ status: "unavailable", message: "Admin Settings could not be saved. Check API reachability." });
      });
  }

  const isBusy = state.status === "loading";

  return (
    <section aria-labelledby="admin-settings-title" style={pageStyle}>
      <div>
        <p className="eyebrow">Settings</p>
        <h1 id="admin-settings-title">Admin settings</h1>
        <p className="summary">
          Edit only the displayed admin user name. Account, credential, deployment, model, secret, role, team, and
          organization settings are not available here.
        </p>
      </div>

      <article style={panelStyle}>
        <form onSubmit={loadSettings} style={fieldStyle}>
          <span style={labelStyle}>Operator token</span>
          <div style={buttonRowStyle}>
            <input
              aria-label="Operator token"
              onChange={(event) => setAdminToken(event.target.value)}
              style={{ ...inputStyle, minWidth: "min(16rem, 100%)" }}
              type="password"
              value={adminToken}
            />
            <button disabled={isBusy} style={isBusy ? disabledButtonStyle : secondaryButtonStyle} type="submit">
              Load settings
            </button>
          </div>
        </form>

        <SettingsStatusPanel state={state} />

        <label style={fieldStyle}>
          <span style={labelStyle}>Display name</span>
          <input
            aria-label="Display name"
            onChange={(event) => setDisplayName(event.target.value)}
            style={inputStyle}
            type="text"
            value={displayName}
          />
        </label>

        <div style={buttonRowStyle}>
          <button
            disabled={isBusy}
            onClick={saveSettings}
            style={isBusy ? disabledButtonStyle : actionButtonStyle}
            type="button"
          >
            Save display name
          </button>
          <span style={mutedTextStyle}>Saves only the display name through the controlled admin settings boundary.</span>
        </div>
      </article>
    </section>
  );
}
