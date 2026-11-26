import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { ClockCounterClockwise, MagnifyingGlass, CaretLeft, CaretRight } from "@phosphor-icons/react";

const VERB = {
  employee_added: "Added employee {t}",
  employee_removed: "Removed employee {t}",
  employee_assigned: "Updated {t}'s details",
  shift_updated: "Changed {t}'s shift",
  work_timing_updated: "Updated work timings for {t}",
  work_timing_cleared: "Cleared the weekly timing for {t}",
  work_timing_override: "Set a one-day timing for {t}",
  work_timing_override_cleared: "Removed a one-day timing for {t}",
  work_timing_copied: "Copied work timings to {t}",
  role_changed: "Changed {t}'s access level",
  scope_updated: "Updated which teams {t} manages",
  leave_approved: "Approved leave for {t}",
  leave_rejected: "Rejected leave for {t}",
  leave_type_added: "Added leave type {t}",
  password_set: "Set a password for {t}",
  site_added: "Added branch {t}",
  site_removed: "Removed branch {t}",
  branch_updated: "Updated the location of branch {t}",
  field_staff_changed: "Changed field-staff access for {t}",
  geofence_settings: "Changed leaving-area alert timing",
  bank_approved: "Approved bank details for {t}",
  bank_rejected: "Rejected bank details for {t}",
  bank_change_requested: "Submitted new bank details",
  profile_updated: "Updated profile of {t}",
  payroll_export: "Downloaded payroll details",
  payroll_generated: "Generated a draft payroll for {t}",
  payroll_settings_saved: "Saved payroll settings for {t}",
  payroll_settings_copied: "Copied payroll settings to {t}",
  salary_structure_saved: "Saved a salary structure for {t}",
  salary_structures_imported: "Created salary structures for {t}",
  payroll_ndp_override: "Changed days paid for {t}",
  payroll_adjustment: "Updated deductions and additions for {t}",
  payroll_approved: "Approved payroll for {t}",
  payroll_published: "Published payroll for {t}",
  payroll_revised: "Revised payroll for {t}",
  payroll_notified: "Re-sent payslip notifications for {t}",
  payroll_ndp_refreshed: "Refreshed days paid for {t}",
  payroll_exported: "Downloaded a payroll export for {t}",
  payroll_imported: "Imported a past payroll for {t}",
  payslip_downloaded: "Downloaded a payslip for {t}",
  payslips_zip: "Downloaded a payslip bundle for {t}",
  payslip_template_saved: "Saved the payslip template for {t}",
  payroll_recurring_added: "Added a recurring deduction or addition for {t}",
  payroll_recurring_ended: "Stopped a recurring deduction or addition",
  payslip_query: "{t} raised a payslip query",
  payslip_query_replied: "Replied to a payslip query from {t}",
  holiday_added: "Added holiday {t}",
  face_reset: "Reset the face enrolment of {t}",
  face_blocked: "Blocked a check-in by {t} — the face looked like another employee",
  face_enroll_blocked: "Blocked a face enrolment by {t} — already enrolled for another employee",
  face_review_ok: "Confirmed the face check of {t}",
  face_review_mismatch: "Marked the face check of {t} as NOT the same person",
  holiday_removed: "Removed holiday {t}",
  announcement_posted: "Posted notice \"{t}\"",
  announcement_removed: "Removed notice \"{t}\"",
  data_export: "Started a full data export ({t})",
  regularization_requested: "{t} requested an attendance correction",
  regularization_approved: "Approved attendance correction for {t}",
  regularization_rejected: "Rejected attendance correction for {t}",
  employees_imported: "Imported employees from a file",
  roster_applied: "Applied a shift template to {t}",
};
const FIELD = {
  shift_start: "shift start", shift_end: "shift end", break_max_minutes: "break limit", timezone: "time zone",
  manager_id: "reporting manager", department: "department", site: "branch", email: "email", name: "name",
  esi_not_applicable: "ESI not applicable", epf_not_applicable: "EPF not applicable", uan: "UAN", esi: "ESI number", dob: "date of birth",
  wedding_anniversary: "wedding anniversary", date_of_joining: "joining date", weekly_off: "weekly off",
};
const humanAction = (a) => (a || "").replace(/_/g, " ").replace(/^\w/, c => c.toUpperCase());

export const sentence = (e) => {
  const tmpl = VERB[e.action];
  const t = e.target_name || "someone";
  return tmpl ? tmpl.replace("{t}", t) : `${humanAction(e.action)}${e.target_name ? ` — ${e.target_name}` : ""}`;
};

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
export const humanDetails = (d) => {
  if (!d) return "";
  const parts = d.replace(/\[([\d,\s]*)\]/g, (_, l) => l.split(/,\s*/).filter(Boolean).map(n => DAYS[+n] || n).join("/")).split(/,\s+(?=\w+=)|,(?=\w+=)/).map(p => {
    const m = p.match(/^(\w+)=(.*)$/);
    if (m) {
      const f = FIELD[m[1]] || m[1].replace(/_/g, " ");
      const v = m[2];
      if (v === "None" || v === "") return `${f} cleared`;
      if (m[1] === "manager_id") return `${f} changed`;
      if (m[1] === "weekly_off") return `${f} set to ${v.replace(/\//g, ", ")}`;
      return `${f} set to ${v}`;
    }
    return FIELD[p] ? `${FIELD[p]} updated` : p.replace(/→/g, " to ");
  });
  return parts.join(" · ");
};

const inputCls = "bg-background border border-border px-3 py-2 text-sm";

export default function ActivityTab() {
  const [data, setData] = useState({ entries: [], total: 0, actions: [], page: 1, page_size: 25 });
  const [f, setF] = useState({ action: "", person: "", q: "", from: "", to: "" });
  const [page, setPage] = useState(1);

  useEffect(() => {
    const params = { page, page_size: 25, ...Object.fromEntries(Object.entries(f).filter(([, v]) => v)) };
    const t = setTimeout(() => {
      api.get("/admin/activity", { params }).then(r => setData(r.data)).catch(() => toast.error("Failed to load activity"));
    }, 250);
    return () => clearTimeout(t);
  }, [f, page]);

  const set = (k) => (e) => { setPage(1); setF({ ...f, [k]: e.target.value }); };
  const pages = Math.max(1, Math.ceil(data.total / data.page_size));

  return (
    <div className="border border-border bg-card w-full" data-testid="activity-tab">
      <div className="p-4 border-b border-border flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <ClockCounterClockwise size={16} weight="bold" className="text-primary"/>
          <span className="label-overline">Admin Activity</span>
        </div>
        <span className="font-mono text-xs text-muted-foreground" data-testid="activity-total">{data.total} events</span>
      </div>
      <div className="p-4 border-b border-border grid sm:grid-cols-2 lg:grid-cols-5 gap-2" data-testid="activity-filters">
        <div className="relative lg:col-span-2">
          <MagnifyingGlass size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground"/>
          <input value={f.q} onChange={set("q")} placeholder="Search activity" className={`${inputCls} w-full pl-8`} data-testid="activity-search"/>
        </div>
        <select value={f.action} onChange={set("action")} className={inputCls} data-testid="activity-action-filter">
          <option value="">All actions</option>
          {data.actions.map(a => <option key={a} value={a}>{humanAction(a)}</option>)}
        </select>
        <input value={f.person} onChange={set("person")} placeholder="Employee or admin" className={inputCls} data-testid="activity-person-filter"/>
        <div className="flex gap-2">
          <input type="date" value={f.from} onChange={set("from")} className={`${inputCls} w-full`} data-testid="activity-from"/>
          <input type="date" value={f.to} onChange={set("to")} className={`${inputCls} w-full`} data-testid="activity-to"/>
        </div>
      </div>
      <div className="divide-y divide-border" data-testid="activity-list">
        {data.entries.map(e => (
          <div key={e.log_id} className="p-4 flex items-start gap-4" data-testid={`activity-${e.log_id}`}>
            <div className="font-mono text-xs text-foreground/70 w-36 shrink-0 pt-0.5">
              {new Date(e.created_at).toLocaleString([], { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })}
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm"><span className="font-medium">{e.actor_name}</span> <span className="text-foreground/80">{sentence(e).replace(/^\w/, c => c.toLowerCase())}</span></div>
              {e.details && <div className="text-xs text-foreground/65 mt-1 break-words">{humanDetails(e.details)}</div>}
            </div>
          </div>
        ))}
        {data.entries.length === 0 && <div className="p-8 text-sm text-muted-foreground text-center">No activity matches these filters.</div>}
      </div>
      <div className="p-3 border-t border-border flex items-center justify-between text-sm">
        <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page <= 1} className="inline-flex items-center gap-1 px-3 py-1.5 border border-border disabled:opacity-40" data-testid="activity-prev"><CaretLeft size={14}/> Newer</button>
        <span className="font-mono text-xs" data-testid="activity-page">Page {page} of {pages}</span>
        <button onClick={() => setPage(p => Math.min(pages, p + 1))} disabled={page >= pages} className="inline-flex items-center gap-1 px-3 py-1.5 border border-border disabled:opacity-40" data-testid="activity-next">Older <CaretRight size={14}/></button>
      </div>
    </div>
  );
}
