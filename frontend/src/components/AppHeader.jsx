import { useAuth } from "@/lib/auth";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { SignOut, Gauge, MapTrifold, Users } from "@phosphor-icons/react";

export default function AppHeader() {
  const { user, logout } = useAuth();
  const loc = useLocation();
  const navigate = useNavigate();
  const isAdmin = user?.role === "admin";

  return (
    <header className="bg-card border-b border-border sticky top-0 z-30">
      <div className="px-4 sm:px-6 h-16 flex items-center justify-between">
        <Link to={isAdmin ? "/admin" : "/dashboard"} className="flex items-center gap-3" data-testid="brand-link">
          <img
            src="https://customer-assets.emergentagent.com/job_employee-locator-4/artifacts/5n0qsrf7_GTG%20LOGO%20BLACK.png"
            alt="Gyarahalli Thammayya Groups"
            className="brand-logo w-10 h-10 object-contain"
          />
          <div className="hidden sm:flex flex-col leading-tight">
            <span className="text-[10px] label-overline">Gyarahalli Thammayya</span>
            <span className="text-sm font-semibold tracking-tight">Attendance &amp; Field Work</span>
          </div>
        </Link>

        <nav className="flex items-center gap-1">
          {isAdmin && (
            <>
              <NavLink to="/admin" current={loc.pathname.startsWith("/admin")} icon={<Gauge size={16} weight="bold"/>} label="Console" testid="nav-admin"/>
              <NavLink to="/dashboard" current={loc.pathname === "/dashboard"} icon={<MapTrifold size={16} weight="bold"/>} label="My Day" testid="nav-my-day"/>
            </>
          )}
          {!isAdmin && (
            <NavLink to="/dashboard" current={loc.pathname === "/dashboard"} icon={<MapTrifold size={16} weight="bold"/>} label="My Day" testid="nav-my-day"/>
          )}
        </nav>

        <div className="flex items-center gap-3">
          <div className="hidden sm:flex items-center gap-2">
            {user?.picture ? (
              <img src={user.picture} alt="" className="w-8 h-8 rounded-full border border-border"/>
            ) : (
              <div className="w-8 h-8 rounded-full bg-secondary grid place-items-center text-xs font-medium">
                {user?.name?.[0]}
              </div>
            )}
            <div className="leading-tight">
              <div className="text-sm font-medium" data-testid="user-name">{user?.name}</div>
              <div className="text-[10px] label-overline" data-testid="user-role">{user?.role}</div>
            </div>
          </div>
          <button
            onClick={async () => { await logout(); navigate("/", { replace: true }); }}
            data-testid="logout-button"
            className="border border-border bg-card px-3 py-2 text-xs hover:bg-foreground hover:text-background transition-colors flex items-center gap-2"
          >
            <SignOut size={14} weight="bold"/>
            <span className="hidden sm:inline">Sign out</span>
          </button>
        </div>
      </div>
    </header>
  );
}

const NavLink = ({ to, current, icon, label, testid }) => (
  <Link
    to={to}
    data-testid={testid}
    className={`flex items-center gap-2 px-3 py-2 text-xs uppercase tracking-[0.15em] border ${current ? "bg-foreground text-background border-foreground" : "border-transparent hover:border-border"}`}
  >
    {icon}
    <span className="hidden sm:inline">{label}</span>
  </Link>
);
