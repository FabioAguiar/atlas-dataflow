import { Routes, Route } from "react-router-dom";
import "./App.css";
import AdminShell from "./layouts/AdminShell";
import PublicShell from "./layouts/PublicShell";
import DashboardPage from "./pages/admin/DashboardPage";
import DatasetAdminPage from "./pages/admin/DatasetAdminPage";
import HelpPage from "./pages/admin/HelpPage";
import SettingsPage from "./pages/admin/SettingsPage";
import DatasetPage from "./pages/DatasetPage";
import DatasetViewPage from "./pages/DatasetViewPage";
import HomePage from "./pages/HomePage";

export default function App() {
  return (
    <Routes>
      <Route path="/admin" element={<AdminShell />}>
        <Route index element={<DashboardPage />} />
        <Route path="dataset-admin" element={<DatasetAdminPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="help" element={<HelpPage />} />
      </Route>
      <Route
        path="/dataset/:slug/view/:viewId"
        element={
          <PublicShell>
            <DatasetViewPage />
          </PublicShell>
        }
      />
      <Route
        path="/dataset/:slug"
        element={
          <PublicShell>
            <DatasetPage />
          </PublicShell>
        }
      />
      <Route
        path="/"
        element={
          <PublicShell>
            <HomePage />
          </PublicShell>
        }
      />
    </Routes>
  );
}
