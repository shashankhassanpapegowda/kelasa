import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { api, setToken } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function AuthCallback() {
  const navigate = useNavigate();
  const { setUser } = useAuth();
  const hasProcessed = useRef(false);

  useEffect(() => {
    if (hasProcessed.current) return;
    hasProcessed.current = true;
    const hash = window.location.hash || "";
    const match = hash.match(/session_id=([^&]+)/);
    if (!match) {
      navigate("/", { replace: true });
      return;
    }
    const sessionId = match[1];
    (async () => {
      try {
        const res = await api.post("/auth/session", { session_id: sessionId });
        if (res.data.session_token) {
          setToken(res.data.session_token);
        }
        setUser(res.data.user);
        window.history.replaceState(null, "", "/dashboard");
        if (res.data.user.role === "admin") {
          navigate("/admin", { replace: true, state: { user: res.data.user } });
        } else {
          navigate("/dashboard", { replace: true, state: { user: res.data.user } });
        }
      } catch {
        navigate("/", { replace: true });
      }
    })();
  }, [navigate, setUser]);

  return (
    <div className="min-h-screen grid place-items-center bg-background p-8">
      <div className="max-w-sm w-full">
        <div className="label-overline mb-3">Authenticating</div>
        <div className="loading-bar"/>
        <p className="mt-4 text-sm text-muted-foreground font-mono">Establishing secure session…</p>
      </div>
    </div>
  );
}
