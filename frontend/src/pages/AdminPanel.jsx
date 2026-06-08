import { useEffect, useState } from "react";
import AppHeader from "@/components/AppHeader";
import MapView from "@/components/MapView";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { Users, Pulse, Clock, CheckSquare, ArrowsClockwise, Path } from "@phosphor-icons/react";

const fmtTime = (iso) => iso ? new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : "—";
const fmtDuration = (mins) => {
  if (mins == null) return "—";
  const h = Math.floor(mins / 60); const m = mins % 60;
  return `${h}h ${m}m`;
};

export default function AdminPanel() {
  const [stats, setStats] = useState(null);
  const [employees, setEmployees] = useState([]);
  const [attendance, setAttendance] = useState([]);
  const [date, setDate] = useState(new Date().toISOString().slice(0,10));
  const [selectedEmp, setSelectedEmp] = useState(null);
  const [empRoute, setEmpRoute] = useState({ pings: [], attendance: [], employee: null });
  const [loading, setLoading] = useState(false);

  const refresh = async () => {
    setLoading(true);
    try {
      const [s, e, a] = await Promise.all([
        api.get("/admin/stats"),
        api.get("/admin/employees"),
        api.get(`/admin/attendance?date=${date}`),
      ]);
      setStats(s.data);
      setEmployees(e.data.employees || []);
      setAttendance(a.data.records || []);
    } catch (err) {
      toast.error("Failed to load admin data");
    } finally { setLoading(false); }
  };

  useEffect(() => { refresh(); }, [date]);

  const openEmp = async (emp) => {
    setSelectedEmp(emp);
    try {
      const res = await api.get(`/admin/employees/${emp.user_id}/route?date=${date}`);
      setEmpRoute(res.data);
    } catch {
      setEmpRoute({ pings: [], attendance: [], employee: emp });
    }
  };

  const toggleRole = async (emp) => {
    const newRole = emp.role === "admin" ? "employee" : "admin";
    try {
      await api.patch(`/admin/employees/${emp.user_id}/role`, { role: newRole });
      toast.success(`${emp.name} → ${newRole}`);
      refresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Update failed");
    }
  };

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <AppHeader/>
      <main className="flex-1">
        <div className="px-4 sm:px-6 py-6">
          <div className="flex items-end justify-between gap-4 flex-wrap">
            <div>
              <div className="label-overline" data-testid="admin-overline">Field Operations Console</div>
              <h1 className="text-3xl sm:text-4xl font-semibold tracking-tight mt-1">Master Panel</h1>
            </div>
            <div className="flex items-center gap-3">
              <input
                type="date"
                value={date}
                onChange={e => setDate(e.target.value)}
                data-testid="date-filter"
                className="bg-card border border-border px-3 py-2 text-sm font-mono"
              />
              <button onClick={refresh} className="text-xs label-overline flex items-center gap-2 hover:text-foreground" data-testid="admin-refresh">
                <ArrowsClockwise size={14} weight="bold"/> Refresh
              </button>
            </div>
          </div>

          {/* Stats */}
          <div className="mt-6 grid grid-cols-2 lg:grid-cols-4 gap-0 border border-border bg-card">
            <StatBlock label="Employees" value={stats?.total_employees ?? "—"} icon={<Users size={18} weight="bold"/>} testid="stat-employees"/>
            <StatBlock label="On Duty Now" value={stats?.on_duty ?? "—"} icon={<Pulse size={18} weight="bold"/>} accent testid="stat-on-duty"/>
            <StatBlock label="Today Check-ins" value={stats?.today_checkins ?? "—"} icon={<CheckSquare size={18} weight="bold"/>} testid="stat-checkins"/>
            <StatBlock label="Work Hrs Today" value={fmtDuration(stats?.total_work_minutes_today)} icon={<Clock size={18} weight="bold"/>} testid="stat-workhours"/>
          </div>
          {loading && <div className="loading-bar mt-2"/>}

          {/* Employees & Attendance */}
          <div className="mt-6 grid lg:grid-cols-2 gap-0 border border-border bg-card">
            {/* Employees */}
            <div className="lg:border-r border-border border-b lg:border-b-0">
              <div className="p-4 flex items-center justify-between border-b border-border">
                <span className="label-overline">Employees</span>
                <span className="font-mono text-xs text-muted-foreground">{employees.length} TOTAL</span>
              </div>
              <div className="divide-y divide-border max-h-[420px] overflow-y-auto" data-testid="employees-list">
                {employees.map(emp => (
                  <div key={emp.user_id} className="p-4 flex items-center gap-3 hover:bg-secondary/40 cursor-pointer" onClick={() => openEmp(emp)} data-testid={`emp-row-${emp.user_id}`}>
                    {emp.picture
                      ? <img src={emp.picture} className="w-10 h-10 rounded-full border border-border" alt=""/>
                      : <div className="w-10 h-10 rounded-full bg-secondary grid place-items-center text-sm font-medium">{emp.name?.[0]}</div>
                    }
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium truncate">{emp.name}</span>
                        {emp.is_on_duty && <span className="text-[10px] font-mono uppercase tracking-wider bg-[#00E676] text-black px-1.5 py-0.5">ON DUTY</span>}
                        {emp.role === "admin" && <span className="text-[10px] font-mono uppercase tracking-wider border border-border px-1.5 py-0.5">ADMIN</span>}
                      </div>
                      <div className="text-xs text-muted-foreground truncate">{emp.email}</div>
                    </div>
                    <div className="text-right">
                      <div className="font-mono text-sm">{fmtDuration(emp.today_minutes)}</div>
                      <button
                        onClick={(e) => { e.stopPropagation(); toggleRole(emp); }}
                        className="text-[10px] label-overline hover:text-primary"
                        data-testid={`toggle-role-${emp.user_id}`}
                      >
                        Make {emp.role === "admin" ? "Employee" : "Admin"}
                      </button>
                    </div>
                  </div>
                ))}
                {employees.length === 0 && <div className="p-6 text-sm text-muted-foreground">No employees yet.</div>}
              </div>
            </div>

            {/* Today's attendance */}
            <div>
              <div className="p-4 flex items-center justify-between border-b border-border">
                <span className="label-overline">Attendance Log · {date}</span>
                <span className="font-mono text-xs text-muted-foreground">{attendance.length} SESSIONS</span>
              </div>
              <div className="max-h-[420px] overflow-y-auto" data-testid="attendance-log">
                <table className="w-full text-sm">
                  <thead className="text-[10px] label-overline">
                    <tr className="border-b border-border">
                      <th className="text-left p-3">Employee</th>
                      <th className="text-left p-3">In</th>
                      <th className="text-left p-3">Out</th>
                      <th className="text-right p-3">Duration</th>
                    </tr>
                  </thead>
                  <tbody>
                    {attendance.map(r => (
                      <tr key={r.record_id} className="border-b border-border hover:bg-secondary/40">
                        <td className="p-3">
                          <div className="font-medium">{r.name || r.user_id}</div>
                          <div className="text-xs text-muted-foreground">{r.email}</div>
                        </td>
                        <td className="p-3 font-mono">{fmtTime(r.check_in)}</td>
                        <td className="p-3 font-mono">{r.check_out ? fmtTime(r.check_out) : <span className="text-[#00E676]">live</span>}</td>
                        <td className="p-3 font-mono text-right">{fmtDuration(r.duration_minutes)}</td>
                      </tr>
                    ))}
                    {attendance.length === 0 && (
                      <tr><td colSpan={4} className="p-6 text-center text-muted-foreground">No sessions on this date.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {/* Selected employee route */}
          <div className="mt-6 border border-border bg-card">
            <div className="p-4 flex items-center justify-between border-b border-border">
              <div className="flex items-center gap-2">
                <Path size={16} weight="bold" className="text-primary"/>
                <span className="label-overline">Route Inspector</span>
                {selectedEmp && <span className="text-sm font-medium ml-2" data-testid="selected-emp">{selectedEmp.name}</span>}
              </div>
              <span className="font-mono text-xs text-muted-foreground">{empRoute.pings?.length || 0} POINTS</span>
            </div>
            <div className="grid lg:grid-cols-3">
              <div className="lg:col-span-2 h-[460px] border-b lg:border-b-0 lg:border-r border-border">
                {!selectedEmp ? (
                  <div className="h-full grid place-items-center text-sm text-muted-foreground p-6 text-center">
                    Select an employee to inspect their day's route.
                  </div>
                ) : empRoute.pings?.length === 0 ? (
                  <div className="h-full grid place-items-center text-sm text-muted-foreground p-6 text-center">
                    No location pings for this employee on {date}.
                  </div>
                ) : <MapView pings={empRoute.pings}/>}
              </div>
              <div className="max-h-[460px] overflow-y-auto" data-testid="timeline">
                <div className="p-4 border-b border-border">
                  <span className="label-overline">Timeline</span>
                </div>
                <div className="divide-y divide-border">
                  {(empRoute.attendance || []).map(r => (
                    <div key={r.record_id} className="p-4">
                      <div className="text-xs label-overline mb-1">Session</div>
                      <div className="font-mono text-sm">{fmtTime(r.check_in)} → {r.check_out ? fmtTime(r.check_out) : "live"}</div>
                      <div className="text-xs text-muted-foreground mt-1">{fmtDuration(r.duration_minutes)}</div>
                    </div>
                  ))}
                  {(empRoute.pings || []).slice(0, 50).map((p, i) => (
                    <div key={p.ping_id} className="p-3 flex items-center justify-between">
                      <div className="font-mono text-xs">{fmtTime(p.timestamp)}</div>
                      <div className="font-mono text-[10px] text-muted-foreground">{p.lat.toFixed(4)}, {p.lng.toFixed(4)}</div>
                    </div>
                  ))}
                  {!selectedEmp && <div className="p-6 text-xs text-muted-foreground">No selection.</div>}
                </div>
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

const StatBlock = ({ label, value, icon, accent, testid }) => (
  <div className={`p-6 border-b lg:border-b-0 lg:border-r last:border-r-0 border-border ${accent ? "bg-secondary/30" : ""}`}>
    <div className="flex items-center justify-between">
      <span className="label-overline">{label}</span>
      <span className="text-muted-foreground">{icon}</span>
    </div>
    <div className="stat-value mt-3" data-testid={testid}>{value}</div>
  </div>
);
