import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { Toaster } from "sonner";
import { AuthProvider, useAuth } from "@/lib/auth";
import Login from "@/pages/Login";
import AuthCallback from "@/pages/AuthCallback";
import Dashboard from "@/pages/Dashboard";
import AdminPanel from "@/pages/AdminPanel";
import FaceEnroll from "@/pages/FaceEnroll";
import Reports from "@/pages/Reports";
import LeavePage from "@/pages/LeavePage";
import ProfilePage from "@/pages/ProfilePage";
import ChangePassword from "@/pages/ChangePassword";
import ResetPassword from "@/pages/ResetPassword";

const isManager = (user) => user?.role === "admin" || user?.role === "sub_admin";

function ProtectedRoute({ children, managerOnly = false, skipFaceCheck = false, allowPasswordChange = false }) {
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
  if (!skipFaceCheck && !user.face_enrolled) return <Navigate to="/enroll" replace/>;
  if (managerOnly && !isManager(user)) return <Navigate to="/dashboard" replace/>;
  return children;
}

function RootRedirect() {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (user) {
    if (user.must_change_password) return <Navigate to="/change-password" replace/>;
    if (!user.face_enrolled) return <Navigate to="/enroll" replace/>;
    return <Navigate to={isManager(user) ? "/admin" : "/dashboard"} replace/>;
  }
  return <Login/>;
}

function AppRouter() {
  const location = useLocation();
  if (location.hash?.includes("session_id=")) return <AuthCallback/>;
  return (
    <Routes>
      <Route path="/" element={<RootRedirect/>}/>
      <Route path="/reset-password" element={<ResetPassword/>}/>
      <Route path="/change-password" element={<ProtectedRoute skipFaceCheck allowPasswordChange><ChangePassword/></ProtectedRoute>}/>
      <Route path="/enroll" element={<ProtectedRoute skipFaceCheck><FaceEnroll/></ProtectedRoute>}/>
      <Route path="/dashboard" element={<ProtectedRoute><Dashboard/></ProtectedRoute>}/>
      <Route path="/leave" element={<ProtectedRoute><LeavePage/></ProtectedRoute>}/>
      <Route path="/profile" element={<ProtectedRoute><ProfilePage/></ProtectedRoute>}/>
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
