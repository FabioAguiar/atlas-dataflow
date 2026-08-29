import { lazy, Suspense } from "react";
import { Navigate, Route, Routes, useParams } from "react-router-dom";
import "./App.css";
import PublicShell from "./layouts/PublicShell";
import DatasetPage from "./pages/DatasetPage";
import DatasetViewPage from "./pages/DatasetViewPage";
import HomePage from "./pages/HomePage";

const isAdminEnabled = import.meta.env.VITE_ENABLE_ADMIN === "true";

const AdminShell = isAdminEnabled ? lazy(() => import("./layouts/AdminShell")) : null;
const DashboardPage = isAdminEnabled ? lazy(() => import("./pages/admin/DashboardPage")) : null;
const DatasetAdminPage = isAdminEnabled ? lazy(() => import("./pages/admin/DatasetAdminPage")) : null;
const HelpPage = isAdminEnabled ? lazy(() => import("./pages/admin/HelpPage")) : null;
const SettingsPage = isAdminEnabled ? lazy(() => import("./pages/admin/SettingsPage")) : null;

// Project Spec S0139: the dataset slug is the explicit route-entry identity
// for Dataset Detail. Keying PublicShell on it forces a fresh shell instance
// (and a fresh application of initialNavOpen={false}) whenever the app
// enters this route from elsewhere or the slug changes, without PublicShell
// ever inspecting the route itself. A query-string/hash change or an
// ordinary re-render keeps the same key, so user interaction survives.
function DatasetDetailRoute() {
  const { slug } = useParams<{ slug: string }>();

  return (
    <PublicShell key={`dataset-detail:${slug ?? ""}`} mainMode="full_bleed" initialNavOpen={false}>
      <DatasetPage />
    </PublicShell>
  );
}

function renderAdminRoutes() {
  if (!AdminShell || !DashboardPage || !DatasetAdminPage || !HelpPage || !SettingsPage) {
    return <Route path="/admin/*" element={null} />;
  }

  // Project Spec S0278: Dashboard and Dataset Detail authoring each have one
  // canonical Admin route (/admin/dashboard, /admin/dataset-detail). The bare
  // /admin index and the legacy /admin/dataset-admin path are redirect aliases
  // only -- they never render a second copy of a canonical page. Both Navigate
  // targets resolve within this same AdminShell parent, so the shell is not
  // unmounted mid-redirect and the aliases cannot loop.
  return (
    <Route path="/admin" element={<AdminShell />}>
      <Route index element={<Navigate replace to="/admin/dashboard" />} />
      <Route path="dashboard" element={<DashboardPage />} />
      <Route path="dataset-detail" element={<DatasetAdminPage />} />
      <Route path="dataset-admin" element={<Navigate replace to="/admin/dataset-detail" />} />
      <Route path="settings" element={<SettingsPage />} />
      <Route path="help" element={<HelpPage />} />
    </Route>
  );
}

export default function App() {
  return (
    <Suspense fallback={null}>
      <Routes>
        {renderAdminRoutes()}
        <Route
          path="/dataset/:slug/view/:viewId"
          element={
            <PublicShell>
              <DatasetViewPage />
            </PublicShell>
          }
        />
        <Route path="/dataset/:slug" element={<DatasetDetailRoute />} />
        <Route
          path="/"
          element={
            <PublicShell>
              <HomePage />
            </PublicShell>
          }
        />
      </Routes>
    </Suspense>
  );
}
