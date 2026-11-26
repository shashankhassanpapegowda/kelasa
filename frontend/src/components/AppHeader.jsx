import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import AuthPhoto from "@/components/AuthPhoto";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { SignOut, Gauge, MapTrifold, ChartBar, AirplaneTilt, Lock, UserCircle, HandHeart, CalendarDots, CurrencyInr } from "@phosphor-icons/react";

export default function AppHeader() {
  const { user, logout } = useAuth();
  const loc = useLocation();
  const [unread, setUnread] = useState(0);
  useEffect(() => {
    const load = () => api.get("/wishes/unread-count").then(r => setUnread(r.data.unread || 0)).catch(() => {});
    load();
    const id = setInterval(load, 60000);
    window.addEventListener("kelasa-wishes-read", load);
    return () => { clearInterval(id); window.removeEventListener("kelasa-wishes-read", load); };
  }, [loc.pathname]);
  const navigate = useNavigate();
  const isManager = user?.role === "admin" || user?.role === "sub_admin";

  return (
    <header className="bg-card border-b border-border sticky top-0 z-30">
      <div className="px-4 sm:px-6 h-16 flex items-center justify-between">
        <Link to={isManager ? "/admin" : "/dashboard"} className="flex items-center gap-3" data-testid="brand-link">
          <img
            src="/icons/logo-black.png"
            alt="Gyarahalli Thammayya Groups"
            className="brand-logo w-10 h-10 object-contain"
          />
          <div className="hidden sm:flex flex-col leading-tight">
            <span className="text-lg font-semibold leading-none" style={{ fontFamily: "'Hubballi', sans-serif" }}>ಕೆಲಸ</span>
            <span className="text-[10px] label-overline">Kelasa</span>
          </div>
        </Link>

        <nav className="flex items-center gap-1">
          {isManager && (
            <>
              <NavLink to="/admin" current={loc.pathname.startsWith("/admin") && loc.pathname !== "/admin/reports"} icon={<Gauge size={16} weight="bold"/>} label="Console" testid="nav-admin"/>
              <NavLink to="/admin/reports" current={loc.pathname === "/admin/reports"} icon={<ChartBar size={16} weight="bold"/>} label="Reports" testid="nav-reports"/>
            </>
          )}
          <NavLink to="/dashboard" current={loc.pathname === "/dashboard"} icon={<MapTrifold size={16} weight="bold"/>} label="My Day" testid="nav-my-day"/>
          <NavLink to="/calendar" current={loc.pathname === "/calendar"} icon={<CalendarDots size={16} weight="bold"/>} label="Calendar" testid="nav-calendar"/>
          <NavLink to="/leave" current={loc.pathname === "/leave"} icon={<AirplaneTilt size={16} weight="bold"/>} label="Leave" testid="nav-leave"/>
          <NavLink to="/wishes" current={loc.pathname === "/wishes"} icon={<span className="relative mr-1.5"><HandHeart size={16} weight="bold"/>{unread > 0 && <span className="absolute -top-1.5 -right-2 min-w-[14px] h-[14px] px-0.5 rounded-full bg-[#FF3B30] text-white text-[9px] font-mono grid place-items-center" data-testid="wishes-unread-badge">{unread}</span>}</span>} label="Wishes" testid="nav-wishes"/>
          <NavLink to="/profile" current={loc.pathname === "/profile"} icon={<UserCircle size={16} weight="bold"/>} label="Profile" testid="nav-profile"/>
          {user?.role === "employee" && (
            <NavLink to="/salary" current={loc.pathname === "/salary"} icon={<CurrencyInr size={16} weight="bold"/>} label="Salary" testid="nav-salary"/>
          )}
        </nav>

        <div className="flex items-center gap-3">
          <Link to="/profile" className="hidden sm:flex items-center gap-2" data-testid="header-profile-link">
            <AuthPhoto key={user?.avatar_path || "none"} path={user?.avatar_path} className="w-8 h-8 rounded-full object-cover border border-border"
              fallback={<div className="w-8 h-8 rounded-full bg-secondary grid place-items-center text-xs font-medium">{user?.name?.[0]}</div>}/>
            <div className="leading-tight">
              <div className="text-sm font-medium" data-testid="user-name">{user?.name}</div>
              <div className="text-[10px] label-overline" data-testid="user-role">{String(user?.role || "").replace("_", "-")}</div>
            </div>
          </Link>
          <Link
            to="/change-password"
            data-testid="nav-change-password"
            title="Change password"
            className="border border-border bg-card px-3 py-2 text-xs hover:bg-foreground hover:text-background transition-colors flex items-center gap-2"
          >
            <Lock size={14} weight="bold"/>
            <span className="hidden lg:inline">Password</span>
          </Link>
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
