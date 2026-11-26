import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import AuthPhoto from "@/components/AuthPhoto";
import BankRequestsPanel from "@/components/admin/BankRequestsPanel";
import EmployeeProfileModal from "@/components/admin/EmployeeProfileModal";
import RemoveEmployeeDialog from "@/components/admin/RemoveEmployeeDialog";
import { fmtDuration } from "@/lib/format";
import { UserPlus, PencilSimple, Trash, X, MagnifyingGlass, Clock as ClockIcon, Buildings, Key, IdentificationCard } from "@phosphor-icons/react";

const ROLE_LABEL = { admin: "ADMIN", sub_admin: "SUB-ADMIN", employee: "EMPLOYEE" };

export default function TeamTab({ isAdmin, currentUserId }) {
  const [employees, setEmployees] = useState([]);
  const [org, setOrg] = useState({ departments: [], sites: [], managers: [] });
  const [q, setQ] = useState("");
  const [dept, setDept] = useState("all");
  const [branch, setBranch] = useState("all");
  const [editing, setEditing] = useState(null);
  const [viewing, setViewing] = useState(null);
  const [adding, setAdding] = useState(false);
  const [passwordFor, setPasswordFor] = useState(null);
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
    const matchB = branch === "all" || (branch === "none" ? !e.site : e.site === branch);
    return matchQ && matchD && matchB;
  }), [employees, q, dept, branch]);

  const act = async (fn, msg) => {
    try { await fn(); toast.success(msg); refresh(); }
    catch (e) { toast.error(e?.response?.data?.detail || "Action failed"); }
  };

  const [removing, setRemoving] = useState(null);
  const removeEmployee = (emp) => { document.querySelectorAll("details[open]").forEach(d => d.removeAttribute("open")); setRemoving(emp); };
  const confirmRemove = () => {
    const emp = removing;
    setRemoving(null);
    act(() => api.delete(`/admin/employees/${emp.user_id}`), `${emp.name} removed`);
  };

  return (
    <div data-testid="team-tab">
      {isAdmin && <BankRequestsPanel/>}
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
            <select value={branch} onChange={e => setBranch(e.target.value)} data-testid="team-branch-filter"
              className="bg-background border border-border px-2 py-1.5 text-sm">
              <option value="all">All branches</option>
              {org.sites.map(s => <option key={s.unit_id} value={s.name}>{s.name}</option>)}
              <option value="none">No branch</option>
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
                <AuthPhoto path={emp.avatar_path || emp.face_photo_path} className="w-10 h-10 rounded-full object-cover border border-border"
                  fallback={emp.picture
                    ? <img src={emp.picture} className="w-10 h-10 rounded-full border border-border" alt=""/>
                    : <div className="w-10 h-10 rounded-full bg-secondary grid place-items-center text-sm font-medium">{emp.name?.[0]}</div>}/>
                <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-medium truncate">{emp.name}</span>
                  {emp.is_on_duty && !emp.on_break && <Tag className="bg-[#00E676] text-black">ON DUTY</Tag>}
                  {emp.on_break && <Tag className="bg-yellow-400 text-black">ON BREAK</Tag>}
                  {emp.role !== "employee" && <Tag className="border border-border">{ROLE_LABEL[emp.role]}</Tag>}
                  {emp.field_staff && <Tag className="bg-[#0047FF]/15 text-[#0047FF]">FIELD STAFF</Tag>}
                  {emp.tracking_mode === "always_on" && <span title="24/7 = location is tracked all the time. Duty only = tracked only between check-in and check-out."><Tag className="bg-[#0047FF] text-white">24/7</Tag></span>}
                  {emp.pending_invite && <Tag className="bg-secondary text-foreground">INVITE PENDING</Tag>}
                  {!emp.has_password && <Tag className="bg-[#FF3B30]/15 text-[#FF3B30]">NO PASSWORD</Tag>}
                  {emp.must_change_password && emp.has_password && <Tag className="bg-yellow-400 text-black">TEMP PASSWORD</Tag>}
                </div>
                <div className="text-xs text-muted-foreground truncate">{emp.email}</div>
                <div className="text-[10px] font-mono text-muted-foreground mt-1 flex items-center gap-1.5 flex-wrap">
                  <Buildings size={11} weight="bold"/>
                  <span>{emp.site || "No branch"}{emp.department ? ` · ${emp.department}` : ""}</span>
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
                  <button onClick={() => setViewing(emp)} className="text-[10px] label-overline hover:text-primary inline-flex items-center gap-1" data-testid={`profile-emp-${emp.user_id}`}>
                    <IdentificationCard size={11} weight="bold"/> PROFILE
                  </button>
                  {(isAdmin || emp.user_id !== currentUserId) && (
                    <button onClick={() => setEditing(emp)} className="text-[10px] label-overline hover:text-primary inline-flex items-center gap-1" data-testid={`edit-emp-${emp.user_id}`}>
                      <PencilSimple size={10} weight="bold"/> EDIT
                    </button>
                  )}
                  {(isAdmin || emp.user_id !== currentUserId) && (
                    <button onClick={() => setPasswordFor(emp)} className="text-[10px] label-overline hover:text-primary inline-flex items-center gap-1" data-testid={`set-password-${emp.user_id}`}>
                      <Key size={10} weight="bold"/> {emp.has_password ? "RESET PASSWORD" : "SET PASSWORD"}
                    </button>
                  )}
                  {isAdmin && (
                    <button onClick={() => act(() => api.patch(`/admin/employees/${emp.user_id}/tracking_mode`, { tracking_mode: emp.tracking_mode === "always_on" ? "duty_only" : "always_on" }), "Tracking mode updated")}
                      title="24/7 = location is tracked all the time. Duty only = tracked only between check-in and check-out."
                      className="text-[10px] label-overline hover:text-primary" data-testid={`toggle-tracking-${emp.user_id}`}>
                      {emp.tracking_mode === "always_on" ? "→ DUTY ONLY" : "→ 24/7"}
                    </button>
                  )}
                  {emp.user_id !== currentUserId && (
                    <details className="relative" data-testid={`more-emp-${emp.user_id}`}>
                      <summary className="list-none cursor-pointer text-[10px] label-overline hover:text-foreground">MORE ▾</summary>
                      <div className="absolute right-0 mt-1 z-20 bg-card border border-border shadow-lg min-w-[160px]">
                        <button onClick={() => removeEmployee(emp)} className="w-full text-left px-3 py-2 text-xs text-[#FF3B30] hover:bg-[#FF3B30]/10 inline-flex items-center gap-1.5" data-testid={`delete-emp-${emp.user_id}`}>
                          <Trash size={12} weight="bold"/> Remove employee
                        </button>
                      </div>
                    </details>
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

      {passwordFor && (
        <SetPasswordModal emp={passwordFor} onClose={() => setPasswordFor(null)}
          onSave={async (password) => {
            try {
              await api.patch(`/admin/employees/${passwordFor.user_id}/password`, { password });
              toast.success(`Password set for ${passwordFor.name} — share it with them, they'll be asked to change it`);
              setPasswordFor(null); refresh();
            } catch (e) { toast.error(e?.response?.data?.detail || "Could not set password"); }
          }}/>
      )}

      {removing && <RemoveEmployeeDialog emp={removing} onCancel={() => setRemoving(null)} onConfirm={confirmRemove}/>}
      {viewing && <EmployeeProfileModal emp={viewing} onClose={() => setViewing(null)}/>}
      {editing && (
        <EmployeeEditModal emp={editing} org={org} isAdmin={isAdmin} onClose={() => setEditing(null)}
          onSave={async ({ shift, assignment, role, fieldStaff }) => {
            try {
              await api.patch(`/admin/employees/${editing.user_id}/assignment`, assignment);
              await api.patch(`/admin/employees/${editing.user_id}/shift`, shift);
              if (fieldStaff !== !!editing.field_staff) {
                await api.patch(`/admin/employees/${editing.user_id}/field_staff`, { field_staff: fieldStaff });
              }
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

function SetPasswordModal({ emp, onClose, onSave }) {
  const [pw, setPw] = useState("");
  const [err, setErr] = useState("");
  const submit = () => {
    if (pw.trim().length < 8) return setErr("At least 8 characters");
    onSave(pw.trim());
  };
  return (
    <Modal title={emp.has_password ? "Reset Password" : "Set Password"} subtitle={emp.name} onClose={onClose} testid="set-password-modal">
      <div className="p-5 space-y-4">
        <Field label="Temporary password">
          <input type="text" value={pw} onChange={(e) => { setPw(e.target.value); setErr(""); }} className={`${inputCls} font-mono`}
            placeholder="At least 8 characters" data-testid="temp-password-input" autoFocus/>
        </Field>
        {err && <p className="text-sm text-[#FF3B30]" data-testid="set-password-error">{err}</p>}
        <p className="text-[11px] text-muted-foreground">
          Share this with {emp.name.split(" ")[0]} directly. They'll be asked to set their own password the first time they sign in, and any active session of theirs is signed out now.
        </p>
        <div className="flex items-center gap-2">
          <button onClick={submit} data-testid="save-password-btn"
            className="flex-1 bg-foreground text-background px-4 py-3 hover:bg-primary transition-colors font-medium">Save Password</button>
          <button onClick={onClose} className="border border-border px-4 py-3 hover:bg-secondary">Cancel</button>
        </div>
      </div>
    </Modal>
  );
}

function EmployeeFormModal({ org, isAdmin, onClose, onSave }) {
  const [f, setF] = useState({
    name: "", email: "", department: "", site: "", manager_id: "", designation: "",
    phone: "", employee_code: "", role: "employee", password: "", shift_start: "", shift_end: "", break_max_minutes: 60,
  });
  const set = (k) => (e) => setF(prev => ({ ...prev, [k]: e.target.value }));
  return (
    <Modal title="Add Employee" subtitle="Create their record and share their first password" onClose={onClose} testid="add-employee-modal">
      <div className="p-5 space-y-4">
        <div className="grid sm:grid-cols-2 gap-3">
          <Field label="Full Name"><input value={f.name} onChange={set("name")} className={inputCls} data-testid="new-emp-name"/></Field>
          <Field label="Work Email"><input value={f.email} onChange={set("email")} type="email" className={inputCls} data-testid="new-emp-email"/></Field>
          <Field label="First Password"><input value={f.password} onChange={set("password")} type="text" placeholder="At least 8 characters" className={`${inputCls} font-mono`} data-testid="new-emp-password"/></Field>
          <Field label="Employee Code"><input value={f.employee_code} onChange={set("employee_code")} className={inputCls} data-testid="new-emp-code"/></Field>
          <Field label="Phone"><input value={f.phone} onChange={set("phone")} className={inputCls} data-testid="new-emp-phone"/></Field>
          <Field label="Department">
            <select value={f.department} onChange={set("department")} className={inputCls} data-testid="new-emp-dept">
              <option value="">—</option>
              {org.departments.map(d => <option key={d.unit_id} value={d.name}>{d.name}</option>)}
            </select>
          </Field>
          <Field label="Branch">
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
          Share the first password with them directly — they sign in with this email and are asked to set their own password straight away.
        </p>
        <div className="flex items-center gap-2 pt-1">
          <button onClick={() => {
              if (!f.name.trim() || !f.email.trim()) return toast.error("Name and work email are required");
              if ((f.password || "").length < 8) return toast.error("Set a first password of at least 8 characters");
              onSave({ ...f, break_max_minutes: Number(f.break_max_minutes) || 60 });
            }} data-testid="save-new-emp"
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
    weekly_off: emp.weekly_off ?? [6],
  });
  const [a, setA] = useState({
    name: emp.name || "", email: emp.email || "", department: emp.department || "", site: emp.site || "", manager_id: emp.manager_id || "",
    designation: emp.designation || "", phone: emp.phone || "", employee_code: emp.employee_code || "",
  });
  const [role, setRole] = useState(emp.role);
  const [fieldStaff, setFieldStaff] = useState(!!emp.field_staff);
  const setAs = (k) => (e) => setA(prev => ({ ...prev, [k]: e.target.value }));
  return (
    <Modal title="Employee Settings" subtitle={emp.name} onClose={onClose} testid="edit-employee-modal">
      <div className="p-5 space-y-4">
        <div className="grid sm:grid-cols-2 gap-3">
          <Field label="Full Name"><input value={a.name} onChange={setAs("name")} className={inputCls} data-testid="edit-emp-name"/></Field>
          <Field label="Work Email"><input type="email" value={a.email} onChange={setAs("email")} placeholder="name@company.com" className={inputCls} data-testid="edit-emp-email"/></Field>
          <Field label="Shift Start"><input type="time" value={shift.shift_start} onChange={e => setShift(s => ({ ...s, shift_start: e.target.value }))} className={`${inputCls} font-mono`} data-testid="shift-start-input"/></Field>
          <Field label="Shift End"><input type="time" value={shift.shift_end} onChange={e => setShift(s => ({ ...s, shift_end: e.target.value }))} className={`${inputCls} font-mono`} data-testid="shift-end-input"/></Field>
          <Field label="Break Limit (min)"><input type="number" min="0" max="600" value={shift.break_max_minutes} onChange={e => setShift(s => ({ ...s, break_max_minutes: parseInt(e.target.value || "0", 10) }))} className={`${inputCls} font-mono`} data-testid="break-max-input"/></Field>
          <div className="sm:col-span-2">
            <div className="label-overline mb-1.5">Weekly Off</div>
            <div className="flex flex-wrap gap-1.5" data-testid="weekly-off-picker">
              {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d, i) => {
                const on = shift.weekly_off.includes(i);
                return (
                  <button type="button" key={d} data-testid={`weekly-off-${i}`}
                    onClick={() => setShift(s => ({ ...s, weekly_off: on ? s.weekly_off.filter(x => x !== i) : [...s.weekly_off, i] }))}
                    className={`px-2.5 py-1 text-xs border transition-colors ${on ? "bg-foreground text-background border-foreground" : "border-border hover:border-foreground"}`}>{d}</button>
                );
              })}
            </div>
          </div>
          <Field label="Employee Code"><input value={a.employee_code} onChange={setAs("employee_code")} className={inputCls} data-testid="edit-emp-code"/></Field>
          <Field label="Department">
            <select value={a.department} onChange={setAs("department")} className={inputCls} data-testid="edit-emp-dept">
              <option value="">—</option>
              {org.departments.map(d => <option key={d.unit_id} value={d.name}>{d.name}</option>)}
            </select>
          </Field>
          <Field label="Branch">
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
        <label className="flex items-start gap-3 border border-border p-3 cursor-pointer hover:bg-secondary/40" data-testid="edit-emp-field-staff">
          <input type="checkbox" checked={fieldStaff} onChange={e => setFieldStaff(e.target.checked)} className="mt-0.5 accent-[#0047FF]" data-testid="edit-emp-field-staff-checkbox"/>
          <span>
            <span className="text-sm font-medium block">Field staff — can punch from anywhere</span>
            <span className="text-[11px] text-muted-foreground">When off, they can punch in/out only inside a branch circle.</span>
          </span>
        </label>
        <p className="text-[10px] text-muted-foreground">Breaks longer than the limit are flagged as over-break. Late detection has a 15-minute grace.</p>
        <div className="flex items-center gap-2 pt-1">
          <button onClick={() => {
              if (!a.name.trim()) return toast.error("Name is required");
              if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(a.email.trim())) return toast.error("Enter a valid work email");
              onSave({ shift, assignment: { ...a, name: a.name.trim(), email: a.email.trim() }, role, fieldStaff });
            }} data-testid="save-employee-btn"
            className="flex-1 bg-foreground text-background px-4 py-3 hover:bg-primary transition-colors font-medium">Save Changes</button>
          <button onClick={onClose} className="border border-border px-4 py-3 hover:bg-secondary">Cancel</button>
        </div>
      </div>
    </Modal>
  );
}
