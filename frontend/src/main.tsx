import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import Layout from "./app/Layout";
import { AuthProvider } from "./auth/AuthContext";
import i18n from "./i18n";
import "./index.css";
import DashboardPage from "./modules/dashboard/DashboardPage";
import DrillholesPage from "./modules/drillholes/DrillholesPage";
import ScanningPage from "./modules/scanning/ScanningPage";
import BlastingPage from "./modules/blasting/BlastingPage";
import DetonatorsPage from "./modules/detonators/DetonatorsPage";
import LaboratoryPage from "./modules/laboratory/LaboratoryPage";
import PlanningPage from "./modules/planning/PlanningPage";
import SafetyPage from "./modules/safety/SafetyPage";
import VibrationPage from "./modules/vibration/VibrationPage";
import KpiPage from "./modules/kpi/KpiPage";
import PostBlastPage from "./modules/postblast/PostBlastPage";
import ReportsPage from "./modules/reports/ReportsPage";
import SettingsPage from "./modules/settings/SettingsPage";
import UsersPage from "./modules/users/UsersPage";
import MasterDataPage from "./modules/masterdata/MasterDataPage";

const qc = new QueryClient({ defaultOptions: { queries: { staleTime: 60_000, retry: 1, refetchOnWindowFocus: false } } });
// server texts (KPI names, alerts, errors…) are produced in the UI language: refetch when it changes
// (cancel first: a first load still in flight would otherwise be reused and keep the previous language)
i18n.on("languageChanged", () => { void qc.cancelQueries().then(() => qc.invalidateQueries()); });


createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<DashboardPage />} />
            <Route path="planning" element={<PlanningPage />} />
            <Route path="blasting" element={<BlastingPage />} />
            <Route path="laboratory" element={<LaboratoryPage />} />
            <Route path="vibration" element={<VibrationPage />} />
            <Route path="detonators" element={<DetonatorsPage />} />
            <Route path="safety" element={<SafetyPage />} />
            <Route path="scanning" element={<ScanningPage />} />
            <Route path="drillholes" element={<DrillholesPage />} />
            <Route path="postblast" element={<PostBlastPage />} />
            <Route path="kpi" element={<KpiPage />} />
            <Route path="reports" element={<ReportsPage />} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="users" element={<UsersPage />} />
            <Route path="masterdata" element={<MasterDataPage />} />
            <Route path="*" element={<DashboardPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  </StrictMode>,
);
