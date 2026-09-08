import { ArrowRight, MapTrifold, ClockClockwise, ShieldCheck } from "@phosphor-icons/react";

// REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
export default function Login() {
  const handleLogin = () => {
    const redirectUrl = window.location.origin + "/dashboard";
    window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
  };

  return (
    <div className="min-h-screen grid lg:grid-cols-2 bg-background">
      {/* Left: form */}
      <div className="flex flex-col justify-between p-8 lg:p-14 bg-card border-r border-border">
        <div className="flex items-center gap-3">
          <img
            src="https://customer-assets.emergentagent.com/job_employee-locator-4/artifacts/5n0qsrf7_GTG%20LOGO%20BLACK.png"
            alt="Kelasa"
            className="brand-logo w-14 h-14 object-contain"
          />
          <div className="flex flex-col leading-tight">
            <span className="text-2xl font-semibold" style={{ fontFamily: "'Hubballi', sans-serif" }}>ಕೆಲಸ</span>
            <span className="text-xs label-overline">Kelasa</span>
          </div>
        </div>

        <div className="max-w-md">
          <div className="label-overline mb-4" data-testid="login-overline">Welcome to Kelasa</div>
          <h1 className="text-5xl lg:text-6xl font-semibold tracking-tight leading-[1.05]">
            <span style={{ fontFamily: "'Hubballi', sans-serif" }}>ಕೆಲಸ</span><br/>Kelasa<span className="text-primary">.</span>
          </h1>
          <p className="mt-6 text-muted-foreground text-base leading-relaxed">
            Bring your whole field team together — attendance, live routes and on-site hours, all in one calm, reliable place. Sign in to pick up right where the day left off.
          </p>

          <button
            onClick={handleLogin}
            data-testid="login-google-button"
            className="mt-10 group inline-flex items-center gap-3 bg-foreground text-background px-6 py-4 hover:bg-primary transition-colors w-full sm:w-auto"
          >
            <span className="font-medium tracking-tight">Continue with Google</span>
            <ArrowRight size={18} weight="bold" className="transition-transform group-hover:translate-x-1"/>
          </button>
          <p className="mt-4 text-xs text-muted-foreground">Secured by Google sign-in — your data stays private.</p>
        </div>

        <div className="border-t border-border pt-6 space-y-6">
          <div className="grid grid-cols-3 gap-0">
            <Feature icon={<MapTrifold size={18} weight="bold"/>} label="Live Routes"/>
            <Feature icon={<ClockClockwise size={18} weight="bold"/>} label="Auto Hours"/>
            <Feature icon={<ShieldCheck size={18} weight="bold"/>} label="Role Access"/>
          </div>
          <div className="flex items-center gap-2.5 text-muted-foreground" data-testid="powered-by">
            <img
              src="https://customer-assets.emergentagent.com/job_employee-locator-4/artifacts/5n0qsrf7_GTG%20LOGO%20BLACK.png"
              alt="Gyarahalli Thammayya Groups"
              className="w-6 h-6 object-contain opacity-70"
            />
            <span className="text-[11px] tracking-wide">Powered by Gyarahalli Thammayya Groups</span>
          </div>
        </div>
      </div>

      {/* Right: visual */}
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
