import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { ArrowDown, ArrowUp, Copy, Plus, Trash } from "@phosphor-icons/react";

const field = "bg-background border border-border px-3 py-2 text-sm w-full";
const label = "text-[10px] uppercase tracking-[0.16em] text-muted-foreground";
const emptyComponent = () => ({ code: "", name: "", payslip_label: "", show_on_payslip: true, prorate: true, esi_base: false, pf_base: false });

export default function PayrollSettings({ branchId, branches }) {
  const [settings, setSettings] = useState(null);
  const [month, setMonth] = useState(() => new Date().toISOString().slice(0, 7));
  const [copyFrom, setCopyFrom] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => {
    if (!branchId) return;
    api.get("/payroll/settings", { params: { branch_id: branchId, month } })
      .then(r => setSettings(structuredClone(r.data.current.settings)))
      .catch(() => toast.error("Could not load payroll settings"));
  };
  useEffect(() => { load(); }, [branchId, month]);

  const set = (path, value) => {
    setSettings(prev => {
      const next = structuredClone(prev);
      const parts = path.split(".");
      let cursor = next;
      for (let i = 0; i < parts.length - 1; i++) cursor = cursor[parts[i]];
      cursor[parts[parts.length - 1]] = value;
      return next;
    });
  };

  const save = async () => {
    setBusy(true);
    try {
      await api.put("/payroll/settings", { branch_id: branchId, effective_month: month, settings });
      toast.success(`Payroll settings saved for ${month}`);
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not save"); }
    finally { setBusy(false); }
  };

  const copy = async () => {
    if (!copyFrom) return;
    setBusy(true);
    try {
      await api.post("/payroll/settings/copy", { from_branch_id: copyFrom, to_branch_id: branchId, effective_month: month });
      toast.success("Settings copied");
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not copy"); }
    finally { setBusy(false); }
  };

  const move = (index, dir) => {
    const items = [...settings.earning_components];
    const next = index + dir;
    if (next < 0 || next >= items.length) return;
    [items[index], items[next]] = [items[next], items[index]];
    set("earning_components", items);
  };

  if (!settings) return <div className="loading-bar" data-testid="payroll-settings-loading"/>;
  const profile = settings.profile || {};
  const components = settings.earning_components || [];

  return (
    <div className="space-y-6" data-testid="payroll-settings">
      <div className="flex flex-wrap items-end gap-3">
        <label className="block">
          <div className={label}>Effective month</div>
          <input type="month" value={month} onChange={e => setMonth(e.target.value)} className={field} data-testid="payroll-settings-month"/>
        </label>
        <button onClick={save} disabled={busy} data-testid="payroll-settings-save" className="bg-foreground text-background px-4 py-2 text-sm">Save settings</button>
        <div className="flex items-end gap-2 ml-auto">
          <label className="block">
            <div className={label}>Copy from</div>
            <select value={copyFrom} onChange={e => setCopyFrom(e.target.value)} className={field} data-testid="payroll-copy-from">
              <option value="">Another branch</option>
              {branches.filter(b => b.unit_id !== branchId).map(b => <option key={b.unit_id} value={b.unit_id}>{b.name}</option>)}
            </select>
          </label>
          <button onClick={copy} disabled={!copyFrom || busy} data-testid="payroll-copy-settings" className="border border-border px-3 py-2 text-sm inline-flex items-center gap-1"><Copy size={14}/> Copy</button>
        </div>
      </div>

      <section className="border border-border bg-card p-4 space-y-3">
        <div className="label-overline">Branch payroll profile</div>
        <div className="grid sm:grid-cols-2 gap-3">
          <Field label="Legal entity name" value={profile.legal_name || ""} onChange={v => set("profile.legal_name", v)} testid="payroll-legal-name"/>
          <Field label="Display name" value={profile.display_name || ""} onChange={v => set("profile.display_name", v)} testid="payroll-display-name"/>
          <Field label="PF establishment code" value={profile.pf_establishment_code || ""} onChange={v => set("profile.pf_establishment_code", v)} testid="payroll-pf-code"/>
          <Field label="ESI code" value={profile.esi_code || ""} onChange={v => set("profile.esi_code", v)} testid="payroll-esi-code"/>
          <Field label="PT registration" value={profile.pt_registration || ""} onChange={v => set("profile.pt_registration", v)} testid="payroll-pt-reg"/>
        </div>
        <label className="block">
          <div className={label}>Address</div>
          <textarea value={profile.address || ""} onChange={e => set("profile.address", e.target.value)} className={field} rows={3} data-testid="payroll-address"/>
        </label>
      </section>

      <section className="border border-border bg-card">
        <div className="p-4 border-b border-border flex items-center justify-between">
          <div className="label-overline">Earning components</div>
          <button data-testid="payroll-add-component" onClick={() => set("earning_components", [...components, emptyComponent()])} className="border border-border px-2 py-1 text-xs inline-flex items-center gap-1"><Plus size={12}/> Add</button>
        </div>
        <div className="divide-y divide-border">
          {components.map((comp, index) => (
            <div key={index} className="p-3 grid lg:grid-cols-12 gap-2 items-end" data-testid={`payroll-component-${index}`}>
              <label className="lg:col-span-2 block"><div className={label}>Code</div><input value={comp.code} onChange={e => { const n = [...components]; n[index] = { ...comp, code: e.target.value.toUpperCase() }; set("earning_components", n); }} className={field}/></label>
              <label className="lg:col-span-3 block"><div className={label}>Name</div><input value={comp.name} onChange={e => { const n = [...components]; n[index] = { ...comp, name: e.target.value }; set("earning_components", n); }} className={field}/></label>
              <label className="lg:col-span-3 block"><div className={label}>Payslip label</div><input value={comp.payslip_label || ""} onChange={e => { const n = [...components]; n[index] = { ...comp, payslip_label: e.target.value }; set("earning_components", n); }} className={field}/></label>
              <label className="text-xs flex items-center gap-1"><input type="checkbox" checked={!!comp.prorate} onChange={e => { const n = [...components]; n[index] = { ...comp, prorate: e.target.checked }; set("earning_components", n); }}/> Prorate</label>
              <label className="text-xs flex items-center gap-1"><input type="checkbox" checked={!!comp.esi_base} onChange={e => { const n = [...components]; n[index] = { ...comp, esi_base: e.target.checked }; set("earning_components", n); }}/> ESI base</label>
              <label className="text-xs flex items-center gap-1"><input type="checkbox" checked={!!comp.pf_base} onChange={e => { const n = [...components]; n[index] = { ...comp, pf_base: e.target.checked }; set("earning_components", n); }}/> PF base</label>
              <div className="flex gap-1">
                <button type="button" onClick={() => move(index, -1)} className="border border-border p-1" aria-label="Move up"><ArrowUp size={12}/></button>
                <button type="button" onClick={() => move(index, 1)} className="border border-border p-1" aria-label="Move down"><ArrowDown size={12}/></button>
                <button type="button" onClick={() => set("earning_components", components.filter((_, i) => i !== index))} className="border border-border p-1" aria-label="Remove"><Trash size={12}/></button>
              </div>
            </div>
          ))}
        </div>
      </section>

      <div className="grid lg:grid-cols-2 gap-4">
        <RateCard title="ESI" testid="payroll-esi" value={settings.esi} onChange={v => set("esi", v)} extra="gross"/>
        <RateCard title="PF" testid="payroll-pf" value={settings.pf} onChange={v => set("pf", v)} extra="ceiling"/>
      </div>

      <section className="border border-border bg-card p-4 space-y-3" data-testid="payroll-pt">
        <div className="label-overline">Professional tax</div>
        <p className="text-sm text-muted-foreground">Default: ₹200 when the month's gross is ₹25,000 or more, otherwise ₹0. The amount is not prorated unless you turn that on.</p>
        <div className="grid sm:grid-cols-3 gap-3">
          <label className="block"><div className={label}>Mode</div>
            <select value={settings.pt.mode} onChange={e => set("pt.mode", e.target.value)} className={field} data-testid="payroll-pt-mode">
              <option value="threshold">Threshold</option>
              <option value="slabs">Slabs</option>
            </select>
          </label>
          <Field label="Threshold (₹)" value={settings.pt.threshold} onChange={v => set("pt.threshold", v)} testid="payroll-pt-threshold"/>
          <Field label="Amount (₹)" value={settings.pt.amount} onChange={v => set("pt.amount", v)} testid="payroll-pt-amount"/>
          <label className="block"><div className={label}>Evaluate on</div>
            <select value={settings.pt.base} onChange={e => set("pt.base", e.target.value)} className={field}>
              <option value="gross">Month gross</option>
              <option value="fixed_gross">Fixed monthly gross</option>
            </select>
          </label>
          <label className="text-sm flex items-center gap-2"><input type="checkbox" checked={!!settings.pt.prorate} onChange={e => set("pt.prorate", e.target.checked)} data-testid="payroll-pt-prorate"/> Prorate PT by attendance</label>
        </div>
        {settings.pt.mode === "slabs" && <SlabEditor slabs={settings.pt.slabs || []} onChange={slabs => set("pt.slabs", slabs)}/>}
      </section>

      <section className="border border-border bg-card p-4 grid sm:grid-cols-2 gap-3">
        <div className="label-overline sm:col-span-2">Who pays, and how the month is counted</div>
        <label className="text-sm flex items-center gap-2"><input type="checkbox" checked={!!settings.bearer.employee_pf_esi_deducted} onChange={e => set("bearer.employee_pf_esi_deducted", e.target.checked)} data-testid="payroll-deduct-pf-esi"/> Deduct employee PF and ESI from pay</label>
        <label className="text-sm flex items-center gap-2"><input type="checkbox" checked={!!settings.bearer.pt_deducted} onChange={e => set("bearer.pt_deducted", e.target.checked)} data-testid="payroll-deduct-pt"/> Deduct professional tax from pay</label>
        <label className="block"><div className={label}>Days in month</div>
          <select value={settings.proration} onChange={e => set("proration", e.target.value)} className={field} data-testid="payroll-proration">
            <option value="calendar">Calendar days</option>
            <option value="fixed_30">Fixed 30 days</option>
            <option value="working_days">Working days, excluding weekly offs</option>
          </select>
        </label>
        <label className="block"><div className={label}>Final pay rounding</div>
          <select value={settings.final_rounding} onChange={e => set("final_rounding", e.target.value)} className={field} data-testid="payroll-final-rounding">
            <option value="roundup">Round up</option>
            <option value="nearest">Nearest rupee</option>
            <option value="down">Round down</option>
            <option value="none">None</option>
          </select>
        </label>
        <Field label="CTC builder — basic % of CTC" value={settings.ctc_builder.basic_pct} onChange={v => set("ctc_builder.basic_pct", v)} testid="payroll-basic-pct"/>
        <Field label="CTC builder — HRA % of basic" value={settings.ctc_builder.hra_pct_of_basic} onChange={v => set("ctc_builder.hra_pct_of_basic", v)} testid="payroll-hra-pct"/>
        <button type="button" onClick={() => set("register_columns", null)} className="border border-border px-3 py-2 text-sm" data-testid="payroll-reset-columns">Reset register columns to default</button>
      </section>
    </div>
  );
}

function Field({ label: text, value, onChange, testid }) {
  return (
    <label className="block">
      <div className={label}>{text}</div>
      <input value={value ?? ""} onChange={e => onChange(e.target.value)} className={field} data-testid={testid}/>
    </label>
  );
}

function RateCard({ title, value, onChange, extra, testid }) {
  const patch = (key, val) => onChange({ ...value, [key]: val });
  const limitKey = extra === "gross" ? "gross_limit_enabled" : "ceiling_enabled";
  const amountKey = extra === "gross" ? "gross_limit" : "ceiling";
  return (
    <section className="border border-border bg-card p-4 space-y-3" data-testid={testid}>
      <div className="flex items-center justify-between">
        <div className="label-overline">{title}</div>
        <label className="text-sm flex items-center gap-2"><input type="checkbox" checked={!!value.enabled} onChange={e => patch("enabled", e.target.checked)}/> On</label>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Employer rate" value={value.employer_rate} onChange={v => patch("employer_rate", v)}/>
        <Field label="Employee rate" value={value.employee_rate} onChange={v => patch("employee_rate", v)}/>
        <label className="block"><div className={label}>Base</div>
          <select value={value.base} onChange={e => patch("base", e.target.value)} className={field}>
            <option value="basic">Basic</option>
            <option value="gross">Gross</option>
          </select>
        </label>
        <label className="block"><div className={label}>Rounding</div>
          <select value={value.rounding} onChange={e => patch("rounding", e.target.value)} className={field}>
            <option value="roundup">Round up</option>
            <option value="nearest">Nearest</option>
            <option value="down">Round down</option>
            <option value="none">None</option>
          </select>
        </label>
      </div>
      <label className="text-sm flex items-center gap-2">
        <input type="checkbox" checked={!!value[limitKey]} onChange={e => patch(limitKey, e.target.checked)}/>
        {extra === "gross" ? "Gross eligibility limit" : "Wage ceiling"}
      </label>
      {value[limitKey] && <Field label="Limit (₹)" value={value[amountKey]} onChange={v => patch(amountKey, v)}/>}
    </section>
  );
}

function SlabEditor({ slabs, onChange }) {
  const update = (index, key, value) => onChange(slabs.map((slab, i) => i === index ? { ...slab, [key]: value } : slab));
  return (
    <div className="space-y-2" data-testid="payroll-pt-slabs">
      {slabs.map((slab, index) => (
        <div key={index} className="grid grid-cols-4 gap-2">
          <input placeholder="From" value={slab.from || ""} onChange={e => update(index, "from", e.target.value)} className={field}/>
          <input placeholder="To" value={slab.to || ""} onChange={e => update(index, "to", e.target.value)} className={field}/>
          <input placeholder="Amount" value={slab.amount || ""} onChange={e => update(index, "amount", e.target.value)} className={field}/>
          <input placeholder="February" value={slab.february_amount || ""} onChange={e => update(index, "february_amount", e.target.value)} className={field}/>
        </div>
      ))}
      <button type="button" onClick={() => onChange([...slabs, { from: "0", to: "", amount: "0", february_amount: "" }])} className="text-xs border border-border px-2 py-1">Add slab</button>
    </div>
  );
}
