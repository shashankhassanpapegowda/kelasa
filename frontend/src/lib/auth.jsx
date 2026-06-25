import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { api, setToken, setUnauthorizedHandler } from "@/lib/api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const checkAuth = useCallback(async () => {
    try {
      const res = await api.get("/auth/me");
      setUser(res.data);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Wire global 401 handler — any expired session kicks user back to login cleanly.
    setUnauthorizedHandler(() => {
      setUser(null);
      setToken(null);
      if (window.location.pathname !== "/") {
        window.location.replace("/");
      }
    });
    // If returning from OAuth, let AuthCallback handle it first.
    if (window.location.hash?.includes("session_id=")) {
      setLoading(false);
      return;
    }
    checkAuth();
  }, [checkAuth]);

  const logout = async () => {
    try {
      await api.post("/auth/logout");
    } catch (err) {
      console.warn("logout request failed", err);
    }
    setToken(null);
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, setUser, loading, checkAuth, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
