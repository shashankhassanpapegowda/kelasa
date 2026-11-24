import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { toast } from "sonner";
import { Plus, Trash, CalendarBlank, MapPin } from "@phosphor-icons/react";
import { today } from "@/lib/format";

const BranchPicker = ({ options, value, onChange, allowAll }) => (
  <div className="w-full flex items-center gap-1.5 flex-wrap" data-testid="holiday-branch-picker">
    <span className="label-overline mr-1">Applies to</span>
    {allowAll && (
      <button type="button" onClick={() => onChange([])} data-testid="holiday-branch-all"
        className={`px-2.5 py-1 text-xs border transition-colors ${value.length === 0 ? "bg-foreground text-background border-foreground" : "border-border hover:border-foreground"}`}>
        Whole company
      </button>
    )}
    {options.map(b => {
      const on = value.includes(b);
      return (
        <button type="button" key={b} data-testid={`holiday-branch-${b}`}
          onClick={() => onChange(on ? value.filter(x => x !== b) : [...value, b])}
          className={`px-2.5 py-1 text-xs border transition-colors ${on ? "bg-primary text-white border-primary" : "border-border hover:border-foreground"}`}>
          {b}
        </button>
      );
    })}
    {!allowAll && options.length === 0 && <span className="text-xs text-muted-foreground">No branches assigned to you yet — ask an admin.</span>}
  </div>
);

export default function CalendarTab() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [year, setYear] = useState(new Date().getFullYear());
  const [holidays, setHolidays] = useState([]);
  const [branchOptions, setBranchOptions] = useState(isAdmin ? [] : (user?.managed_sites || []));
  const [form, setForm] = useState({ date: today(), name: "", branches: [] });
  const latest = useRef(year);

  const load = async (y) => {
    latest.current = y;
    try {
      const list = (await api.get(`/holidays?year=${y}`)).data.holidays || [];
      if (latest.current === y) setHolidays(list);
    } catch { toast.error("Failed to load calendar"); }
  };
  useEffect(() => { load(year); }, [year]);
  useEffect(() => {
    if (isAdmin) api.get("/admin/org").then(r => setBranchOptions((r.data.sites || []).map(s => s.name))).catch(() => {});
  }, [isAdmin]);

  const add = async () => {
    if (!form.name.trim()) return toast.error("Give the holiday a name");
    if (!isAdmin && form.branches.length === 0) return toast.error("Pick at least one of your branches");
    try {
      await api.post("/admin/holidays", form);
      toast.success(`${form.name} added`);
      setForm({ date: today(), name: "", branches: [] });
      load(year);
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not add"); }
  };

  const remove = async (h) => {
    if (!window.confirm(`Remove ${h.name}?`)) return;
    try { await api.delete(`/admin/holidays/${h.holiday_id}`); toast.success("Removed"); load(year); }
    catch (e) { toast.error(e?.response?.data?.detail || "Could not remove"); }
  };

  const fmt = (d) => new Date(`${d}T00:00:00`).toLocaleDateString([], { weekday: "short", day: "2-digit", month: "long" });

  return (
    <div className="border border-border bg-card max-w-3xl" data-testid="calendar-tab">
      <div className="p-4 border-b border-border flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <CalendarBlank size={16} weight="bold" className="text-primary"/>
          <span className="label-overline">Holiday Calendar</span>
        </div>
        <div className="flex items-center gap-2">
          <select value={year} onChange={e => setYear(Number(e.target.value))} data-testid="holiday-year"
            className="bg-background border border-border px-2 py-1.5 text-sm font-mono">
            {[year - 1, year, year + 1].map(y => <option key={y} value={y}>{y}</option>)}
          </select>
          <span className="font-mono text-xs text-muted-foreground">{holidays.length} DAYS</span>
        </div>
      </div>

      <div className="p-4 border-b border-border flex items-center gap-2 flex-wrap">
        <input type="date" value={form.date} onChange={e => setForm({ ...form, date: e.target.value })} data-testid="holiday-date"
          className="bg-background border border-border px-3 py-2 text-sm font-mono"/>
        <input value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} onKeyDown={e => e.key === "Enter" && add()}
          placeholder="Holiday name e.g. Ugadi" data-testid="holiday-name"
          className="flex-1 min-w-[180px] bg-background border border-border px-3 py-2 text-sm"/>
        <button onClick={add} data-testid="add-holiday-btn"
          className="bg-foreground text-background px-3 py-2 hover:bg-primary transition-colors inline-flex items-center gap-1.5 text-sm">
          <Plus size={15} weight="bold"/> Add
        </button>
        <BranchPicker options={branchOptions} value={form.branches} allowAll={isAdmin}
          onChange={(branches) => setForm({ ...form, branches })}/>
      </div>

      <div className="divide-y divide-border max-h-[520px] overflow-y-auto" data-testid="holiday-list">
        {holidays.map(h => (
          <div key={h.holiday_id} className="p-4 flex items-center gap-3" data-testid={`holiday-${h.holiday_id}`}>
            <div className="font-mono text-xs text-muted-foreground w-44 shrink-0">{fmt(h.date)}</div>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium">{h.name}</div>
              <div className="text-xs text-muted-foreground inline-flex items-center gap-1 mt-0.5" data-testid={`holiday-scope-${h.holiday_id}`}>
                <MapPin size={11} weight="bold"/> {h.branches?.length ? h.branches.join(", ") : "Whole company"}
              </div>
            </div>
            {h.can_edit && (
              <button onClick={() => remove(h)} className="text-muted-foreground hover:text-[#FF3B30]" data-testid={`delete-holiday-${h.holiday_id}`}>
                <Trash size={14} weight="bold"/>
              </button>
            )}
          </div>
        ))}
        {holidays.length === 0 && <div className="p-8 text-sm text-muted-foreground text-center">No holidays declared for {year}.</div>}
      </div>
      <div className="p-3 border-t border-border text-xs text-muted-foreground">
        Holidays are never counted as absent days. Branch holidays apply only to staff whose home branch is listed.
        {!isAdmin && " You can add and remove holidays for your own branches."}
      </div>
    </div>
  );
}
