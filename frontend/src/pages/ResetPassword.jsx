import { useState } from "react";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import { api, apiErrorMessage } from "@/lib/api";
import { toast } from "sonner";
import { Lock } from "@phosphor-icons/react";

export default function ResetPassword() {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const navigate = useNavigate();
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    if (next !== confirm) return setError("The two passwords don't match");
    if (next.length < 8) return setError("Password must be at least 8 characters");
    setBusy(true);
    try {
      await api.post("/auth/reset-password", { token, new_password: next });
      setDone(true);
      toast.success("Password updated — sign in with your new password");
      setTimeout(() => navigate("/", { replace: true }), 2000);
    } catch (err) {
      setError(apiErrorMessage(err, "Could not reset your password"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen grid place-items-center bg-background p-6">
      <div className="w-full max-w-md border border-border bg-card" data-testid="reset-password-page">
        <div className="p-6 border-b border-border">
          <div className="flex items-center gap-2">
            <Lock size={16} weight="bold" className="text-primary"/>
            <span className="label-overline">Kelasa · Password reset</span>
          </div>
          <h1 className="text-2xl font-semibold tracking-tight mt-2">Set a new password</h1>
        </div>
        {!token ? (
          <div className="p-6">
            <p className="text-sm text-muted-foreground" data-testid="reset-no-token">
              This link is missing its reset code. Request a fresh one from the sign-in page.
            </p>
            <Link to="/" className="mt-4 inline-block text-xs label-overline hover:text-primary">Back to sign in</Link>
          </div>
        ) : done ? (
          <div className="p-6" data-testid="reset-done">
            <p className="text-sm">Your password is updated. Taking you to sign in…</p>
          </div>
        ) : (
          <form onSubmit={submit} className="p-6 space-y-4">
            <div>
              <label className="label-overline mb-1.5 block">New password</label>
              <input type="password" required value={next} onChange={(e) => setNext(e.target.value)} data-testid="reset-new-password"
                autoComplete="new-password" className="w-full bg-background border border-border px-3 py-3 text-sm"/>
              <p className="text-[10px] text-muted-foreground mt-1">At least 8 characters.</p>
            </div>
            <div>
              <label className="label-overline mb-1.5 block">Confirm password</label>
              <input type="password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} data-testid="reset-confirm-password"
                autoComplete="new-password" className="w-full bg-background border border-border px-3 py-3 text-sm"/>
            </div>
            {error && <p className="text-sm text-[#FF3B30]" data-testid="reset-error">{error}</p>}
            <button type="submit" disabled={busy} data-testid="reset-submit"
              className="w-full bg-foreground text-background px-4 py-3 hover:bg-primary transition-colors font-medium disabled:opacity-60">
              {busy ? "Saving…" : "Save new password"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
