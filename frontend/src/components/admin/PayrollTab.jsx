import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { DownloadSimple, Plus, Trash } from "@phosphor-icons/react";
import PayrollSettings from "@/components/admin/PayrollSettings";
import PayslipDesigner from "@/components/admin/PayslipDesigner";

const field = "bg-background border border-border px-3 py-2 text-sm";
const money = (n) => {
  if (n === null || n === undefined || n === "") return "—";
  const value = Number(n);
  if (Number.isNaN(value)) return String(n);
  return value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

export default function PayrollTab() {
  const [branches, setBranches] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [branchId, setBranchId] = useState("");
  const [month, setMonth] = useState("2026-10");
  const [view, setView] = useState("register");
  const [run, setRun] = useState(null);
  const [lines, setLines] = useState([]);
  const [missing, setMissing] = useState({ structure: [], bank: [] });
  const [selected, setSelected] = useState(null);
  const [ctc, setCtc] = useState("12000");
  const [ctcResult, setCtcResult] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    Promise.all([api.get("/admin/org"), api.get("/admin/employees")]).then(([org, people]) => {
      const sites = org.data.sites || [];
      setBranches(sites);
      setEmployees(people.data.employees || []);
      const stored = sessionStorage.getItem("kelasa-payroll-branch");
      setBranchId(stored && sites.some(s => s.unit_id === stored) ? stored : (sites[0]?.unit_id || ""));
    }).catch(() => toast.error("Could not load branches"));
  }, []);

  useEffect(() => { if (branchId) sessionStorage.setItem("kelasa-payroll-branch", branchId); }, [branchId]);

  const branch = branches.find(b => b.unit_id === branchId);
  const branchPeople = employees.filter(e => e.site === branch?.name);

  const loadRun = async (id) => {
    const r = await api.get(`/payroll/runs/${id}`);
    setRun(r.data.run);
    setLines(r.data.lines || []);
  };

  const openMonth = async () => {
    if (!branchId) return;
    const r = await api.get("/payroll/runs", { params: { branch_id: branchId, month } });
    const latest = (r.data.runs || [])[0];
    if (latest) await loadRun(latest.run_id);
    else { setRun(null); setLines([]); }
  };
  useEffect(() => { openMonth().catch(() => {}); }, [branchId, month]);

  const generate = async () => {
    setBusy(true);
    try {
      const r = await api.post("/payroll/runs/generate", { branch_id: branchId, month });
      setRun(r.data.run);
      setLines(r.data.lines || []);
      setMissing({ structure: r.data.missing_structure || [], bank: r.data.missing_bank || [] });
      toast.success(r.data.existing ? "Opened the existing draft" : "Draft generated");
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not generate"); }
    finally { setBusy(false); }
  };

  const act = async (path, ok) => {
    setBusy(true);
    try {
      await api.post(path);
      await loadRun(run.run_id);
      toast.success(ok);
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not update the payroll"); }
    finally { setBusy(false); }
  };

  const download = async (kind, filename) => {
    try {
      const res = await api.get(`/payroll/runs/${run.run_id}/export`, { params: { kind }, responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url; a.download = filename; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 4000);
    } catch { toast.error("Download failed"); }
  };

  const totals = useMemo(() => lines.reduce((acc, line) => {
    acc.gross += Number(line.gross || 0);
    acc.pt += Number(line.pt || 0);
    acc.ded += Number(line.ded_add || 0);
    acc.final += Number(line.final || 0);
    acc.atc += Number(line.atc || 0);
    acc.ctc += Number(line.ctc || 0);
    return acc;
  }, { gross: 0, pt: 0, ded: 0, final: 0, atc: 0, ctc: 0 }), [lines]);

  const codes = lines[0] ? Object.keys(lines[0].earnings || {}) : ["BASIC", "HRA", "TA"];

  return (
    <div className="space-y-4" data-testid="payroll-tab">
      <div className="flex flex-wrap items-end gap-3">
        <label className="block"><div className="label-overline">Branch</div>
          <select value={branchId} onChange={e => setBranchId(e.target.value)} className={field} data-testid="payroll-branch">
            {branches.map(b => <option key={b.unit_id} value={b.unit_id}>{b.name}</option>)}
          </select>
        </label>
        <label className="block"><div className="label-overline">Month</div>
          <input type="month" value={month} onChange={e => setMonth(e.target.value)} className={field} data-testid="payroll-month"/>
        </label>
        <div className="flex border border-border" data-testid="payroll-views">
          {[["register", "Register"], ["settings", "Branch settings"], ["template", "Payslip template"], ["import", "Import"], ["structures", "Structures"]].map(([id, text]) => (
            <button key={id} onClick={() => setView(id)} data-testid={`payroll-view-${id}`} className={`px-3 py-2 text-xs uppercase tracking-[0.14em] ${view === id ? "bg-foreground text-background" : ""}`}>{text}</button>
          ))}
        </div>
      </div>

      {view === "settings" && <PayrollSettings branchId={branchId} branches={branches}/>}
      {view === "template" && <PayslipDesigner branchId={branchId} branches={branches}/>}
      {view === "import" && <ImportPanel branchId={branchId} month={month}/>}
      {view === "structures" && (
        <Structures branchId={branchId} people={branchPeople} ctc={ctc} setCtc={setCtc} ctcResult={ctcResult} setCtcResult={setCtcResult} month={month}/>
      )}

      {view === "register" && (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <button onClick={generate} disabled={busy || !branchId} data-testid="payroll-generate" className="bg-foreground text-background px-4 py-2 text-sm">Generate draft</button>
            {run?.status === "draft" && <button onClick={() => act(`/payroll/runs/${run.run_id}/approve`, "Approved")} data-testid="payroll-approve" className="border border-border px-3 py-2 text-sm">Approve</button>}
            {run?.status === "approved" && <button onClick={() => act(`/payroll/runs/${run.run_id}/publish`, "Published")} data-testid="payroll-publish" className="bg-[#0047FF] text-white px-3 py-2 text-sm">Publish</button>}
            {run?.status === "published" && <button onClick={async () => { setBusy(true); try { const r = await api.post(`/payroll/runs/${run.run_id}/revise`); setRun(r.data.run); setLines(r.data.lines || []); toast.success("Revision opened"); } catch (e) { toast.error(e?.response?.data?.detail || "Could not revise"); } finally { setBusy(false); } }} data-testid="payroll-revise" className="border border-border px-3 py-2 text-sm">Revise</button>}
            {run && <button onClick={() => download("register", `salary-${month}.xlsx`)} data-testid="payroll-download-register" className="border border-border px-3 py-2 text-sm inline-flex items-center gap-1"><DownloadSimple size={14}/> Register</button>}
            {run && <button onClick={() => download("values", `salary-${month}-values.xlsx`)} className="border border-border px-3 py-2 text-sm">Values only</button>}
            {run && <button onClick={() => download("bank", `bank-${month}.csv`)} className="border border-border px-3 py-2 text-sm">Bank file</button>}
            {run && <button onClick={() => download("adjustments", `ded-add-${month}.csv`)} data-testid="payroll-download-adjustments" className="border border-border px-3 py-2 text-sm">DED/ADD</button>}
            {run?.status === "published" && <button onClick={async () => { const res = await api.get(`/payroll/runs/${run.run_id}/payslips.zip`, { responseType: "blob" }); const url = URL.createObjectURL(res.data); const a = document.createElement("a"); a.href = url; a.download = `payslips-${month}.zip`; a.click(); }} className="border border-border px-3 py-2 text-sm">All payslips</button>}
          </div>
          {run && <div className="text-xs uppercase tracking-[0.16em]" data-testid="payroll-status">{run.display_name || branch?.name} · {month} · {run.status}{run.imported ? " · imported" : ""}{run.superseded ? " · superseded" : ""} · v{run.version}</div>}
          {(missing.structure.length > 0 || missing.bank.length > 0) && (
            <div className="border border-[#FF3B30]/40 bg-[#FF3B30]/5 p-3 text-sm" data-testid="payroll-missing">
              {missing.structure.length > 0 && <div>No salary structure: {missing.structure.map(p => p.name).join(", ")}</div>}
              {missing.bank.length > 0 && <div>No bank account: {missing.bank.map(p => p.name).join(", ")}</div>}
            </div>
          )}
          <div className="overflow-x-auto border border-border bg-card" data-testid="payroll-register">
            <table className="text-xs min-w-max w-full">
              <thead className="bg-[#0D0D12] text-white">
                <tr>{["SL", "Name", "A/C", "UAN", "NWD", "NDP", ...codes, "GROSS", "(E)ESI R", "ESI R", "E(PF) R", "PF (R)", "PT", "DED/ADD", "FINAL", "ATC", "CTC"].map(h => <th key={h} className="px-2 py-2 text-left font-medium whitespace-nowrap">{h}</th>)}</tr>
              </thead>
              <tbody>
                {lines.map((line, index) => (
                  <tr key={line.line_id} onClick={() => setSelected(line)} data-testid={`payroll-row-${index}`} className={`border-t border-border cursor-pointer ${selected?.line_id === line.line_id ? "bg-[#0047FF]/10" : "hover:bg-secondary"}`}>
                    <td className="px-2 py-1.5">{index + 1}</td>
                    <td className="px-2 py-1.5 whitespace-nowrap">{line.name} {(line.overridden || []).length > 0 && <span className="ml-1 border border-border px-1 text-[9px] uppercase" data-testid="payroll-overridden">Overridden</span>}{line.warnings?.length > 0 && <span className="ml-1 text-[#FF3B30]">!</span>}</td>
                    <td className="px-2 py-1.5 font-mono">{line.account_masked}</td>
                    <td className="px-2 py-1.5 font-mono">{line.uan || ""}</td>
                    <td className="px-2 py-1.5">{line.nwd}</td>
                    <td className="px-2 py-1.5">{line.ndp}{line.ndp_overridden ? "*" : ""}</td>
                    {codes.map(code => <td key={code} className="px-2 py-1.5 text-right">{money(line.earnings?.[code])}</td>)}
                    <td className="px-2 py-1.5 text-right">{money(line.gross)}</td>
                    <td className="px-2 py-1.5 text-right">{line.e_esi_r}</td>
                    <td className="px-2 py-1.5 text-right">{line.esi_r}</td>
                    <td className="px-2 py-1.5 text-right">{line.e_pf_r}</td>
                    <td className="px-2 py-1.5 text-right">{line.pf_r}</td>
                    <td className="px-2 py-1.5 text-right">{line.pt}</td>
                    <td className="px-2 py-1.5 text-right">{money(line.ded_add)}</td>
                    <td className="px-2 py-1.5 text-right">{money(line.final)}</td>
                    <td className="px-2 py-1.5 text-right">{line.atc}</td>
                    <td className="px-2 py-1.5 text-right">{money(line.ctc)}</td>
                  </tr>
                ))}
                {lines.length > 0 && (
                  <tr className="border-t-2 border-foreground font-medium" data-testid="payroll-totals">
                    <td className="px-2 py-2" colSpan={4}>Total · {lines.length}</td>
                    <td/><td/>
                    {codes.map(code => <td key={code}/>)}
                    <td className="px-2 py-2 text-right">{money(totals.gross)}</td>
                    <td colSpan={4}/>
                    <td className="px-2 py-2 text-right">{money(totals.pt)}</td>
                    <td className="px-2 py-2 text-right">{money(totals.ded)}</td>
                    <td className="px-2 py-2 text-right">{money(totals.final)}</td>
                    <td className="px-2 py-2 text-right">{money(totals.atc)}</td>
                    <td className="px-2 py-2 text-right">{money(totals.ctc)}</td>
                  </tr>
                )}
              </tbody>
            </table>
            {lines.length === 0 && <div className="p-8 text-sm text-muted-foreground text-center">No payroll for this branch and month yet.</div>}
          </div>
          {selected && run?.status === "draft" && <LineEditor line={selected} onSaved={async (updated) => { setLines(rows => rows.map(row => row.line_id === updated.line_id ? updated : row)); setSelected(updated); }}/>}
          {selected && run?.status !== "draft" && <div className="text-sm text-muted-foreground">This version is locked. Revise a published month to edit it.</div>}
        </div>
      )}
    </div>
  );
}

function LineEditor({ line, onSaved }) {
  const [ndp, setNdp] = useState(String(line.ndp ?? ""));
  const [reason, setReason] = useState(line.ndp_reason || "");
  const [items, setItems] = useState(line.adjustments || []);
  const [pt, setPt] = useState(line.pt_override || "branch");
  const [esiOn, setEsiOn] = useState(line.esi_applicable !== false);
  const [pfOn, setPfOn] = useState(line.pf_applicable !== false);
  useEffect(() => {
    setNdp(String(line.ndp ?? "")); setReason(line.ndp_reason || ""); setItems(line.adjustments || []);
    setPt(line.pt_override || "branch"); setEsiOn(line.esi_applicable !== false); setPfOn(line.pf_applicable !== false);
  }, [line.line_id]);

  const save = async () => {
    if (items.some(item => !(item.label || "").trim())) { toast.error("Each deduction or addition needs a reason"); return; }
    try {
      const r = await api.patch(`/payroll/runs/${line.run_id}/lines/${line.line_id}`, { ndp, ndp_reason: reason, adjustments: items, pt_override: pt, esi_applicable: esiOn, pf_applicable: pfOn });
      toast.success("Line updated");
      onSaved(r.data);
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not save"); }
  };

  return (
    <div className="border border-border bg-card p-4 space-y-3" data-testid="payroll-line-editor">
      <div className="font-medium">{line.name}</div>
      {(line.warnings || []).map((w, i) => <div key={i} className="text-sm text-[#FF3B30]">{w}</div>)}
      <div className="flex flex-wrap gap-3 items-end">
        <label className="block"><div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Days paid</div><input value={ndp} onChange={e => setNdp(e.target.value)} className={field} data-testid="payroll-ndp"/></label>
        <label className="block flex-1 min-w-[12rem]"><div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Reason if you override</div><input value={reason} onChange={e => setReason(e.target.value)} className={`${field} w-full`} data-testid="payroll-ndp-reason"/></label>
        <label className="block"><div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">PT</div>
          <select value={pt} onChange={e => setPt(e.target.value)} className={field} data-testid="payroll-pt-override"><option value="branch">Branch rule</option><option value="none">None</option><option value="fixed">Fixed</option></select>
        </label>
        <label className="text-sm flex items-center gap-2"><input type="checkbox" checked={esiOn} onChange={e => setEsiOn(e.target.checked)}/> ESI</label>
        <label className="text-sm flex items-center gap-2"><input type="checkbox" checked={pfOn} onChange={e => setPfOn(e.target.checked)}/> PF</label>
      </div>
      <div className="space-y-2" data-testid="payroll-adjustments">
        {items.map((item, index) => (
          <div key={index} className="flex flex-wrap gap-2">
            <select value={item.type} onChange={e => setItems(items.map((it, i) => i === index ? { ...it, type: e.target.value } : it))} className={field}><option value="deduction">Deduction</option><option value="addition">Addition</option></select>
            <input value={item.amount} onChange={e => setItems(items.map((it, i) => i === index ? { ...it, amount: e.target.value } : it))} className={`${field} w-28`} placeholder="Amount"/>
            <input value={item.label || ""} onChange={e => setItems(items.map((it, i) => i === index ? { ...it, label: e.target.value } : it))} className={`${field} flex-1 min-w-[10rem]`} placeholder="Reason" data-testid={`payroll-adj-reason-${index}`}/>
            <button onClick={() => setItems(items.filter((_, i) => i !== index))} className="border border-border px-2" aria-label="Remove item"><Trash size={14}/></button>
          </div>
        ))}
        <button onClick={() => setItems([...items, { type: "deduction", amount: "", label: "", category: "Other" }])} className="text-xs border border-border px-2 py-1 inline-flex items-center gap-1" data-testid="payroll-add-adjustment"><Plus size={12}/> Add DED/ADD</button>
      </div>
      <button onClick={save} data-testid="payroll-line-save" className="bg-foreground text-background px-4 py-2 text-sm">Update line</button>
    </div>
  );
}

function Structures({ branchId, people, ctc, setCtc, ctcResult, setCtcResult, month }) {
  const [userId, setUserId] = useState("");
  const [fixed, setFixed] = useState({ BASIC: "", HRA: "", TA: "" });
  const [esi, setEsi] = useState(true);
  const preview = async () => {
    try {
      const r = await api.post("/payroll/structures/preview-ctc", { monthly_ctc: ctc, esi_applicable: esi, branch_id: branchId, month });
      setCtcResult(r.data);
      setFixed({ BASIC: r.data.fixed.BASIC, HRA: r.data.fixed.HRA, TA: r.data.fixed.TA });
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not build the structure"); }
  };
  const save = async () => {
    if (!userId) { toast.error("Choose an employee"); return; }
    try {
      await api.post("/payroll/structures", { user_id: userId, branch_id: branchId, effective_from: `${month}-01`, fixed, monthly_ctc: ctc, esi_applicable: esi, pf_applicable: true, pt_override: "branch" });
      toast.success("Salary structure saved as a new version");
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not save"); }
  };
  return (
    <div className="border border-border bg-card p-4 space-y-3" data-testid="payroll-structures">
      <div className="label-overline">Salary structure</div>
      <div className="flex flex-wrap gap-3 items-end">
        <label className="block"><div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Employee</div>
          <select value={userId} onChange={e => setUserId(e.target.value)} className={field} data-testid="payroll-structure-employee"><option value="">Select</option>{people.map(p => <option key={p.user_id} value={p.user_id}>{p.name}</option>)}</select>
        </label>
        <label className="block"><div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Monthly CTC</div><input value={ctc} onChange={e => setCtc(e.target.value)} className={field} data-testid="payroll-ctc"/></label>
        <label className="text-sm flex items-center gap-2"><input type="checkbox" checked={esi} onChange={e => setEsi(e.target.checked)}/> ESI applicable</label>
        <button onClick={preview} className="border border-border px-3 py-2 text-sm" data-testid="payroll-ctc-preview">Build from CTC</button>
        <button onClick={save} className="bg-foreground text-background px-3 py-2 text-sm" data-testid="payroll-structure-save">Save new version</button>
      </div>
      <div className="grid grid-cols-3 gap-3">
        {["BASIC", "HRA", "TA"].map(code => (
          <label key={code} className="block"><div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">{code === "TA" ? "Travel Allowance" : code}</div>
            <input value={fixed[code]} onChange={e => setFixed({ ...fixed, [code]: e.target.value })} className={`${field} w-full`} data-testid={`payroll-fixed-${code}`}/>
          </label>
        ))}
      </div>
      {ctcResult && <div className="text-sm" data-testid="payroll-ctc-result">Provisional gross {ctcResult.provisional_gross} · PT {ctcResult.pt} · TA {ctcResult.fixed.TA}</div>}
    </div>
  );
}

function ImportPanel({ branchId, month }) {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [sheet, setSheet] = useState("");
  const load = async () => {
    if (!file) return;
    const b64 = await fileToB64(file);
    try {
      const r = await api.post("/payroll/import/preview", { branch_id: branchId, file_b64: b64 });
      setPreview(r.data);
      setSheet(r.data.sheets?.[0]?.sheet || "");
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not read the workbook"); }
  };
  const current = (preview?.sheets || []).find(s => s.sheet === sheet);
  return (
    <div className="border border-border bg-card p-4 space-y-3" data-testid="payroll-import">
      <div className="label-overline">Import a past month</div>
      <p className="text-sm text-muted-foreground">Values are stored as they appear on the sheet. The old SA column is saved as Travel Allowance. A single DED/ADD figure is kept as one item labelled Imported.</p>
      <input type="file" accept=".xlsx" onChange={e => setFile(e.target.files?.[0] || null)} data-testid="payroll-import-file"/>
      <button onClick={load} className="border border-border px-3 py-2 text-sm" data-testid="payroll-import-preview">Preview</button>
      {preview && (
        <label className="block"><div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Sheet</div>
          <select value={sheet} onChange={e => setSheet(e.target.value)} className={field}>{preview.sheets.map(s => <option key={s.sheet} value={s.sheet}>{s.sheet} {s.month ? `(${s.month})` : ""}</option>)}</select>
        </label>
      )}
      {current && <div className="text-sm" data-testid="payroll-import-summary">{current.row_count} rows · {current.matched.length} matched · {current.unmatched.length} unmatched{current.month ? ` · detected ${current.month}` : ""}</div>}
    </div>
  );
}

function fileToB64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1]);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}
