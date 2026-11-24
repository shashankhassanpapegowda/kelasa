import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import BranchEditModal from "@/components/admin/BranchEditModal";
import { Plus, Trash, MapPinArea, Users, PencilSimple } from "@phosphor-icons/react";

export default function BranchesTab() {
  const [branches, setBranches] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [name, setName] = useState("");
  const [editing, setEditing] = useState(null);

  const load = async () => {
    try {
      const [o, e] = await Promise.all([api.get("/admin/org"), api.get("/admin/employees")]);
      setBranches(o.data.sites || []);
      setEmployees(e.data.employees || []);
    } catch { toast.error("Failed to load branches"); }
  };
  useEffect(() => { load(); }, []);

  const add = async () => {
    if (!name.trim()) return;
    try {
      const r = await api.post("/admin/org/sites", { name: name.trim() });
      setName(""); await load();
      toast.success(`${r.data.site.name} added — now pin its location`);
      setEditing(r.data.site);
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not add"); }
  };

  const remove = async (b) => {
    if (!window.confirm(`Delete branch "${b.name}"? Its employees become unassigned and its geofence is removed.`)) return;
    try { await api.delete(`/admin/org/sites/${b.unit_id}`); toast.success("Branch removed"); load(); }
    catch { toast.error("Could not remove"); }
  };

  const fenced = branches.filter(b => b.lat != null && b.radius_m);
  const fieldStaff = employees.filter(e => e.field_staff).length;

  return (
    <div className="space-y-6" data-testid="branches-tab">
      <div className={`border p-4 text-sm ${fenced.length ? "border-[#0047FF]/40 bg-[#0047FF]/5" : "border-yellow-500/40 bg-yellow-500/5"}`} data-testid="geofence-status">
        {fenced.length
          ? <>Geofencing is <strong>on</strong>. Staff must be inside a pinned branch to check in or out. {fieldStaff} field staff can check in from anywhere.</>
          : <>Geofencing is <strong>off</strong>. No branch has a location pinned yet, so staff can check in from anywhere. Pin at least one branch to turn it on.</>}
      </div>
      {branches.filter(b => !(b.lat != null && b.radius_m) && employees.some(e => e.site === b.name)).map(b => (
        <div key={b.unit_id} className="border border-[#FF3B30]/50 bg-[#FF3B30]/5 p-3 text-sm" data-testid={`unpinned-warning-${b.unit_id}`}>
          <strong>{b.name}</strong> has {employees.filter(e => e.site === b.name).length} employee(s) but no pinned location.
          {fenced.length ? " They can only check in at another pinned branch until you pin it." : " Pin it so its staff check in at the right place."}
        </div>
      ))}

      <div className="border border-border bg-card">
        <div className="p-4 border-b border-border flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <MapPinArea size={16} weight="bold" className="text-primary"/>
            <span className="label-overline">Branches</span>
            <span className="font-mono text-xs text-muted-foreground">{branches.length}</span>
          </div>
          <div className="flex items-center gap-2">
            <input value={name} onChange={e => setName(e.target.value)} onKeyDown={e => e.key === "Enter" && add()}
              placeholder="New branch name" data-testid="branch-new-input"
              className="bg-background border border-border px-3 py-1.5 text-sm w-56"/>
            <button onClick={add} data-testid="branch-add-btn"
              className="bg-foreground text-background px-3 py-1.5 text-sm inline-flex items-center gap-1.5 hover:bg-primary transition-colors">
              <Plus size={14} weight="bold"/> Add Branch
            </button>
          </div>
        </div>
        <div className="divide-y divide-border">
          {branches.map(b => (
            <BranchRow key={b.unit_id} branch={b} members={employees.filter(e => e.site === b.name)}
              onEdit={() => setEditing(b)} onRemove={() => remove(b)}/>
          ))}
          {branches.length === 0 && <div className="p-8 text-sm text-muted-foreground text-center">No branches yet. Add your first branch above.</div>}
        </div>
      </div>

      {editing && (
        <BranchEditModal branch={editing} others={fenced.filter(b => b.unit_id !== editing.unit_id)}
          onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load(); }}/>
      )}
    </div>
  );
}

function BranchRow({ branch, members, onEdit, onRemove }) {
  const [open, setOpen] = useState(false);
  const fenced = branch.lat != null && branch.radius_m;
  return (
    <div className="p-4" data-testid={`branch-row-${branch.unit_id}`}>
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium">{branch.name}</span>
            {fenced
              ? <span className="text-[9px] font-mono uppercase tracking-wider bg-[#0047FF] text-white px-1.5 py-0.5" data-testid={`branch-radius-${branch.unit_id}`}>{branch.radius_m} M RADIUS</span>
              : <span className="text-[9px] font-mono uppercase tracking-wider bg-yellow-400 text-black px-1.5 py-0.5">NOT PINNED</span>}
          </div>
          {branch.address && <div className="text-xs text-muted-foreground mt-0.5 truncate max-w-xl">{branch.address}</div>}
          {fenced && <div className="text-[10px] font-mono text-muted-foreground mt-0.5">{branch.lat.toFixed(5)}, {branch.lng.toFixed(5)}</div>}
        </div>
        <div className="flex items-center gap-3">
          <button onClick={() => setOpen(v => !v)} className="text-[10px] label-overline hover:text-primary inline-flex items-center gap-1" data-testid={`branch-members-${branch.unit_id}`}>
            <Users size={11} weight="bold"/> {members.length} EMPLOYEES
          </button>
          <button onClick={onEdit} className="text-[10px] label-overline hover:text-primary inline-flex items-center gap-1" data-testid={`branch-edit-${branch.unit_id}`}>
            <PencilSimple size={11} weight="bold"/> {fenced ? "EDIT GEOFENCE" : "PIN LOCATION"}
          </button>
          <button onClick={onRemove} className="text-muted-foreground hover:text-[#FF3B30]" data-testid={`branch-delete-${branch.unit_id}`}>
            <Trash size={14} weight="bold"/>
          </button>
        </div>
      </div>
      {open && (
        <div className="mt-3 flex flex-wrap gap-1.5" data-testid={`branch-member-list-${branch.unit_id}`}>
          {members.map(m => (
            <span key={m.user_id} className="text-xs border border-border px-2 py-1">
              {m.name}{m.field_staff ? " · field" : ""}
            </span>
          ))}
          {members.length === 0 && <span className="text-xs text-muted-foreground">No employees yet — set their branch from the Team tab.</span>}
        </div>
      )}
    </div>
  );
}
