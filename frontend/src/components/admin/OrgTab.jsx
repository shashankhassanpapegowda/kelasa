import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { Plus, Trash, ShieldCheck } from "@phosphor-icons/react";

export default function OrgTab() {
  const [org, setOrg] = useState({ departments: [], sites: [], managers: [] });
  const [deptName, setDeptName] = useState("");
  const [siteName, setSiteName] = useState("");

  const load = async () => {
    try { setOrg((await api.get("/admin/org")).data); }
    catch { toast.error("Failed to load organisation"); }
  };
  useEffect(() => { load(); }, []);

  const add = async (kind, name, reset) => {
    if (!name.trim()) return;
    try {
      await api.post(`/admin/org/${kind}`, { name: name.trim() });
      toast.success(`${name.trim()} added`);
      reset(""); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not add"); }
  };

  const remove = async (kind, unit) => {
    if (!window.confirm(`Delete "${unit.name}"? Employees in it become unassigned.`)) return;
    try { await api.delete(`/admin/org/${kind}/${unit.unit_id}`); toast.success("Removed"); load(); }
    catch { toast.error("Could not remove"); }
  };

  const subAdmins = org.managers.filter(m => m.role === "sub_admin");

  return (
    <div className="grid lg:grid-cols-2 gap-6" data-testid="org-tab">
      <UnitList title="Departments" kind="departments" units={org.departments} value={deptName} setValue={setDeptName}
        onAdd={() => add("departments", deptName, setDeptName)} onRemove={(u) => remove("departments", u)} testid="departments"/>
      <UnitList title="Sites / Branches" kind="sites" units={org.sites} value={siteName} setValue={setSiteName}
        onAdd={() => add("sites", siteName, setSiteName)} onRemove={(u) => remove("sites", u)} testid="sites"/>

      <div className="lg:col-span-2 border border-border bg-card" data-testid="subadmin-scopes">
        <div className="p-4 border-b border-border flex items-center gap-2">
          <ShieldCheck size={16} weight="bold" className="text-primary"/>
          <span className="label-overline">Sub-admin Coverage</span>
        </div>
        <div className="divide-y divide-border">
          {subAdmins.map(m => (
            <ScopeRow key={m.user_id} manager={m} org={org} onSaved={load}/>
          ))}
          {subAdmins.length === 0 && (
            <div className="p-8 text-sm text-muted-foreground text-center">
              No sub-admins yet. Set someone's access level to “Sub-admin” in the Team tab, then choose what they cover here.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function UnitList({ title, units, value, setValue, onAdd, onRemove, testid }) {
  return (
    <div className="border border-border bg-card" data-testid={`${testid}-card`}>
      <div className="p-4 border-b border-border flex items-center justify-between">
        <span className="label-overline">{title}</span>
        <span className="font-mono text-xs text-muted-foreground">{units.length}</span>
      </div>
      <div className="p-4 border-b border-border flex items-center gap-2">
        <input value={value} onChange={e => setValue(e.target.value)} onKeyDown={e => e.key === "Enter" && onAdd()}
          placeholder={`Add ${title.split(" ")[0].toLowerCase()}`} data-testid={`${testid}-input`}
          className="flex-1 bg-background border border-border px-3 py-2 text-sm"/>
        <button onClick={onAdd} data-testid={`${testid}-add`}
          className="bg-foreground text-background px-3 py-2 hover:bg-primary transition-colors"><Plus size={16} weight="bold"/></button>
      </div>
      <div className="divide-y divide-border max-h-[320px] overflow-y-auto">
        {units.map(u => (
          <div key={u.unit_id} className="p-3 flex items-center justify-between" data-testid={`${testid}-row-${u.unit_id}`}>
            <span className="text-sm">{u.name}</span>
            <button onClick={() => onRemove(u)} className="text-muted-foreground hover:text-[#FF3B30]" data-testid={`${testid}-delete-${u.unit_id}`}>
              <Trash size={14} weight="bold"/>
            </button>
          </div>
        ))}
        {units.length === 0 && <div className="p-6 text-sm text-muted-foreground">Nothing added yet.</div>}
      </div>
    </div>
  );
}

function ScopeRow({ manager, org, onSaved }) {
  const [depts, setDepts] = useState(manager.managed_departments || []);
  const [sites, setSites] = useState(manager.managed_sites || []);
  const [saving, setSaving] = useState(false);

  const toggle = (list, setList, name) =>
    setList(list.includes(name) ? list.filter(x => x !== name) : [...list, name]);

  const save = async () => {
    setSaving(true);
    try {
      await api.patch(`/admin/employees/${manager.user_id}/scope`, { managed_departments: depts, managed_sites: sites });
      toast.success(`${manager.name}'s coverage saved`);
      onSaved();
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not save"); }
    finally { setSaving(false); }
  };

  return (
    <div className="p-4" data-testid={`scope-${manager.user_id}`}>
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="text-sm font-medium">{manager.name}</div>
        <button onClick={save} disabled={saving} data-testid={`save-scope-${manager.user_id}`}
          className="text-[10px] label-overline border border-border px-2 py-1 hover:border-foreground disabled:opacity-50">Save coverage</button>
      </div>
      <div className="mt-3 grid sm:grid-cols-2 gap-3">
        <div>
          <div className="label-overline mb-1.5">Departments</div>
          <div className="flex flex-wrap gap-1.5">
            {org.departments.map(d => (
              <Chip key={d.unit_id} active={depts.includes(d.name)} onClick={() => toggle(depts, setDepts, d.name)} testid={`scope-dept-${manager.user_id}-${d.unit_id}`}>{d.name}</Chip>
            ))}
            {org.departments.length === 0 && <span className="text-xs text-muted-foreground">Add departments first.</span>}
          </div>
        </div>
        <div>
          <div className="label-overline mb-1.5">Sites</div>
          <div className="flex flex-wrap gap-1.5">
            {org.sites.map(s => (
              <Chip key={s.unit_id} active={sites.includes(s.name)} onClick={() => toggle(sites, setSites, s.name)} testid={`scope-site-${manager.user_id}-${s.unit_id}`}>{s.name}</Chip>
            ))}
            {org.sites.length === 0 && <span className="text-xs text-muted-foreground">Add sites first.</span>}
          </div>
        </div>
      </div>
      <p className="text-[10px] text-muted-foreground mt-2">
        They also always see anyone whose “Reports To” is set to them.
      </p>
    </div>
  );
}

const Chip = ({ active, onClick, children, testid }) => (
  <button onClick={onClick} data-testid={testid}
    className={`text-xs px-2 py-1 border transition-colors ${active ? "bg-foreground text-background border-foreground" : "border-border hover:border-foreground"}`}>
    {children}
  </button>
);
