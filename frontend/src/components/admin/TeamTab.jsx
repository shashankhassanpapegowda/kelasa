import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import AuthPhoto from "@/components/AuthPhoto";
import { fmtDuration } from "@/lib/format";
import { UserPlus, PencilSimple, Trash, X, MagnifyingGlass, Clock as ClockIcon, Buildings } from "@phosphor-icons/react";

const ROLE_LABEL = { admin: "ADMIN", sub_admin: "SUB-ADMIN", employee: "EMPLOYEE" };

export default function TeamTab({ isAdmin, currentUserId }) {
  const [employees, setEmployees] = useState([]);
  const [org, setOrg] = useState({ departments: [], sites: [], managers: [] });
  const [q, setQ] = useState("");
  const [dept, setDept] = useState("all");
  const [editing, setEditing] = useState(null);
  const [adding, setAdding] = useState(false);
  const [loading, setLoading] = useState(false);

  const refresh = async () => {
    setLoading(true);
    try {
      const [e, o] = await Promise.all([api.get("/admin/employees"), api.get("/admin/org")]);
      setEmployees(e.data.employees || []);
      setOrg(o.data);
    } catch { toast.error("Failed to load team"); }
    finally { setLoading(false); }
  };

  useEffect(() => { refresh(); }, []);

  const filtered = useMemo(() => employees.filter(e => {
    const matchQ = !q || `${e.name} ${e.email} ${e.employee_code || ""} ${e.designation || ""}`.toLowerCase().includes(q.toLowerCase());
    const matchD = dept === "all" || (dept === "none" ? !e.department : e.department === dept);
    return matchQ && matchD;
  }), [employees, q, dept]);

  const act = async (fn, msg) => {
    try { await fn(); toast.success(msg); refresh(); }
    catch (e) { toast.error(e?.response?.data?.detail || "Action failed"); }
  };

  const removeEmployee = (emp) => {
    if (!window.confirm(`Remove ${emp.name} permanently?\n\nTheir attendance, routes and leave records will be deleted. This cannot be undone.`)) return;
    act(() => api.delete(`/admin/employees/${emp.user_id}`), `${emp.name} removed`);
  };

  return (
    <div data-testid="team-tab">
      <div className="border border-border bg-card">
        <div className="p-4 border-b border-border flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <span className="label-overline">Team Directory</span>
            <span className="font-mono text-xs text-muted-foreground">{filtered.length}/{employees.length}</span>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <div className="relative">
              <MagnifyingGlass size={14} weight="bold" className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground"/>
              <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search name, email, code" data-testid="team-search"
                className="bg-background border border-border pl-8 pr-3 py-1.5 text-sm w-56"/>
            </div>
            <select value={dept} onChange={e => setDept(e.target.value)} data-testid="team-dept-filter"
              className="bg-background border border-border px-2 py-1.5 text-sm">
              <option value="all">All departments</option>
              {org.departments.map(d => <option key={d.unit_id} value={d.name}>{d.name}</option>)}
              <option value="none">Unassigned</option>
            </select>
            <button onClick={() => setAdding(true)} data-testid="add-employee-btn"
              className="bg-foreground text-background px-3 py-1.5 text-sm inline-flex items-center gap-2 hover:bg-primary transition-colors">
              <UserPlus size={15} weight="bold"/> Add Employee
            </button>
          </div>
        </div>
        {loading && <div className="loading-bar"/>}
        <div className="divide-y divide-border max-h-[640px] overflow-y-auto" data-testid="employees-list">
          {filtered.map(emp => (
            <div key={emp.user_id} className="p-4 flex flex-col sm:flex-row sm:items-start gap-3 hover:bg-secondary/40" data-testid={`emp-row-${emp.user_id}`}>
              <div className="flex items-start gap-3 flex-1 min-w-0">
                <AuthPhoto path={emp.face_photo_path} className="w-10 h-10 rounded-full object-cover border border-border"
                  fallback={emp.picture
                    ? <img src={emp.picture} className="w-10 h-10 rounded-full border border-border" alt=""/>
                    : <div className="w-10 h-10 rounded-full bg-secondary grid place-items-center text-sm font-medium">{emp.name?.[0]}</div>}/>
                <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-medium truncate">{emp.name}</span>
                  {emp.is_on_duty && !emp.on_break && <Tag className="bg-[#00E676] text-black">ON DUTY</Tag>}
                  {emp.on_break && <Tag className="bg-yellow-400 text-black">ON BREAK</Tag>}
                  {emp.role !== "employee" && <Tag className="border border-border">{ROLE_LABEL[emp.role]}</Tag>}
                  {emp.tracking_mode === "always_on" && <Tag className="bg-[#0047FF] text-white">24/7</Tag>}
                  {emp.pending_invite && <Tag className="bg-secondary text-foreground">INVITE PENDING</Tag>}
                  {!emp.face_enrolled && <Tag className="bg-yellow-500/20 text-yellow-700">NOT ENROLLED</Tag>}
                </div>
                <div className="text-xs text-muted-foreground truncate">{emp.email}</div>
                <div className="text-[10px] font-mono text-muted-foreground mt-1 flex items-center gap-1.5 flex-wrap">
                  <Buildings size={11} weight="bold"/>
                  <span>{emp.department || "No department"}{emp.site ? ` · ${emp.site}` : ""}</span>
                  {emp.designation && <span>· {emp.designation}</span>}
                </div>
                <div className="text-[10px] font-mono text-muted-foreground mt-0.5 flex items-center gap-1.5">
                  <ClockIcon size={11} weight="bold"/>
                  {emp.shift_start ? `${emp.shift_start}${emp.shift_end ? ` – ${emp.shift_end}` : ""}` : <span className="italic text-yellow-700">No shift set</span>}
                  <span className="mx-1">·</span>
                  <span>Break {emp.break_max_minutes ?? 60}m</span>
                </div>
              </div>
              </div>
              <div className="text-left sm:text-right shrink-0 pl-[52px] sm:pl-0">
                <div className="font-mono text-sm">{fmtDuration(emp.today_minutes)}</div>
                <div className="flex items-center gap-2 mt-1 sm:justify-end flex-wrap">
                  <button onClick={() => setEditing(emp)} className="text-[10px] label-overline hover:text-primary inline-flex items-center gap-1" data-testid={`edit-emp-${emp.user_id}`}>
                    <PencilSimple size={10} weight="bold"/> EDIT
                  </button>
                  {isAdmin && (
                    <button onClick={() => act(() => api.patch(`/admin/employees/${emp.user_id}/tracking_mode`, { tracking_mode: emp.tracking_mode === "always_on" ? "duty_only" : "always_on" }), "Tracking mode updated")}
                      className="text-[10px] label-overline hover:text-primary" data-testid={`toggle-tracking-${emp.user_id}`}>
                      {emp.tracking_mode === "always_on" ? "→ DUTY ONLY" : "→ 24/7"}
                    </button>
                  )}
                  {emp.face_enrolled && (
                    <button onClick={() => { if (window.confirm(`Reset face enrollment for ${emp.name}?`)) act(() => api.delete(`/admin/employees/${emp.user_id}/face`), "Face enrollment reset"); }}
                      className="text-[10px] label-overline hover:text-[#FF3B30]" data-testid={`reset-face-${emp.user_id}`}>
                      RESET FACE
                    </button>
                  )}
                  {emp.user_id !== currentUserId && (
                    <button onClick={() => removeEmployee(emp)} className="text-[10px] label-overline text-muted-foreground hover:text-[#FF3B30] inline-flex items-center gap-1" data-testid={`delete-emp-${emp.user_id}`}>
                      <Trash size={10} weight="bold"/> REMOVE
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
          {filtered.length === 0 && <div className="p-8 text-sm text-muted-foreground text-center">No employees match this filter.</div>}
        </div>
      </div>

      {adding && (
        <EmployeeFormModal org={org} isAdmin={isAdmin} onClose={() => setAdding(false)}
          onSave={async (form) => {
            try {
              await api.post("/admin/employees", form);
              toast.success(`${form.name} added — they can sign in with ${form.email}`);
              setAdding(false); refresh();
            } catch (e) { toast.error(e?.response?.data?.detail || "Could not add employee"); }
          }}/>
      )}

      {editing && (
        <EmployeeEditModal emp={editing} org={org} isAdmin={isAdmin} onClose={() => setEditing(null)}
          onSave={async ({ shift, assignment, role }) => {
            try {
              await api.patch(`/admin/employees/${editing.user_id}/shift`, shift);
              await api.patch(`/admin/employees/${editing.user_id}/assignment`, assignment);
              if (isAdmin && role && role !== editing.role) {
                await api.patch(`/admin/employees/${editing.user_id}/role`, { role });
              }
              toast.success(`${editing.name} updated`);
              setEditing(null); refresh();
            } catch (e) { toast.error(e?.response?.data?.detail || "Update failed"); }
          }}/>
      )}
    </div>
  );
}

const Tag = ({ children, className = "" }) => (
  <span className={`text-[9px] font-mono uppercase tracking-wider px-1.5 py-0.5 ${className}`}>{children}</span>
);

const Field = ({ label, children }) => (
  <div>
    <label className="label-overline mb-1.5 block">{label}</label>
    {children}
  </div>
);

const inputCls = "w-full bg-background border border-border px-3 py-2 text-sm";

function Modal({ title, subtitle, onClose, children, testid }) {
  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm grid place-items-center p-4 overflow-y-auto" onClick={onClose} data-testid={testid}>
      <div className="bg-card border border-border max-w-lg w-full my-8" onClick={(e) => e.stopPropagation()}>
        <div className="p-4 border-b border-border flex items-center justify-between">
          <div>
            <div className="label-overline">{title}</div>
            {subtitle && <div className="font-semibold tracking-tight mt-0.5">{subtitle}</div>}
          </div>
          <button onClick={onClose} className="p-1 hover:bg-secondary" data-testid="modal-close"><X size={18} weight="bold"/></button>
        </div>
        {children}
      </div>
    </div>
  );
}

function EmployeeFormModal({ org, isAdmin, onClose, onSave }) {
  const [f, setF] = useState({
    name: "", email: "", department: "", site: "", manager_id: "", designation: "",
    phone: "", employee_code: "", role: "employee", shift_start: "", shift_end: "", break_max_minutes: 60,
  });
  const set = (k) => (e) => setF(prev => ({ ...prev, [k]: e.target.value }));
  return (
    <Modal title="Add Employee" subtitle="Create their record now, they sign in with Google later" onClose={onClose} testid="add-employee-modal">
      <div className="p-5 space-y-4">
        <div className="grid sm:grid-cols-2 gap-3">
          <Field label="Full Name"><input value={f.name} onChange={set("name")} className={inputCls} data-testid="new-emp-name"/></Field>
          <Field label="Work Email"><input value={f.email} onChange={set("email")} type="email" className={inputCls} data-testid="new-emp-email"/></Field>
          <Field label="Employee Code"><input value={f.employee_code} onChange={set("employee_code")} className={inputCls} data-testid="new-emp-code"/></Field>
          <Field label="Phone"><input value={f.phone} onChange={set("phone")} className={inputCls} data-testid="new-emp-phone"/></Field>
          <Field label="Department">
            <select value={f.department} onChange={set("department")} className={inputCls} data-testid="new-emp-dept">
              <option value="">—</option>
              {org.departments.map(d => <option key={d.unit_id} value={d.name}>{d.name}</option>)}
            </select>
          </Field>
          <Field label="Site">
            <select value={f.site} onChange={set("site")} className={inputCls} data-testid="new-emp-site">
              <option value="">—</option>
              {org.sites.map(s => <option key={s.unit_id} value={s.name}>{s.name}</option>)}
            </select>
          </Field>
          <Field label="Designation"><input value={f.designation} onChange={set("designation")} className={inputCls} data-testid="new-emp-designation"/></Field>
          <Field label="Reports To">
            <select value={f.manager_id} onChange={set("manager_id")} className={inputCls} data-testid="new-emp-manager">
              <option value="">—</option>
              {org.managers.map(m => <option key={m.user_id} value={m.user_id}>{m.name}</option>)}
            </select>
          </Field>
          <Field label="Shift Start"><input type="time" value={f.shift_start} onChange={set("shift_start")} className={`${inputCls} font-mono`} data-testid="new-emp-shift-start"/></Field>
          <Field label="Shift End"><input type="time" value={f.shift_end} onChange={set("shift_end")} className={`${inputCls} font-mono`} data-testid="new-emp-shift-end"/></Field>
          {isAdmin && (
            <Field label="Access Level">
              <select value={f.role} onChange={set("role")} className={inputCls} data-testid="new-emp-role">
                <option value="employee">Employee</option>
                <option value="sub_admin">Sub-admin</option>
                <option value="admin">Admin</option>
              </select>
            </Field>
          )}
        </div>
        <p className="text-[11px] text-muted-foreground">
          The employee signs in with Google using this exact email and lands straight on their own record.
        </p>
        <div className="flex items-center gap-2 pt-1">
          <button onClick={() => onSave({ ...f, break_max_minutes: Number(f.break_max_minutes) || 60 })} data-testid="save-new-emp"
            className="flex-1 bg-foreground text-background px-4 py-3 hover:bg-primary transition-colors font-medium">Add to Team</button>
          <button onClick={onClose} className="border border-border px-4 py-3 hover:bg-secondary">Cancel</button>
        </div>
      </div>
    </Modal>
  );
}

function EmployeeEditModal({ emp, org, isAdmin, onClose, onSave }) {
  const [shift, setShift] = useState({
    shift_start: emp.shift_start || "", shift_end: emp.shift_end || "", break_max_minutes: emp.break_max_minutes ?? 60,
  });
  const [a, setA] = useState({
    department: emp.department || "", site: emp.site || "", manager_id: emp.manager_id || "",
    designation: emp.designation || "", phone: emp.phone || "", employee_code: emp.employee_code || "",
  });
  const [role, setRole] = useState(emp.role);
  const setAs = (k) => (e) => setA(prev => ({ ...prev, [k]: e.target.value }));
  return (
    <Modal title="Employee Settings" subtitle={emp.name} onClose={onClose} testid="edit-employee-modal">
      <div className="p-5 space-y-4">
        <div className="grid sm:grid-cols-2 gap-3">
          <Field label="Shift Start"><input type="time" value={shift.shift_start} onChange={e => setShift(s => ({ ...s, shift_start: e.target.value }))} className={`${inputCls} font-mono`} data-testid="shift-start-input"/></Field>
          <Field label="Shift End"><input type="time" value={shift.shift_end} onChange={e => setShift(s => ({ ...s, shift_end: e.target.value }))} className={`${inputCls} font-mono`} data-testid="shift-end-input"/></Field>
          <Field label="Break Limit (min)"><input type="number" min="0" max="600" value={shift.break_max_minutes} onChange={e => setShift(s => ({ ...s, break_max_minutes: parseInt(e.target.value || "0", 10) }))} className={`${inputCls} font-mono`} data-testid="break-max-input"/></Field>
          <Field label="Employee Code"><input value={a.employee_code} onChange={setAs("employee_code")} className={inputCls} data-testid="edit-emp-code"/></Field>
          <Field label="Department">
            <select value={a.department} onChange={setAs("department")} className={inputCls} data-testid="edit-emp-dept">
              <option value="">—</option>
              {org.departments.map(d => <option key={d.unit_id} value={d.name}>{d.name}</option>)}
            </select>
          </Field>
          <Field label="Site">
            <select value={a.site} onChange={setAs("site")} className={inputCls} data-testid="edit-emp-site">
              <option value="">—</option>
              {org.sites.map(s => <option key={s.unit_id} value={s.name}>{s.name}</option>)}
            </select>
          </Field>
          <Field label="Designation"><input value={a.designation} onChange={setAs("designation")} className={inputCls} data-testid="edit-emp-designation"/></Field>
          <Field label="Phone"><input value={a.phone} onChange={setAs("phone")} className={inputCls} data-testid="edit-emp-phone"/></Field>
          <Field label="Reports To">
            <select value={a.manager_id} onChange={setAs("manager_id")} className={inputCls} data-testid="edit-emp-manager">
              <option value="">—</option>
              {org.managers.filter(m => m.user_id !== emp.user_id).map(m => <option key={m.user_id} value={m.user_id}>{m.name}</option>)}
            </select>
          </Field>
          {isAdmin && (
            <Field label="Access Level">
              <select value={role} onChange={e => setRole(e.target.value)} className={inputCls} data-testid="edit-emp-role">
                <option value="employee">Employee</option>
                <option value="sub_admin">Sub-admin</option>
                <option value="admin">Admin</option>
              </select>
            </Field>
          )}
        </div>
        <p className="text-[10px] text-muted-foreground">Breaks longer than the limit are flagged as over-break. Late detection has a 15-minute grace.</p>
        <div className="flex items-center gap-2 pt-1">
          <button onClick={() => onSave({ shift, assignment: a, role })} data-testid="save-employee-btn"
            className="flex-1 bg-foreground text-background px-4 py-3 hover:bg-primary transition-colors font-medium">Save Changes</button>
          <button onClick={onClose} className="border border-border px-4 py-3 hover:bg-secondary">Cancel</button>
        </div>
      </div>
    </Modal>
  );
}
