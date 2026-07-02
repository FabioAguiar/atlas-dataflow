import { Routes, Route } from "react-router-dom";
import "./App.css";
import PublicShell from "./layouts/PublicShell";
import DatasetPage from "./pages/DatasetPage";
import DatasetViewPage from "./pages/DatasetViewPage";
import HomePage from "./pages/HomePage";

export default function App() {
  return (
    <Routes>
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
