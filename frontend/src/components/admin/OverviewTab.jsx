import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import AuthPhoto from "@/components/AuthPhoto";
import PhotoModal from "@/components/admin/PhotoModal";
import { fmtTime, fmtDuration, fmtAcc, accClass, fmtDay, today } from "@/lib/format";
import { Users, Pulse, Clock, CheckSquare, WarningCircle, AirplaneTilt, Hourglass } from "@phosphor-icons/react";
import { AreaChart, Area, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";

const RANGES = [7, 14, 30];

export default function OverviewTab() {
  const [stats, setStats] = useState(null);
  const [analytics, setAnalytics] = useState(null);
  const [range, setRange] = useState(14);
  const [date, setDate] = useState(today());
  const [attendance, setAttendance] = useState([]);
  const [photoModal, setPhotoModal] = useState(null);

  useEffect(() => {
    api.get("/admin/stats").then(r => setStats(r.data)).catch(() => toast.error("Failed to load stats"));
  }, []);

  useEffect(() => {
    api.get(`/admin/analytics?days=${range}`).then(r => setAnalytics(r.data)).catch(() => {});
  }, [range]);

  useEffect(() => {
    api.get(`/admin/attendance?date=${date}`).then(r => setAttendance(r.data.records || [])).catch(() => {});
  }, [date]);

  const daily = (analytics?.daily || []).map(d => ({ ...d, label: fmtDay(d.date) }));

  return (
    <div data-testid="overview-tab">
      <div className="grid grid-cols-2 lg:grid-cols-4 xl:grid-cols-7 gap-0 border border-border bg-card">
        <Stat label="Headcount" value={stats?.total_employees ?? "—"} icon={<Users size={18} weight="bold"/>} testid="stat-employees"/>
        <Stat label="On Duty Now" value={stats?.on_duty ?? "—"} icon={<Pulse size={18} weight="bold"/>} accent testid="stat-on-duty"/>
        <Stat label="Check-ins" value={stats?.today_checkins ?? "—"} icon={<CheckSquare size={18} weight="bold"/>} testid="stat-checkins"/>
        <Stat label="Late Today" value={stats?.late_today ?? "—"} icon={<WarningCircle size={18} weight="bold"/>} testid="stat-late"/>
        <Stat label="On Leave" value={stats?.on_leave_today ?? "—"} icon={<AirplaneTilt size={18} weight="bold"/>} testid="stat-on-leave"/>
        <Stat label="Leave Pending" value={stats?.pending_leave ?? "—"} icon={<Hourglass size={18} weight="bold"/>} testid="stat-pending-leave"/>
        <Stat label="Work Hrs Today" value={fmtDuration(stats?.total_work_minutes_today)} icon={<Clock size={18} weight="bold"/>} testid="stat-workhours"/>
      </div>

      <div className="mt-6 border border-border bg-card" data-testid="attendance-trend">
        <div className="p-4 border-b border-border flex items-center justify-between flex-wrap gap-2">
          <span className="label-overline">Attendance Trend</span>
          <div className="flex items-center gap-1">
            {RANGES.map(r => (
              <button key={r} onClick={() => setRange(r)} data-testid={`range-${r}`}
                className={`text-[10px] label-overline border px-2 py-1 ${range === r ? "bg-foreground text-background border-foreground" : "border-border hover:border-foreground"}`}>
                {r}D
              </button>
            ))}
          </div>
        </div>
        <div className="h-[260px] p-4">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={daily} margin={{ top: 8, right: 8, left: -24, bottom: 0 }}>
              <defs>
                <linearGradient id="gPresent" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#00E676" stopOpacity={0.55}/>
                  <stop offset="100%" stopColor="#00E676" stopOpacity={0.02}/>
                </linearGradient>
              </defs>
              <CartesianGrid stroke="currentColor" strokeOpacity={0.08} vertical={false}/>
              <XAxis dataKey="label" tick={{ fontSize: 10, fontFamily: "monospace" }} tickLine={false} axisLine={false} interval="preserveStartEnd"/>
              <YAxis tick={{ fontSize: 10, fontFamily: "monospace" }} tickLine={false} axisLine={false} allowDecimals={false}/>
              <Tooltip contentStyle={{ fontSize: 12, border: "1px solid var(--border)", borderRadius: 0, background: "var(--card)" }}/>
              <Area type="monotone" dataKey="present" stroke="#00E676" strokeWidth={2} fill="url(#gPresent)" name="Present"/>
              <Area type="monotone" dataKey="late" stroke="#FF3B30" strokeWidth={1.5} fillOpacity={0} name="Late"/>
              <Area type="monotone" dataKey="on_leave" stroke="#0047FF" strokeWidth={1.5} fillOpacity={0} name="On leave"/>
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="mt-6 grid lg:grid-cols-2 gap-0 border border-border bg-card">
        <div className="lg:border-r border-border border-b lg:border-b-0">
          <div className="p-4 border-b border-border"><span className="label-overline">Leave Days by Type · {range}D</span></div>
          <div className="h-[220px] p-4" data-testid="leave-by-type-chart">
            {(analytics?.leave_by_type || []).length === 0 ? (
              <div className="h-full grid place-items-center text-sm text-muted-foreground">No approved leave in this window.</div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={analytics.leave_by_type} margin={{ top: 8, right: 8, left: -24, bottom: 0 }}>
                  <CartesianGrid stroke="currentColor" strokeOpacity={0.08} vertical={false}/>
                  <XAxis dataKey="name" tick={{ fontSize: 10 }} tickLine={false} axisLine={false}/>
                  <YAxis tick={{ fontSize: 10, fontFamily: "monospace" }} tickLine={false} axisLine={false}/>
                  <Tooltip cursor={{ fillOpacity: 0.06 }} contentStyle={{ fontSize: 12, borderRadius: 0 }}/>
                  <Bar dataKey="days" fill="#0047FF" name="Days"/>
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>
        <div>
          <div className="p-4 border-b border-border"><span className="label-overline">Headcount by Department</span></div>
          <div className="divide-y divide-border max-h-[220px] overflow-y-auto" data-testid="dept-breakdown">
            {(analytics?.departments || []).map(d => (
              <div key={d.name} className="p-3 flex items-center justify-between">
                <span className="text-sm">{d.name}</span>
                <span className="font-mono text-sm">{d.count}</span>
              </div>
            ))}
            {(analytics?.departments || []).length === 0 && <div className="p-6 text-sm text-muted-foreground">No employees yet.</div>}
          </div>
        </div>
      </div>

      <div className="mt-6 border border-border bg-card">
        <div className="p-4 flex items-center justify-between border-b border-border flex-wrap gap-2">
          <span className="label-overline">Attendance Log</span>
          <div className="flex items-center gap-3">
            <input type="date" value={date} onChange={e => setDate(e.target.value)} data-testid="date-filter"
              className="bg-background border border-border px-3 py-1.5 text-sm font-mono"/>
            <span className="font-mono text-xs text-muted-foreground">{attendance.length} SESSIONS</span>
          </div>
        </div>
        <div className="max-h-[520px] overflow-y-auto" data-testid="attendance-log">
          <table className="w-full text-sm">
            <thead className="text-[10px] label-overline">
              <tr className="border-b border-border">
                <th className="text-left p-3">Employee</th>
                <th className="text-left p-3">In / Out</th>
                <th className="text-left p-3">Photos</th>
                <th className="text-right p-3">Net</th>
              </tr>
            </thead>
            <tbody>
              {attendance.map(r => (
                <tr key={r.record_id} className="border-b border-border hover:bg-secondary/40">
                  <td className="p-3">
                    <div className="font-medium">{r.name || r.user_id}</div>
                    <div className="text-xs text-muted-foreground">{r.email}</div>
                    <div className="text-[10px] font-mono text-muted-foreground mt-0.5">
                      Shift {r.shift_start || "—"}{r.shift_end ? ` – ${r.shift_end}` : ""}
                    </div>
                  </td>
                  <td className="p-3 font-mono text-xs">
                    <div className="flex items-center gap-1.5">
                      <span>{fmtTime(r.check_in)}</span>
                      {r.late_by_minutes > 0 && <span className="text-[9px] uppercase bg-[#FF3B30]/15 text-[#FF3B30] px-1">+{r.late_by_minutes}m</span>}
                    </div>
                    <div className={`text-[10px] ${accClass(r.check_in_accuracy)}`}>{fmtAcc(r.check_in_accuracy)}</div>
                    <div className="mt-1">{r.check_out ? fmtTime(r.check_out) : <span className="text-[#00E676]">live</span>}</div>
                    {r.total_break_minutes > 0 && (
                      <div className="text-[10px] text-muted-foreground mt-0.5">
                        brk {r.total_break_minutes}m {r.over_break && <span className="text-yellow-700">(over)</span>}
                      </div>
                    )}
                  </td>
                  <td className="p-3">
                    <div className="flex items-center gap-1.5">
                      {r.check_in_photo_path && (
                        <button onClick={() => setPhotoModal({ path: r.check_in_photo_path, label: "Check-In", record: r, kind: "in" })}
                          className="border border-border hover:border-primary" data-testid={`photo-in-${r.record_id}`}>
                          <AuthPhoto path={r.check_in_photo_path} className="w-9 h-9 object-cover" fallback={<div className="w-9 h-9 bg-secondary"/>}/>
                        </button>
                      )}
                      {r.check_out_photo_path && (
                        <button onClick={() => setPhotoModal({ path: r.check_out_photo_path, label: "Check-Out", record: r, kind: "out" })}
                          className="border border-border hover:border-primary" data-testid={`photo-out-${r.record_id}`}>
                          <AuthPhoto path={r.check_out_photo_path} className="w-9 h-9 object-cover" fallback={<div className="w-9 h-9 bg-secondary"/>}/>
                        </button>
                      )}
                      {!r.check_in_photo_path && !r.check_out_photo_path && <span className="text-xs text-muted-foreground">—</span>}
                    </div>
                  </td>
                  <td className="p-3 font-mono text-right">{fmtDuration(r.net_work_minutes ?? r.duration_minutes)}</td>
                </tr>
              ))}
              {attendance.length === 0 && (
                <tr><td colSpan={4} className="p-6 text-center text-muted-foreground">No sessions on this date.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <PhotoModal data={photoModal} onClose={() => setPhotoModal(null)}/>
    </div>
  );
}

const Stat = ({ label, value, icon, accent, testid }) => (
  <div className={`p-5 border-b xl:border-b-0 border-r last:border-r-0 border-border ${accent ? "bg-secondary/30" : ""}`}>
    <div className="flex items-center justify-between gap-2">
      <span className="label-overline">{label}</span>
      <span className="text-muted-foreground">{icon}</span>
    </div>
    <div className="stat-value mt-3" data-testid={testid}>{value}</div>
  </div>
);
