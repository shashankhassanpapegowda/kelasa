import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "sonner";
import { AuthProvider, useAuth } from "@/lib/auth";
import Login from "@/pages/Login";
import Dashboard from "@/pages/Dashboard";
import AdminPanel from "@/pages/AdminPanel";
import CalendarPage from "@/pages/CalendarPage";
import Reports from "@/pages/Reports";
import LeavePage from "@/pages/LeavePage";
import ProfilePage from "@/pages/ProfilePage";
import WishesPage from "@/pages/WishesPage";
import ChangePassword from "@/pages/ChangePassword";
import ResetPassword from "@/pages/ResetPassword";
import SalaryPage from "@/pages/SalaryPage";

const isManager = (user) => user?.role === "admin" || user?.role === "sub_admin";

function ProtectedRoute({ children, managerOnly = false, allowPasswordChange = false }) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="min-h-screen grid place-items-center p-8">
        <div className="w-72">
          <div className="label-overline mb-3">Loading</div>
          <div className="loading-bar"/>
        </div>
      </div>
    );
  }
  if (!user) return <Navigate to="/" replace/>;
  if (user.must_change_password && !allowPasswordChange) return <Navigate to="/change-password" replace/>;
  if (managerOnly && !isManager(user)) return <Navigate to="/dashboard" replace/>;
  return children;
}

function RootRedirect() {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (user) {
    if (user.must_change_password) return <Navigate to="/change-password" replace/>;
    return <Navigate to={isManager(user) ? "/admin" : "/dashboard"} replace/>;
  }
  return <Login/>;
}

function SalaryGate() {
  const { user } = useAuth();
  if (user?.role === "sub_admin") return <Navigate to="/admin" replace/>;
  if (user?.role !== "employee" && user?.role !== "admin") return <Navigate to="/dashboard" replace/>;
  return <SalaryPage/>;
}

function AppRouter() {
  return (
    <Routes>
      <Route path="/" element={<RootRedirect/>}/>
      <Route path="/reset-password" element={<ResetPassword/>}/>
      <Route path="/change-password" element={<ProtectedRoute allowPasswordChange><ChangePassword/></ProtectedRoute>}/>
      <Route path="/enroll" element={<Navigate to="/dashboard" replace/>}/>
      <Route path="/calendar" element={<ProtectedRoute><CalendarPage/></ProtectedRoute>}/>
      <Route path="/dashboard" element={<ProtectedRoute><Dashboard/></ProtectedRoute>}/>
      <Route path="/leave" element={<ProtectedRoute><LeavePage/></ProtectedRoute>}/>
      <Route path="/profile" element={<ProtectedRoute><ProfilePage/></ProtectedRoute>}/>
      <Route path="/wishes" element={<ProtectedRoute><WishesPage/></ProtectedRoute>}/>
      <Route path="/salary" element={<ProtectedRoute><SalaryGate/></ProtectedRoute>}/>
      <Route path="/admin" element={<ProtectedRoute managerOnly><AdminPanel/></ProtectedRoute>}/>
      <Route path="/admin/reports" element={<ProtectedRoute managerOnly><Reports/></ProtectedRoute>}/>
      <Route path="*" element={<Navigate to="/" replace/>}/>
    </Routes>
  );
}

export default function App() {
  return (
    <div className="App">
      <BrowserRouter>
        <AuthProvider>
          <AppRouter/>
          <Toaster position="bottom-right" richColors/>
        </AuthProvider>
      </BrowserRouter>
    </div>
  );
}
