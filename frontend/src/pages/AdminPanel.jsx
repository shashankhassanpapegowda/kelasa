import { useEffect, useState } from "react";
import AppHeader from "@/components/AppHeader";
import MapView from "@/components/MapView";
import AuthPhoto from "@/components/AuthPhoto";
import { api, API } from "@/lib/api";
import { toast } from "sonner";
import { Users, Pulse, Clock, CheckSquare, ArrowsClockwise, Path as PathIcon, X, ArrowSquareOut, GpsFix, Clock as ClockIcon, WarningCircle, PencilSimple } from "@phosphor-icons/react";

const fmtTime = (iso) => iso ? new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : "—";
const fmtDuration = (mins) => {
  if (mins == null) return "—";
  const h = Math.floor(mins / 60); const m = mins % 60;
  return `${h}h ${m}m`;
};
const fmtAcc = (m) => {
  if (m == null) return "";
  if (m < 1000) return `±${Math.round(m)}m`;
  return `±${(m/1000).toFixed(1)}km`;
};
const accClass = (m) => {
  if (m == null) return "text-muted-foreground";
  if (m > 200) return "text-[#FF3B30]";
  if (m > 100) return "text-yellow-600";
  return "text-[#00E676]";
};

export default function AdminPanel() {
  const [stats, setStats] = useState(null);
  const [employees, setEmployees] = useState([]);
  const [attendance, setAttendance] = useState([]);
  const [date, setDate] = useState(new Date().toISOString().slice(0,10));
  const [selectedEmp, setSelectedEmp] = useState(null);
  const [empRoute, setEmpRoute] = useState({ pings: [], attendance: [], employee: null });
  const [loading, setLoading] = useState(false);
  const [photoModal, setPhotoModal] = useState(null);
  const [shiftEditor, setShiftEditor] = useState(null);

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
    } catch {
      toast.error("Failed to load admin data");
    } finally { setLoading(false); }
  };

  useEffect(() => { refresh(); }, [date]);

  const openEmp = async (emp) => {
    setSelectedEmp(emp);
    try {
      const res = await api.get(`/admin/employees/${emp.user_id}/route?date=${date}`);
      setEmpRoute(res.data);
    } catch { setEmpRoute({ pings: [], attendance: [], employee: emp }); }
  };

  const toggleRole = async (emp) => {
    const newRole = emp.role === "admin" ? "employee" : "admin";
    try {
      await api.patch(`/admin/employees/${emp.user_id}/role`, { role: newRole });
      toast.success(`${emp.name} → ${newRole}`);
      refresh();
    } catch (e) { toast.error(e?.response?.data?.detail || "Update failed"); }
  };

  const resetFace = async (emp) => {
    if (!confirm(`Reset face enrollment for ${emp.name}? They'll need to re-enrol.`)) return;
    try {
      await api.delete(`/admin/employees/${emp.user_id}/face`);
      toast.success("Face enrollment reset");
      refresh();
    } catch { toast.error("Reset failed"); }
  };

  const toggleTrackingMode = async (emp) => {
    const next = emp.tracking_mode === "always_on" ? "duty_only" : "always_on";
    if (next === "always_on" && !confirm(`Enable 24/7 ALWAYS-ON tracking for ${emp.name}?\n\nThis tracks location whenever they are signed in, NOT just during their shift. Make sure you have written employee consent — Indian privacy law requires it.`)) return;
    try {
      await api.patch(`/admin/employees/${emp.user_id}/tracking_mode`, { tracking_mode: next });
      toast.success(`${emp.name} → ${next === "always_on" ? "24/7 tracking" : "duty-only tracking"}`);
      refresh();
    } catch (e) { toast.error(e?.response?.data?.detail || "Update failed"); }
  };

  const saveShift = async (form) => {
    try {
      await api.patch(`/admin/employees/${shiftEditor.user_id}/shift`, form);
      toast.success(`Shift updated for ${shiftEditor.name}`);
      setShiftEditor(null);
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
              <input type="date" value={date} onChange={e => setDate(e.target.value)} data-testid="date-filter"
                className="bg-card border border-border px-3 py-2 text-sm font-mono"/>
              <button onClick={refresh} className="text-xs label-overline flex items-center gap-2 hover:text-foreground" data-testid="admin-refresh">
                <ArrowsClockwise size={14} weight="bold"/> Refresh
              </button>
            </div>
          </div>

          <div className="mt-6 grid grid-cols-2 lg:grid-cols-5 gap-0 border border-border bg-card">
            <StatBlock label="Employees" value={stats?.total_employees ?? "—"} icon={<Users size={18} weight="bold"/>} testid="stat-employees"/>
            <StatBlock label="On Duty Now" value={stats?.on_duty ?? "—"} icon={<Pulse size={18} weight="bold"/>} accent testid="stat-on-duty"/>
            <StatBlock label="Today Check-ins" value={stats?.today_checkins ?? "—"} icon={<CheckSquare size={18} weight="bold"/>} testid="stat-checkins"/>
            <StatBlock label="Late Today" value={stats?.late_today ?? "—"} icon={<WarningCircle size={18} weight="bold"/>} testid="stat-late"/>
            <StatBlock label="Work Hrs Today" value={fmtDuration(stats?.total_work_minutes_today)} icon={<Clock size={18} weight="bold"/>} testid="stat-workhours"/>
          </div>
          {loading && <div className="loading-bar mt-2"/>}

          <div className="mt-6 grid lg:grid-cols-2 gap-0 border border-border bg-card">
            <div className="lg:border-r border-border border-b lg:border-b-0">
              <div className="p-4 flex items-center justify-between border-b border-border">
                <span className="label-overline">Employees · Shift Mapping</span>
                <span className="font-mono text-xs text-muted-foreground">{employees.length} TOTAL</span>
              </div>
              <div className="divide-y divide-border max-h-[520px] overflow-y-auto" data-testid="employees-list">
                {employees.map(emp => (
                  <div key={emp.user_id} className="p-4 flex items-center gap-3 hover:bg-secondary/40 cursor-pointer" onClick={() => openEmp(emp)} data-testid={`emp-row-${emp.user_id}`}>
                    <AuthPhoto path={emp.face_photo_path} className="w-10 h-10 rounded-full object-cover border border-border"
                      fallback={emp.picture
                        ? <img src={emp.picture} className="w-10 h-10 rounded-full border border-border" alt=""/>
                        : <div className="w-10 h-10 rounded-full bg-secondary grid place-items-center text-sm font-medium">{emp.name?.[0]}</div>
                      }/>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-medium truncate">{emp.name}</span>
                        {emp.is_on_duty && !emp.on_break && <span className="text-[10px] font-mono uppercase tracking-wider bg-[#00E676] text-black px-1.5 py-0.5">ON DUTY</span>}
                        {emp.on_break && <span className="text-[10px] font-mono uppercase tracking-wider bg-yellow-400 text-black px-1.5 py-0.5">ON BREAK</span>}
                        {emp.role === "admin" && <span className="text-[10px] font-mono uppercase tracking-wider border border-border px-1.5 py-0.5">ADMIN</span>}
                        {emp.tracking_mode === "always_on" && <span className="text-[10px] font-mono uppercase tracking-wider bg-[#0047FF] text-white px-1.5 py-0.5">24/7</span>}
                        {!emp.face_enrolled && <span className="text-[10px] font-mono uppercase tracking-wider bg-yellow-500/20 text-yellow-700 px-1.5 py-0.5">NOT ENROLLED</span>}
                      </div>
                      <div className="text-xs text-muted-foreground truncate">{emp.email}</div>
                      <div className="text-[10px] font-mono text-muted-foreground mt-1 flex items-center gap-1.5">
                        <ClockIcon size={11} weight="bold"/>
                        {emp.shift_start ? `${emp.shift_start}${emp.shift_end ? ` – ${emp.shift_end}` : ""}` : <span className="italic text-yellow-700">No shift set</span>}
                        <span className="mx-1">·</span>
                        <span>Break {emp.break_max_minutes ?? 60}m</span>
                      </div>
                    </div>
                    <div className="text-right shrink-0">
                      <div className="font-mono text-sm">{fmtDuration(emp.today_minutes)}</div>
                      <div className="flex items-center gap-2 mt-0.5 justify-end flex-wrap">
                        <button onClick={(e) => { e.stopPropagation(); setShiftEditor(emp); }} className="text-[10px] label-overline hover:text-primary inline-flex items-center gap-1" data-testid={`edit-shift-${emp.user_id}`}>
                          <PencilSimple size={10} weight="bold"/> SHIFT
                        </button>
                        <button onClick={(e) => { e.stopPropagation(); toggleRole(emp); }} className="text-[10px] label-overline hover:text-primary" data-testid={`toggle-role-${emp.user_id}`}>
                          {emp.role === "admin" ? "→ EMP" : "→ ADMIN"}
                        </button>
                        <button onClick={(e) => { e.stopPropagation(); toggleTrackingMode(emp); }} className="text-[10px] label-overline hover:text-primary" data-testid={`toggle-tracking-${emp.user_id}`}>
                          {emp.tracking_mode === "always_on" ? "→ DUTY ONLY" : "→ 24/7"}
                        </button>
                        {emp.face_enrolled && (
                          <button onClick={(e) => { e.stopPropagation(); resetFace(emp); }} className="text-[10px] label-overline hover:text-[#FF3B30]" data-testid={`reset-face-${emp.user_id}`}>
                            RESET FACE
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
                {employees.length === 0 && <div className="p-6 text-sm text-muted-foreground">No employees yet.</div>}
              </div>
            </div>

            <div>
              <div className="p-4 flex items-center justify-between border-b border-border">
                <span className="label-overline">Attendance Log · {date}</span>
                <span className="font-mono text-xs text-muted-foreground">{attendance.length} SESSIONS</span>
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
                          <div className="mt-1">
                            {r.check_out ? fmtTime(r.check_out) : <span className="text-[#00E676]">live</span>}
                          </div>
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
          </div>

          <div className="mt-6 border border-border bg-card">
            <div className="p-4 flex items-center justify-between border-b border-border">
              <div className="flex items-center gap-2">
                <PathIcon size={16} weight="bold" className="text-primary"/>
                <span className="label-overline">Route Inspector</span>
                {selectedEmp && <span className="text-sm font-medium ml-2" data-testid="selected-emp">{selectedEmp.name}</span>}
              </div>
              <span className="font-mono text-xs text-muted-foreground">{empRoute.pings?.length || 0} POINTS</span>
            </div>
            <div className="grid lg:grid-cols-3">
              <div className="lg:col-span-2 h-[460px] border-b lg:border-b-0 lg:border-r border-border">
                {!selectedEmp ? (
                  <div className="h-full grid place-items-center text-sm text-muted-foreground p-6 text-center">Select an employee to inspect their day's route.</div>
                ) : empRoute.pings?.length === 0 ? (
                  <div className="h-full grid place-items-center text-sm text-muted-foreground p-6 text-center">No location pings for this employee on {date}.</div>
                ) : <MapView pings={empRoute.pings}/>}
              </div>
              <div className="max-h-[460px] overflow-y-auto" data-testid="timeline">
                <div className="p-4 border-b border-border"><span className="label-overline">Timeline</span></div>
                <div className="divide-y divide-border">
                  {(empRoute.attendance || []).map(r => (
                    <div key={r.record_id} className="p-4">
                      <div className="flex items-center gap-2 mb-2">
                        {r.check_in_photo_path && (
                          <button onClick={() => setPhotoModal({ path: r.check_in_photo_path, label: "Check-In", record: r, kind: "in" })}>
                            <AuthPhoto path={r.check_in_photo_path} className="w-10 h-10 object-cover border border-border" fallback={<div className="w-10 h-10 bg-secondary"/>}/>
                          </button>
                        )}
                        {r.check_out_photo_path && (
                          <button onClick={() => setPhotoModal({ path: r.check_out_photo_path, label: "Check-Out", record: r, kind: "out" })}>
                            <AuthPhoto path={r.check_out_photo_path} className="w-10 h-10 object-cover border border-border" fallback={<div className="w-10 h-10 bg-secondary"/>}/>
                          </button>
                        )}
                      </div>
                      <div className="text-xs label-overline mb-1">Session</div>
                      <div className="font-mono text-sm">{fmtTime(r.check_in)} → {r.check_out ? fmtTime(r.check_out) : "live"}</div>
                      <div className="text-xs text-muted-foreground mt-1">{fmtDuration(r.net_work_minutes ?? r.duration_minutes)} net · {r.total_break_minutes || 0}m break {r.late_by_minutes > 0 && <span className="text-[#FF3B30]">· {r.late_by_minutes}m late</span>}</div>
                      {(r.breaks || []).length > 0 && (
                        <div className="mt-2 space-y-1">
                          {r.breaks.map(b => (
                            <div key={b.break_id} className="text-[10px] font-mono text-muted-foreground flex items-center gap-2 pl-2 border-l-2 border-yellow-400">
                              <span>{fmtTime(b.start)} → {b.end ? fmtTime(b.end) : "ongoing"}</span>
                              {b.duration_minutes != null && <span>· {b.duration_minutes}m</span>}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                  {(empRoute.pings || []).slice(0, 50).map((p) => (
                    <div key={p.ping_id} className="p-3 flex items-center justify-between">
                      <div>
                        <div className="font-mono text-xs">{fmtTime(p.timestamp)}</div>
                        <div className={`font-mono text-[10px] ${accClass(p.accuracy)}`}><GpsFix size={10} className="inline mr-0.5"/>{fmtAcc(p.accuracy)}</div>
                      </div>
                      <div className="font-mono text-[10px] text-muted-foreground">{p.lat.toFixed(5)}, {p.lng.toFixed(5)}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </main>

      {/* Shift Editor Modal */}
      {shiftEditor && (
        <ShiftEditorModal emp={shiftEditor} onClose={() => setShiftEditor(null)} onSave={saveShift}/>
      )}

      {/* Photo Modal */}
      {photoModal && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm grid place-items-center p-4" onClick={() => setPhotoModal(null)} data-testid="photo-modal">
          <div className="bg-card border border-border max-w-lg w-full" onClick={(e) => e.stopPropagation()}>
            <div className="p-4 border-b border-border flex items-center justify-between">
              <div>
                <div className="label-overline">{photoModal.label} Photo</div>
                <div className="font-semibold tracking-tight mt-0.5">{photoModal.record.name}</div>
              </div>
              <button onClick={() => setPhotoModal(null)} className="p-1 hover:bg-secondary"><X size={18} weight="bold"/></button>
            </div>
            <AuthPhoto path={photoModal.path} className="w-full aspect-[4/3] object-cover bg-black" fallback={<div className="w-full aspect-[4/3] bg-secondary"/>}/>
            <div className="p-4 grid grid-cols-2 gap-3 text-sm">
              <div>
                <div className="label-overline mb-1">Timestamp</div>
                <div className="font-mono">{photoModal.kind === "in" ? fmtTime(photoModal.record.check_in) : fmtTime(photoModal.record.check_out)}</div>
              </div>
              <div>
                <div className="label-overline mb-1">Face Match</div>
                <div className="font-mono">{photoModal.kind === "in" ? photoModal.record.check_in_face_distance : photoModal.record.check_out_face_distance ?? "—"}</div>
              </div>
              <div>
                <div className="label-overline mb-1">Location</div>
                <div className="font-mono text-xs">
                  {photoModal.kind === "in"
                    ? `${photoModal.record.check_in_lat?.toFixed(5)}, ${photoModal.record.check_in_lng?.toFixed(5)}`
                    : `${photoModal.record.check_out_lat?.toFixed(5)}, ${photoModal.record.check_out_lng?.toFixed(5)}`}
                </div>
                <a href={`https://www.openstreetmap.org/?mlat=${photoModal.kind === "in" ? photoModal.record.check_in_lat : photoModal.record.check_out_lat}&mlon=${photoModal.kind === "in" ? photoModal.record.check_in_lng : photoModal.record.check_out_lng}#map=18`}
                   target="_blank" rel="noreferrer" className="text-[10px] label-overline text-primary hover:underline inline-flex items-center gap-1 mt-1">
                  <ArrowSquareOut size={10}/> Open in map
                </a>
              </div>
              <div>
                <div className="label-overline mb-1">GPS Accuracy</div>
                <div className={`font-mono text-xs ${accClass(photoModal.kind === "in" ? photoModal.record.check_in_accuracy : photoModal.record.check_out_accuracy)}`}>
                  {fmtAcc(photoModal.kind === "in" ? photoModal.record.check_in_accuracy : photoModal.record.check_out_accuracy)}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ShiftEditorModal({ emp, onClose, onSave }) {
  const [shiftStart, setShiftStart] = useState(emp.shift_start || "");
  const [shiftEnd, setShiftEnd] = useState(emp.shift_end || "");
  const [breakMax, setBreakMax] = useState(emp.break_max_minutes ?? 60);
  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm grid place-items-center p-4" onClick={onClose} data-testid="shift-modal">
      <div className="bg-card border border-border max-w-md w-full" onClick={(e) => e.stopPropagation()}>
        <div className="p-4 border-b border-border flex items-center justify-between">
          <div>
            <div className="label-overline">Map Shift Timing</div>
            <div className="font-semibold tracking-tight mt-0.5">{emp.name}</div>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-secondary"><X size={18} weight="bold"/></button>
        </div>
        <div className="p-5 space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label-overline mb-1.5 block">Shift Start</label>
              <input type="time" value={shiftStart} onChange={(e) => setShiftStart(e.target.value)}
                className="w-full bg-background border border-border px-3 py-2 font-mono text-sm" data-testid="shift-start-input"/>
            </div>
            <div>
              <label className="label-overline mb-1.5 block">Shift End</label>
              <input type="time" value={shiftEnd} onChange={(e) => setShiftEnd(e.target.value)}
                className="w-full bg-background border border-border px-3 py-2 font-mono text-sm" data-testid="shift-end-input"/>
            </div>
          </div>
          <div>
            <label className="label-overline mb-1.5 block">Break Limit (minutes)</label>
            <input type="number" min="0" max="600" value={breakMax} onChange={(e) => setBreakMax(parseInt(e.target.value || "0", 10))}
              className="w-full bg-background border border-border px-3 py-2 font-mono text-sm" data-testid="break-max-input"/>
            <p className="text-[10px] text-muted-foreground mt-1">Anything above this is flagged as "over-break" in reports. 15-min grace on late detection.</p>
          </div>
          <div className="flex items-center gap-2 pt-2">
            <button onClick={() => onSave({ shift_start: shiftStart, shift_end: shiftEnd, break_max_minutes: breakMax })}
              data-testid="save-shift-btn"
              className="flex-1 bg-foreground text-background px-4 py-3 hover:bg-primary transition-colors">
              <span className="font-medium">Save Mapping</span>
            </button>
            <button onClick={onClose} className="border border-border px-4 py-3 hover:bg-secondary">Cancel</button>
          </div>
        </div>
      </div>
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
