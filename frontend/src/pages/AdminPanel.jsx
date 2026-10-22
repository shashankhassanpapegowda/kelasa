import { useEffect, useState } from "react";
import AppHeader from "@/components/AppHeader";
import OverviewTab from "@/components/admin/OverviewTab";
import LiveTab from "@/components/admin/LiveTab";
import TeamTab from "@/components/admin/TeamTab";
import LeaveTab from "@/components/admin/LeaveTab";
import OrgTab from "@/components/admin/OrgTab";
import CalendarTab from "@/components/admin/CalendarTab";
import NoticesTab from "@/components/admin/NoticesTab";
import ActivityTab from "@/components/admin/ActivityTab";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Gauge, Broadcast, Users, AirplaneTilt, CalendarBlank, Megaphone, Buildings, ClockCounterClockwise } from "@phosphor-icons/react";

const TABS = [
  { id: "overview", label: "Overview", icon: Gauge },
  { id: "live", label: "Live Map", icon: Broadcast },
  { id: "team", label: "Team", icon: Users },
  { id: "leave", label: "Leave", icon: AirplaneTilt },
  { id: "calendar", label: "Holidays", icon: CalendarBlank },
  { id: "notices", label: "Notices", icon: Megaphone },
  { id: "org", label: "Organisation", icon: Buildings, adminOnly: true },
  { id: "activity", label: "Activity", icon: ClockCounterClockwise, adminOnly: true },
];

export default function AdminPanel() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [tab, setTab] = useState(() => window.location.hash.replace("#", "") || "overview");
  const [pendingLeave, setPendingLeave] = useState(0);

  useEffect(() => { window.location.hash = tab; }, [tab]);

  useEffect(() => {
    api.get("/admin/leave?status=pending")
      .then(r => setPendingLeave(r.data.pending_count || 0))
      .catch(() => {});
  }, [tab]);

  const visible = TABS.filter(t => isAdmin || !t.adminOnly);

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <AppHeader/>
      <main className="flex-1">
        <div className="px-4 sm:px-6 py-6">
          <div className="flex items-end justify-between gap-4 flex-wrap">
            <div>
              <div className="label-overline" data-testid="admin-overline">
                {isAdmin ? "Employee Management Console" : "Team Console"}
              </div>
              <h1 className="text-3xl sm:text-4xl font-semibold tracking-tight mt-1">
                {isAdmin ? "Master Panel" : `${user?.name?.split(" ")[0]}'s Team`}
              </h1>
              {!isAdmin && (
                <p className="text-xs text-muted-foreground mt-2 max-w-md">
                  You are seeing only the people you cover — your reportees plus your assigned departments and sites.
                </p>
              )}
            </div>
          </div>

          <div className="mt-6 flex items-center gap-1 overflow-x-auto border-b border-border pb-px" data-testid="admin-tabs">
            {visible.map(t => {
              const Icon = t.icon;
              const active = tab === t.id;
              return (
                <button key={t.id} onClick={() => setTab(t.id)} data-testid={`tab-${t.id}`}
                  className={`relative flex items-center gap-2 px-4 py-3 text-xs uppercase tracking-[0.15em] whitespace-nowrap border-b-2 transition-colors ${active ? "border-foreground text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`}>
                  <Icon size={15} weight="bold"/>
                  {t.label}
                  {t.id === "leave" && pendingLeave > 0 && (
                    <span className="ml-1 bg-[#FF3B30] text-white text-[9px] font-mono px-1.5 py-0.5" data-testid="leave-pending-badge">{pendingLeave}</span>
                  )}
                </button>
              );
            })}
          </div>

          <div className="mt-6">
            {tab === "overview" && <OverviewTab/>}
            {tab === "live" && <LiveTab/>}
            {tab === "team" && <TeamTab isAdmin={isAdmin} currentUserId={user?.user_id}/>}
            {tab === "leave" && <LeaveTab isAdmin={isAdmin}/>}
            {tab === "calendar" && <CalendarTab isAdmin={isAdmin}/>}
            {tab === "notices" && <NoticesTab/>}
            {tab === "org" && isAdmin && <OrgTab/>}
            {tab === "activity" && isAdmin && <ActivityTab/>}
          </div>
        </div>
      </main>
    </div>
  );
}
