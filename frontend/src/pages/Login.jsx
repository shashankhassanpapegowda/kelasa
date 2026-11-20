import { useState } from "react";
import { api, setToken, apiErrorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { toast } from "sonner";
import { ArrowRight, MapTrifold, ClockClockwise, ShieldCheck, Envelope, Lock, CaretLeft } from "@phosphor-icons/react";

export default function Login() {
  const { setUser } = useAuth();
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const res = await api.post("/auth/login", { email: email.trim(), password });
      if (res.data.session_token) setToken(res.data.session_token);
      setUser(res.data.user);
    } catch (err) {
      setError(apiErrorMessage(err, "Could not sign you in"));
    } finally {
      setBusy(false);
    }
  };

  const sendReset = async (e) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await api.post("/auth/forgot-password", { email: email.trim() });
      setSent(true);
      toast.success("If that email is registered, a reset link is on its way.");
    } catch (err) {
      setError(apiErrorMessage(err, "Could not send the reset email"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen grid lg:grid-cols-2 bg-background">
      <div className="flex flex-col justify-between p-8 lg:p-14 bg-card border-r border-border">
        <div className="flex items-center gap-3">
          <img
            src="/icons/logo-black.png"
            alt="Kelasa"
            className="brand-logo w-14 h-14 object-contain"
          />
          <div className="flex flex-col leading-tight">
            <span className="text-2xl font-semibold" style={{ fontFamily: "'Hubballi', sans-serif" }}>ಕೆಲಸ</span>
            <span className="text-xs label-overline">Kelasa</span>
          </div>
        </div>

        <div className="max-w-md w-full">
          <div className="label-overline mb-4" data-testid="login-overline">Employee Management Platform</div>
          <h1 className="text-4xl lg:text-5xl font-semibold tracking-tight leading-[1.05]">
            {mode === "login" ? <>Your whole team,<br/>in one place<span className="text-primary">.</span></> : <>Reset your<br/>password<span className="text-primary">.</span></>}
          </h1>

          {mode === "login" ? (
            <form onSubmit={submit} className="mt-8 space-y-4" data-testid="login-form">
              <div>
                <label className="label-overline mb-1.5 block">Work Email</label>
                <div className="relative">
                  <Envelope size={15} weight="bold" className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"/>
                  <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} data-testid="login-email"
                    autoComplete="username" placeholder="you@company.com"
                    className="w-full bg-background border border-border pl-9 pr-3 py-3 text-sm focus:border-foreground outline-none transition-colors"/>
                </div>
              </div>
              <div>
                <label className="label-overline mb-1.5 block">Password</label>
                <div className="relative">
                  <Lock size={15} weight="bold" className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"/>
                  <input type="password" required value={password} onChange={(e) => setPassword(e.target.value)} data-testid="login-password"
                    autoComplete="current-password" placeholder="••••••••"
                    className="w-full bg-background border border-border pl-9 pr-3 py-3 text-sm focus:border-foreground outline-none transition-colors"/>
                </div>
              </div>

              {error && <p className="text-sm text-[#FF3B30]" data-testid="login-error">{error}</p>}

              <button type="submit" disabled={busy} data-testid="login-submit"
                className="group w-full inline-flex items-center justify-between gap-3 bg-foreground text-background px-6 py-4 hover:bg-primary transition-colors disabled:opacity-60">
                <span className="font-medium tracking-tight">{busy ? "Signing in…" : "Sign in"}</span>
                <ArrowRight size={18} weight="bold" className="transition-transform group-hover:translate-x-1"/>
              </button>

              <button type="button" onClick={() => { setMode("forgot"); setError(""); setSent(false); }} data-testid="forgot-password-link"
                className="text-xs label-overline text-muted-foreground hover:text-foreground transition-colors">
                Forgot password?
              </button>
            </form>
          ) : (
            <div className="mt-8 space-y-4" data-testid="forgot-form">
              {sent ? (
                <div className="border border-border p-5 bg-background" data-testid="reset-sent">
                  <p className="text-sm">If <span className="font-medium">{email}</span> is registered with us, a reset link is on its way. It expires in one hour.</p>
                  <p className="text-xs text-muted-foreground mt-2">Check your spam folder if it doesn't arrive in a few minutes.</p>
                </div>
              ) : (
                <form onSubmit={sendReset} className="space-y-4">
                  <p className="text-sm text-muted-foreground">Enter your work email and we'll send you a link to set a new password.</p>
                  <div>
                    <label className="label-overline mb-1.5 block">Work Email</label>
                    <div className="relative">
                      <Envelope size={15} weight="bold" className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"/>
                      <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} data-testid="forgot-email"
                        placeholder="you@company.com"
                        className="w-full bg-background border border-border pl-9 pr-3 py-3 text-sm focus:border-foreground outline-none transition-colors"/>
                    </div>
                  </div>
                  {error && <p className="text-sm text-[#FF3B30]" data-testid="forgot-error">{error}</p>}
                  <button type="submit" disabled={busy} data-testid="send-reset-btn"
                    className="w-full bg-foreground text-background px-6 py-4 hover:bg-primary transition-colors font-medium disabled:opacity-60">
                    {busy ? "Sending…" : "Send reset link"}
                  </button>
                </form>
              )}
              <button type="button" onClick={() => { setMode("login"); setError(""); }} data-testid="back-to-login"
                className="text-xs label-overline text-muted-foreground hover:text-foreground inline-flex items-center gap-1 transition-colors">
                <CaretLeft size={11} weight="bold"/> Back to sign in
              </button>
            </div>
          )}

          <p className="mt-6 text-xs text-muted-foreground">
            No account yet? Your admin creates it for you and shares your first password.
          </p>
        </div>

        <div className="border-t border-border pt-6 space-y-6">
          <div className="grid grid-cols-3 gap-0">
            <Feature icon={<ClockClockwise size={18} weight="bold"/>} label="Attendance"/>
            <Feature icon={<MapTrifold size={18} weight="bold"/>} label="Field Tracking"/>
            <Feature icon={<ShieldCheck size={18} weight="bold"/>} label="Roles & Reports"/>
          </div>
          <div className="flex items-center gap-2.5 text-muted-foreground" data-testid="powered-by">
            <img
              src="/icons/logo-black.png"
              alt="Gyarahalli Thammayya Groups"
              className="w-6 h-6 object-contain opacity-70"
            />
            <span className="text-[11px] tracking-wide">Powered by Gyarahalli Thammayya Groups</span>
          </div>
        </div>
      </div>

      <div className="hidden lg:block relative topo-bg overflow-hidden">
        <div className="absolute inset-0 opacity-20" style={{
          backgroundImage: `url("https://images.unsplash.com/photo-1774646598677-cc38cb3cac00?crop=entropy&cs=srgb&fm=jpg&ixid=M3w3NDQ2Mzl8MHwxfHNlYXJjaHwxfHxhYnN0cmFjdCUyMG1hcCUyMHRvcG9ncmFwaHklMjBiYWNrZ3JvdW5kfGVufDB8fHx8MTc4MDg5NDk4Nnww&ixlib=rb-4.1.0&q=85")`,
          backgroundSize: 'cover', backgroundPosition: 'center', mixBlendMode: 'screen'
        }}/>
        <div className="relative h-full flex flex-col justify-between p-12 text-white">
          <div className="flex items-center justify-between">
            <span className="label-overline text-white/60">Field Console</span>
            <span className="font-mono text-xs text-white/40">// LIVE</span>
          </div>
          <div className="border-t border-white/15 pt-6 max-w-md">
            <p className="text-2xl font-semibold tracking-tight leading-snug">
              For the people who keep the work moving — every day, on the ground.
            </p>
            <p className="mt-4 text-white/60 text-sm leading-relaxed">
              Kelasa turns each check-in into a clear, honest picture of the day — so your team is trusted and every hour is fairly counted.
            </p>
          </div>
          <div className="font-mono text-xs text-white/50 grid gap-1">
            <div>SECTOR_07 / KARNATAKA</div>
            <div>NODES: 24 ACTIVE</div>
            <div>SYNC: 00:00:01</div>
          </div>
        </div>
      </div>
    </div>
  );
}

const Feature = ({ icon, label }) => (
  <div className="flex flex-col gap-2 pr-4">
    <div className="text-primary">{icon}</div>
    <div className="text-xs uppercase tracking-[0.15em] text-muted-foreground">{label}</div>
  </div>
);
