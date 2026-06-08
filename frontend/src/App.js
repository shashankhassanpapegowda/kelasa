import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { Toaster } from "sonner";
import { AuthProvider, useAuth } from "@/lib/auth";
import Login from "@/pages/Login";
import AuthCallback from "@/pages/AuthCallback";
import Dashboard from "@/pages/Dashboard";
import AdminPanel from "@/pages/AdminPanel";

function ProtectedRoute({ children, adminOnly = false }) {
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
  if (adminOnly && user.role !== "admin") return <Navigate to="/dashboard" replace/>;
  return children;
}

function RootRedirect() {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (user) return <Navigate to={user.role === "admin" ? "/admin" : "/dashboard"} replace/>;
  return <Login/>;
}

function AppRouter() {
  const location = useLocation();
  if (location.hash?.includes("session_id=")) {
    return <AuthCallback/>;
  }
  return (
    <Routes>
      <Route path="/" element={<RootRedirect/>}/>
      <Route path="/dashboard" element={<ProtectedRoute><Dashboard/></ProtectedRoute>}/>
      <Route path="/admin" element={<ProtectedRoute adminOnly><AdminPanel/></ProtectedRoute>}/>
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
          <Toaster position="top-right" richColors/>
        </AuthProvider>
      </BrowserRouter>
    </div>
  );
}
