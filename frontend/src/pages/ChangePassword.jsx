import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, apiErrorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { toast } from "sonner";
import { Lock, SignOut } from "@phosphor-icons/react";

export default function ChangePassword() {
  const { user, checkAuth, logout } = useAuth();
  const navigate = useNavigate();
  const forced = !!user?.must_change_password;
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    if (next !== confirm) return setError("The two new passwords don't match");
    if (next.length < 8) return setError("Password must be at least 8 characters");
    setBusy(true);
    try {
      await api.post("/auth/change-password", { current_password: current, new_password: next });
      toast.success("Password updated");
      await checkAuth();
      navigate("/", { replace: true });
    } catch (err) {
      setError(apiErrorMessage(err, "Could not update your password"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen grid place-items-center bg-background p-6">
      <div className="w-full max-w-md border border-border bg-card" data-testid="change-password-page">
        <div className="p-6 border-b border-border">
          <div className="flex items-center gap-2">
            <Lock size={16} weight="bold" className="text-primary"/>
            <span className="label-overline">{forced ? "Set your own password" : "Change password"}</span>
          </div>
          <h1 className="text-2xl font-semibold tracking-tight mt-2">
            {forced ? "Choose a password only you know" : "Update your password"}
          </h1>
          {forced && (
            <p className="text-sm text-muted-foreground mt-2">
              You're signed in with the temporary password your admin gave you. Set your own before you continue.
            </p>
          )}
        </div>
        <form onSubmit={submit} className="p-6 space-y-4">
          <div>
            <label className="label-overline mb-1.5 block">{forced ? "Temporary password" : "Current password"}</label>
            <input type="password" required value={current} onChange={(e) => setCurrent(e.target.value)} data-testid="current-password"
              autoComplete="current-password" className="w-full bg-background border border-border px-3 py-3 text-sm"/>
          </div>
          <div>
            <label className="label-overline mb-1.5 block">New password</label>
            <input type="password" required value={next} onChange={(e) => setNext(e.target.value)} data-testid="new-password"
              autoComplete="new-password" className="w-full bg-background border border-border px-3 py-3 text-sm"/>
            <p className="text-[10px] text-muted-foreground mt-1">At least 8 characters.</p>
          </div>
          <div>
            <label className="label-overline mb-1.5 block">Confirm new password</label>
            <input type="password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} data-testid="confirm-password"
              autoComplete="new-password" className="w-full bg-background border border-border px-3 py-3 text-sm"/>
          </div>
          {error && <p className="text-sm text-[#FF3B30]" data-testid="change-password-error">{error}</p>}
          <button type="submit" disabled={busy} data-testid="change-password-submit"
            className="w-full bg-foreground text-background px-4 py-3 hover:bg-primary transition-colors font-medium disabled:opacity-60">
            {busy ? "Saving…" : "Save password"}
          </button>
          <button type="button" onClick={logout} data-testid="change-password-logout"
            className="w-full text-xs label-overline text-muted-foreground hover:text-foreground inline-flex items-center justify-center gap-1.5">
            <SignOut size={12} weight="bold"/> Sign out instead
          </button>
        </form>
      </div>
    </div>
  );
}
