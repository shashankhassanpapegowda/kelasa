import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { Clock, Copy, UsersThree } from "@phosphor-icons/react";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const inputCls = "w-full min-w-0 bg-background border border-border px-3 py-2.5 text-sm";
const STORAGE_KEY = "kelasa.timingUser";

const blankWeek = () => Object.fromEntries(DAYS.map((_, i) => [String(i), i < 5
  ? { working: true, start: "09:30", end: "18:30", break_minutes: "" }
  : { working: false, start: "", end: "", break_minutes: "" }]));

const weekFromServer = (week) => Object.fromEntries(DAYS.map((_, i) => {
  const entry = (week || {})[String(i)] || { working: false };
  return [String(i), entry.working
    ? { working: true, start: entry.start || "", end: entry.end || "", break_minutes: entry.break_minutes ?? "" }
    : { working: false, start: "", end: "", break_minutes: "" }];
}));

const payloadWeek = (week) => Object.fromEntries(DAYS.map((_, i) => {
  const day = week[String(i)];
  if (!day.working) return [String(i), { working: false }];
  const body = { working: true, start: day.start, end: day.end };
  if (day.break_minutes !== "" && day.break_minutes != null) body.break_minutes = Number(day.break_minutes);
  return [String(i), body];
}));

const errText = (e, fallback) => {
  const detail = e?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map(x => x.msg).filter(Boolean).join(", ") || fallback;
  return fallback;
};

const istStamp = (iso) => iso
  ? new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })
  : "";

export default function TimingsTab({ isAdmin, currentUserId }) {
  const [employees, setEmployees] = useState([]);
  const [org, setOrg] = useState({ departments: [], sites: [] });
  const [selectedId, setSelectedId] = useState("");
  const [grace, setGrace] = useState(10);
  const [week, setWeek] = useState(blankWeek);
  const [saved, setSaved] = useState(false);
  const [legacy, setLegacy] = useState(null);
  const [overrides, setOverrides] = useState([]);
  const [audit, setAudit] = useState([]);
  const [override, setOverride] = useState({ date: "", working: true, start: "10:00", end: "16:00", break_minutes: "" });
  const [copyIds, setCopyIds] = useState([]);
  const [copyQ, setCopyQ] = useState("");
  const [site, setSite] = useState("");
  const [department, setDepartment] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    Promise.all([api.get("/admin/employees"), api.get("/admin/org")])
      .then(([e, o]) => {
        const list = e.data.employees || [];
        setEmployees(list);
        setOrg({ departments: o.data.departments || [], sites: o.data.sites || [] });
        const wanted = sessionStorage.getItem(STORAGE_KEY);
        sessionStorage.removeItem(STORAGE_KEY);
        const pick = list.find(emp => emp.user_id === wanted) || list.find(emp => canEdit(emp, isAdmin, currentUserId));
        if (pick) setSelectedId(pick.user_id);
      })
      .catch(() => toast.error("Could not load the team"));
  }, [isAdmin, currentUserId]);

  useEffect(() => {
    if (!selectedId) return;
    let live = true;
    setLoading(true);
    api.get(`/admin/employees/${selectedId}/work-timing`).then(r => {
      if (!live) return;
      const data = r.data;
      setLegacy(data.legacy_shift || null);
      setOverrides(data.overrides || []);
      setAudit(data.audit || []);
      if (data.schedule) {
        setGrace(data.schedule.grace_minutes ?? 10);
        setWeek(weekFromServer(data.schedule.week));
        setSaved(true);
      } else {
        setGrace(10);
        setWeek(blankWeek());
        setSaved(false);
      }
    }).catch(e => { if (live) toast.error(errText(e, "Could not load timings")); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [selectedId]);

  const selected = employees.find(e => e.user_id === selectedId);
  const targets = useMemo(() => employees.filter(e => e.user_id !== selectedId && canEdit(e, isAdmin, currentUserId)), [employees, selectedId, isAdmin, currentUserId]);
  const copyList = targets.filter(e => !copyQ || `${e.name} ${e.email} ${e.site || ""}`.toLowerCase().includes(copyQ.toLowerCase()));

  const setDay = (i, patch) => setWeek(prev => ({ ...prev, [String(i)]: { ...prev[String(i)], ...patch } }));

  const reload = async (id = selectedId) => {
    const r = await api.get(`/admin/employees/${id}/work-timing`);
    setOverrides(r.data.overrides || []);
    setAudit(r.data.audit || []);
    setSaved(!!r.data.schedule);
    if (r.data.schedule) {
      setGrace(r.data.schedule.grace_minutes ?? 10);
      setWeek(weekFromServer(r.data.schedule.week));
    }
  };

  const saveWeek = async () => {
    setBusy(true);
    try {
      await api.put(`/admin/employees/${selectedId}/work-timing`, { grace_minutes: Number(grace), week: payloadWeek(week) });
      toast.success("Weekly timing saved");
      await reload();
    } catch (e) { toast.error(errText(e, "Could not save timings")); }
    finally { setBusy(false); }
  };

  const clearWeek = async () => {
    if (!window.confirm("Clear the weekly timing? One-day overrides stay. With no weekly timing, this person goes back to their existing shift.")) return;
    setBusy(true);
    try {
      await api.delete(`/admin/employees/${selectedId}/work-timing`);
      toast.success("Weekly timing cleared");
      setWeek(blankWeek());
      setGrace(10);
      setSaved(false);
      await reload();
    } catch (e) { toast.error(errText(e, "Could not clear timings")); }
    finally { setBusy(false); }
  };

  const saveOverride = async () => {
    if (!override.date) return toast.error("Pick a date");
    setBusy(true);
    try {
      const body = { working: override.working };
      if (override.working) {
        body.start = override.start;
        body.end = override.end;
        if (override.break_minutes !== "") body.break_minutes = Number(override.break_minutes);
      }
      await api.put(`/admin/employees/${selectedId}/work-timing/overrides/${override.date}`, body);
      toast.success("One-day timing saved");
      await reload();
    } catch (e) { toast.error(errText(e, "Could not save that day")); }
    finally { setBusy(false); }
  };

  const removeOverride = async (date) => {
    setBusy(true);
    try {
      await api.delete(`/admin/employees/${selectedId}/work-timing/overrides/${date}`);
      toast.success("One-day timing removed");
      await reload();
    } catch (e) { toast.error(errText(e, "Could not remove that day")); }
    finally { setBusy(false); }
  };

  const copyTo = async () => {
    if (!copyIds.length) return toast.error("Select people to copy to");
    setBusy(true);
    try {
      const r = await api.post("/admin/work-timings/copy", { from_user_id: selectedId, to_user_ids: copyIds });
      toast.success(`Copied to ${r.data.updated} ${r.data.updated === 1 ? "person" : "people"}`);
      setCopyIds([]);
    } catch (e) { toast.error(errText(e, "Could not copy timings")); }
    finally { setBusy(false); }
  };

  const applyBulk = async () => {
    if (!site && !department) return toast.error("Choose a branch, a department, or both");
    setBusy(true);
    try {
      const r = await api.post("/admin/work-timings/apply", {
        grace_minutes: Number(grace),
        week: payloadWeek(week),
        site: site || null,
        department: department || null,
      });
      const skip = (r.data.skipped || []).length;
      toast.success(`Applied to ${r.data.updated}${skip ? `, skipped ${skip}` : ""}`);
      if (selectedId) await reload();
    } catch (e) { toast.error(errText(e, "Could not apply timings")); }
    finally { setBusy(false); }
  };

  return (
    <div className="space-y-4 max-w-3xl" data-testid="timings-tab">
      <div className="border border-border bg-card p-4 space-y-3">
        <div className="flex items-center gap-2">
          <Clock size={16} weight="bold" className="text-primary"/>
          <span className="label-overline">Work timings</span>
        </div>
        <p className="text-sm text-muted-foreground">
          Set each weekday, then a different day when someone needs it. Worked hours are compared with this window. Kelasa does not record overtime.
        </p>
        <label className="block">
          <span className="label-overline mb-1.5 block">Employee</span>
          <select value={selectedId} onChange={e => { setSelectedId(e.target.value); setCopyIds([]); }} className={inputCls} data-testid="timing-employee">
            <option value="">Select someone</option>
            {employees.filter(e => canEdit(e, isAdmin, currentUserId)).map(e => (
              <option key={e.user_id} value={e.user_id}>{e.name}{e.site ? ` · ${e.site}` : ""}</option>
            ))}
          </select>
        </label>
        {selected && !loading && (
          <p className="text-xs text-muted-foreground" data-testid="timing-legacy">
            {saved ? "A weekly timing is saved. " : "No weekly timing yet. "}
            Existing shift {legacy?.start ? `${legacy.start}${legacy.end ? ` – ${legacy.end}` : ""}` : "is not set"}, and still applies on days with no timing.
          </p>
        )}
      </div>

      {selected && loading && <div className="loading-bar" data-testid="timing-loading"/>}
      {selected && !loading && (
        <>
          <section className="border border-border bg-card p-4 space-y-3" data-testid="timing-week">
            <div className="label-overline">Weekly timing</div>
            <label className="block sm:max-w-xs">
              <span className="label-overline mb-1.5 block">Late grace (minutes)</span>
              <input type="number" min="0" max="120" inputMode="numeric" value={grace}
                onChange={e => setGrace(e.target.value)} className={`${inputCls} font-mono`} data-testid="timing-grace"/>
            </label>
            <div className="space-y-2">
              {DAYS.map((name, i) => {
                const day = week[String(i)];
                return (
                  <div key={name} className="border border-border p-3 grid grid-cols-1 sm:grid-cols-[8.5rem_1fr] gap-3" data-testid={`timing-day-${i}`}>
                    <label className="flex items-center gap-2 min-h-11">
                      <input type="checkbox" checked={!!day.working} className="accent-[#0047FF] w-4 h-4"
                        onChange={e => setDay(i, { working: e.target.checked })} data-testid={`timing-working-${i}`}/>
                      <span className="text-sm font-medium">{name}</span>
                    </label>
                    {day.working ? (
                      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                        <label className="text-[11px] text-muted-foreground">Start
                          <input type="time" value={day.start} onChange={e => setDay(i, { start: e.target.value })} className={`${inputCls} font-mono mt-1`} data-testid={`timing-start-${i}`}/>
                        </label>
                        <label className="text-[11px] text-muted-foreground">End
                          <input type="time" value={day.end} onChange={e => setDay(i, { end: e.target.value })} className={`${inputCls} font-mono mt-1`} data-testid={`timing-end-${i}`}/>
                        </label>
                        <label className="text-[11px] text-muted-foreground col-span-2 sm:col-span-1">Break min
                          <input type="number" min="0" max="600" inputMode="numeric" placeholder="Optional" value={day.break_minutes}
                            onChange={e => setDay(i, { break_minutes: e.target.value })} className={`${inputCls} font-mono mt-1`} data-testid={`timing-break-${i}`}/>
                        </label>
                      </div>
                    ) : <div className="text-sm text-muted-foreground self-center">Day off</div>}
                  </div>
                );
              })}
            </div>
            <div className="flex flex-col sm:flex-row gap-2">
              <button onClick={saveWeek} disabled={busy} data-testid="timing-save"
                className="w-full sm:w-auto bg-foreground text-background px-4 py-3 text-sm hover:bg-primary disabled:opacity-50">Save weekly timing</button>
              {saved && (
                <button onClick={clearWeek} disabled={busy} data-testid="timing-clear"
                  className="w-full sm:w-auto border border-border px-4 py-3 text-sm hover:bg-secondary disabled:opacity-50">Clear weekly timing</button>
              )}
            </div>
          </section>

          <section className="border border-border bg-card p-4 space-y-3" data-testid="timing-overrides">
            <div className="label-overline">One day</div>
            <p className="text-sm text-muted-foreground">A date here replaces that weekday. Mark it off, or give it different hours.</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <label className="text-[11px] text-muted-foreground">Date
                <input type="date" value={override.date} onChange={e => setOverride(o => ({ ...o, date: e.target.value }))} className={`${inputCls} font-mono mt-1`} data-testid="override-date"/>
              </label>
              <label className="flex items-center gap-2 min-h-11 sm:mt-5 text-sm">
                <input type="checkbox" checked={override.working} className="accent-[#0047FF] w-4 h-4"
                  onChange={e => setOverride(o => ({ ...o, working: e.target.checked }))} data-testid="override-working"/>
                Working day
              </label>
              {override.working && (
                <>
                  <label className="text-[11px] text-muted-foreground">Start
                    <input type="time" value={override.start} onChange={e => setOverride(o => ({ ...o, start: e.target.value }))} className={`${inputCls} font-mono mt-1`} data-testid="override-start"/>
                  </label>
                  <label className="text-[11px] text-muted-foreground">End
                    <input type="time" value={override.end} onChange={e => setOverride(o => ({ ...o, end: e.target.value }))} className={`${inputCls} font-mono mt-1`} data-testid="override-end"/>
                  </label>
                  <label className="text-[11px] text-muted-foreground sm:col-span-2">Break min
                    <input type="number" min="0" max="600" inputMode="numeric" placeholder="Optional" value={override.break_minutes}
                      onChange={e => setOverride(o => ({ ...o, break_minutes: e.target.value }))} className={`${inputCls} font-mono mt-1 sm:max-w-xs`} data-testid="override-break"/>
                  </label>
                </>
              )}
            </div>
            <button onClick={saveOverride} disabled={busy} data-testid="timing-override-save"
              className="w-full sm:w-auto bg-foreground text-background px-4 py-3 text-sm hover:bg-primary disabled:opacity-50">Save this day</button>
            <div className="divide-y divide-border max-h-64 overflow-y-auto" data-testid="override-list">
              {overrides.map(o => (
                <div key={o.date} className="py-2.5 flex items-center justify-between gap-3 text-sm">
                  <div className="min-w-0">
                    <div className="font-mono">{o.date}</div>
                    <div className="text-xs text-muted-foreground">{o.working ? `${o.start} – ${o.end}${o.break_minutes != null ? ` · break ${o.break_minutes}m` : ""}` : "Day off"}</div>
                  </div>
                  <button onClick={() => removeOverride(o.date)} className="text-[10px] label-overline shrink-0" data-testid={`override-remove-${o.date}`}>Remove</button>
                </div>
              ))}
              {overrides.length === 0 && <div className="py-3 text-sm text-muted-foreground">No one-day timings.</div>}
            </div>
          </section>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <section className="border border-border bg-card p-4 space-y-3" data-testid="timing-copy">
              <div className="flex items-center gap-2"><Copy size={15} weight="bold"/><span className="label-overline">Copy to people</span></div>
              <p className="text-xs text-muted-foreground">Copies the saved weekly timing and grace. Each person's one-day overrides stay as they are.</p>
              <input value={copyQ} onChange={e => setCopyQ(e.target.value)} placeholder="Search" className={inputCls} data-testid="timing-copy-search"/>
              <div className="max-h-52 overflow-y-auto border border-border divide-y divide-border">
                {copyList.map(e => (
                  <label key={e.user_id} className="flex items-center gap-2 px-3 py-2.5 text-sm min-h-11">
                    <input type="checkbox" className="accent-[#0047FF] w-4 h-4" checked={copyIds.includes(e.user_id)} data-testid={`timing-copy-${e.user_id}`}
                      onChange={ev => setCopyIds(ids => ev.target.checked ? [...ids, e.user_id] : ids.filter(id => id !== e.user_id))}/>
                    <span className="min-w-0 truncate">{e.name}</span>
                  </label>
                ))}
                {copyList.length === 0 && <div className="p-3 text-sm text-muted-foreground">No one else to copy to.</div>}
              </div>
              <button onClick={copyTo} disabled={busy || !saved} data-testid="timing-copy-save"
                className="w-full border border-border px-4 py-3 text-sm hover:bg-secondary disabled:opacity-50">Copy saved timing</button>
            </section>

            <section className="border border-border bg-card p-4 space-y-3" data-testid="timing-bulk">
              <div className="flex items-center gap-2"><UsersThree size={15} weight="bold"/><span className="label-overline">Branch or team</span></div>
              <p className="text-xs text-muted-foreground">Applies the weekly timing shown above. Choose a branch, a department, or both (people in that branch and department). One-day overrides stay.</p>
              <label className="block text-[11px] text-muted-foreground">Branch
                <select value={site} onChange={e => setSite(e.target.value)} className={`${inputCls} mt-1`} data-testid="timing-bulk-branch">
                  <option value="">Any branch</option>
                  {org.sites.map(s => <option key={s.unit_id} value={s.name}>{s.name}</option>)}
                </select>
              </label>
              <label className="block text-[11px] text-muted-foreground">Department
                <select value={department} onChange={e => setDepartment(e.target.value)} className={`${inputCls} mt-1`} data-testid="timing-bulk-department">
                  <option value="">Any department</option>
                  {org.departments.map(d => <option key={d.unit_id} value={d.name}>{d.name}</option>)}
                </select>
              </label>
              <button onClick={applyBulk} disabled={busy} data-testid="timing-apply"
                className="w-full bg-foreground text-background px-4 py-3 text-sm hover:bg-primary disabled:opacity-50">Apply to branch / team</button>
            </section>
          </div>

          <section className="border border-border bg-card p-4" data-testid="timing-audit">
            <div className="label-overline mb-2">Changes</div>
            <div className="divide-y divide-border">
              {audit.map(a => (
                <div key={a.audit_id} className="py-2.5 text-sm" data-testid={`timing-audit-${a.audit_id}`}>
                  <div className="font-mono text-[11px] text-muted-foreground">{istStamp(a.created_at)} IST · {a.actor_name}</div>
                  <div className="break-words">{a.summary}</div>
                </div>
              ))}
              {audit.length === 0 && <div className="text-sm text-muted-foreground">No timing changes yet.</div>}
            </div>
          </section>
        </>
      )}
    </div>
  );
}

function canEdit(emp, isAdmin, currentUserId) {
  if (!emp) return false;
  if (isAdmin) return true;
  return emp.user_id !== currentUserId && emp.role === "employee";
}
