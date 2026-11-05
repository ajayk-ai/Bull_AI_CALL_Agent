import { BrowserRouter, Navigate, Route, Routes } from "react-router";

import { Layout } from "./components/Layout";
import { Loading } from "./components/ui";
import { AuthProvider, useAuth } from "./lib/auth";
import { AuditPage } from "./pages/Audit";
import { CallDetailPage } from "./pages/CallDetail";
import { CallsPage } from "./pages/Calls";
import { CampaignDetailPage } from "./pages/CampaignDetail";
import { ChangePasswordPage, ForcedPasswordChange } from "./pages/ChangePassword";
import { CampaignsPage } from "./pages/Campaigns";
import { ContactsPage } from "./pages/Contacts";
import { DepartmentsPage } from "./pages/Departments";
import { DncPage } from "./pages/Dnc";
import { ImportsPage } from "./pages/Imports";
import { ImportWizardPage } from "./pages/ImportWizard";
import { LoginPage } from "./pages/Login";
import { ScriptEditorPage } from "./pages/ScriptEditor";
import { ScriptsPage } from "./pages/Scripts";
import { UsersPage } from "./pages/Users";

function Routed() {
  const { me, loading } = useAuth();
  if (loading) return <Loading />;
  if (!me) return <LoginPage />;
  if (me.must_change_password) return <ForcedPasswordChange />;
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/campaigns" replace />} />
        <Route path="campaigns" element={<CampaignsPage />} />
        <Route path="campaigns/:id" element={<CampaignDetailPage />} />
        <Route path="calls" element={<CallsPage />} />
        <Route path="calls/:id" element={<CallDetailPage />} />
        <Route path="contacts" element={<ContactsPage />} />
        <Route path="imports" element={<ImportsPage />} />
        <Route path="imports/new" element={<ImportWizardPage />} />
        <Route path="scripts" element={<ScriptsPage />} />
        <Route path="scripts/new" element={<ScriptEditorPage />} />
        <Route path="scripts/:scriptId/versions/:versionId" element={<ScriptEditorPage />} />
        <Route path="dnc" element={<DncPage />} />
        <Route path="users" element={<UsersPage />} />
        <Route path="departments" element={<DepartmentsPage />} />
        <Route path="audit" element={<AuditPage />} />
        <Route path="account/password" element={<ChangePasswordPage />} />
        <Route path="*" element={<Navigate to="/campaigns" replace />} />
      </Route>
    </Routes>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routed />
      </AuthProvider>
    </BrowserRouter>
  );
}
