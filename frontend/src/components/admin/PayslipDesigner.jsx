import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { ArrowDown, ArrowUp, DownloadSimple } from "@phosphor-icons/react";

const field = "bg-background border border-border px-3 py-2 text-sm w-full";
const label = "text-[10px] uppercase tracking-[0.16em] text-muted-foreground";
const SECTION_NAMES = {
  header: "Header", employee: "Employee details", bank: "Bank and statutory", attendance: "Attendance",
  earnings: "Earnings", contributions: "Contributions", adjustments: "DED/ADD items", net: "Net pay",
  employer: "Employer contributions", ytd: "Year to date", footer: "Footer",
};

export default function PayslipDesigner({ branchId, branches }) {
  const [template, setTemplate] = useState(null);
  const [preview, setPreview] = useState(null);
  const [copyFrom, setCopyFrom] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => {
    if (!branchId) return;
    api.get("/payroll/templates", { params: { branch_id: branchId } })
      .then(r => setTemplate(structuredClone(r.data.current.template)))
      .catch(() => toast.error("Could not load the payslip template"));
    api.get("/payroll/templates/preview", { params: { branch_id: branchId } })
      .then(r => setPreview(r.data.line))
      .catch(() => {});
  };
  useEffect(() => { load(); }, [branchId]);

  const save = async () => {
    setBusy(true);
    try {
      await api.put("/payroll/templates", { branch_id: branchId, template });
      toast.success("Payslip template saved");
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not save"); }
    finally { setBusy(false); }
  };

  const download = async () => {
    setBusy(true);
    try {
      const res = await api.post("/payroll/templates/preview.pdf", { branch_id: branchId, template }, { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url; a.download = "sample-payslip.pdf"; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 4000);
    } catch { toast.error("Could not build the sample PDF"); }
    finally { setBusy(false); }
  };

  const duplicate = async () => {
    if (!copyFrom) return;
    setBusy(true);
    try {
      const r = await api.post("/payroll/templates/duplicate", { from_branch_id: copyFrom, to_branch_id: branchId });
      setTemplate(r.data.template);
      toast.success("Template duplicated");
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not duplicate"); }
    finally { setBusy(false); }
  };

  const move = (index, dir) => {
    const sections = [...(template.sections || [])];
    const next = index + dir;
    if (next < 0 || next >= sections.length) return;
    [sections[index], sections[next]] = [sections[next], sections[index]];
    setTemplate({ ...template, sections });
  };

  if (!template) return <div className="loading-bar"/>;

  return (
    <div className="grid lg:grid-cols-2 gap-6" data-testid="payslip-designer">
      <div className="space-y-4">
        <div className="flex flex-wrap gap-2">
          <button onClick={save} disabled={busy} data-testid="payslip-template-save" className="bg-foreground text-background px-4 py-2 text-sm">Save template</button>
          <button onClick={download} disabled={busy} data-testid="payslip-sample-download" className="border border-border px-3 py-2 text-sm inline-flex items-center gap-1"><DownloadSimple size={14}/> Download sample PDF</button>
        </div>
        <div className="border border-border bg-card p-4 space-y-3">
          <div className="label-overline">Header</div>
          <label className="block"><div className={label}>Legal entity</div><input value={template.legal_name || ""} onChange={e => setTemplate({ ...template, legal_name: e.target.value })} className={field} data-testid="payslip-legal-name"/></label>
          <label className="block"><div className={label}>Address</div><textarea value={(template.address_lines || []).join("\n")} onChange={e => setTemplate({ ...template, address_lines: e.target.value.split("\n") })} className={field} rows={3} data-testid="payslip-address"/></label>
          <label className="block"><div className={label}>Header text</div><input value={template.header_text || ""} onChange={e => setTemplate({ ...template, header_text: e.target.value })} className={field}/></label>
          <label className="block"><div className={label}>Footer</div><textarea value={template.footer_text || ""} onChange={e => setTemplate({ ...template, footer_text: e.target.value })} className={field} rows={2}/></label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block"><div className={label}>Signatory</div><input value={template.signatory_name || ""} onChange={e => setTemplate({ ...template, signatory_name: e.target.value })} className={field}/></label>
            <label className="block"><div className={label}>Designation</div><input value={template.signatory_designation || ""} onChange={e => setTemplate({ ...template, signatory_designation: e.target.value })} className={field}/></label>
            <label className="block"><div className={label}>Primary</div><input type="color" value={template.primary || "#0D0D12"} onChange={e => setTemplate({ ...template, primary: e.target.value })} className="h-10 w-full border border-border" data-testid="payslip-primary"/></label>
            <label className="block"><div className={label}>Accent</div><input type="color" value={template.accent || "#0047FF"} onChange={e => setTemplate({ ...template, accent: e.target.value })} className="h-10 w-full border border-border"/></label>
            <label className="block"><div className={label}>Paper</div>
              <select value={template.paper || "A4"} onChange={e => setTemplate({ ...template, paper: e.target.value })} className={field}><option>A4</option><option>A5</option><option>LETTER</option></select>
            </label>
            <label className="block"><div className={label}>Language</div>
              <select value={template.language || "en"} onChange={e => setTemplate({ ...template, language: e.target.value })} className={field} data-testid="payslip-language">
                <option value="en">English</option>
                <option value="en-kn">English + ಕನ್ನಡ</option>
              </select>
            </label>
          </div>
          <label className="text-sm flex items-center gap-2"><input type="checkbox" checked={!!template.no_signature_required} onChange={e => setTemplate({ ...template, no_signature_required: e.target.checked })}/> Computer-generated, no signature required</label>
        </div>
        <div className="border border-border bg-card divide-y divide-border" data-testid="payslip-sections">
          {(template.sections || []).map((section, index) => (
            <div key={section.id} className="px-3 py-2 flex items-center gap-2">
              <input type="checkbox" checked={section.show !== false} onChange={e => {
                const sections = template.sections.map((item, i) => i === index ? { ...item, show: e.target.checked } : item);
                setTemplate({ ...template, sections });
              }} data-testid={`payslip-section-${section.id}`}/>
              <span className="text-sm flex-1">{SECTION_NAMES[section.id] || section.id}</span>
              <button onClick={() => move(index, -1)} className="border border-border p-1" aria-label="Move up"><ArrowUp size={12}/></button>
              <button onClick={() => move(index, 1)} className="border border-border p-1" aria-label="Move down"><ArrowDown size={12}/></button>
            </div>
          ))}
        </div>
        <div className="flex items-end gap-2">
          <label className="block flex-1"><div className={label}>Duplicate from</div>
            <select value={copyFrom} onChange={e => setCopyFrom(e.target.value)} className={field} data-testid="payslip-duplicate-from">
              <option value="">Another branch</option>
              {branches.filter(b => b.unit_id !== branchId).map(b => <option key={b.unit_id} value={b.unit_id}>{b.name}</option>)}
            </select>
          </label>
          <button onClick={duplicate} disabled={!copyFrom} className="border border-border px-3 py-2 text-sm" data-testid="payslip-duplicate">Duplicate</button>
        </div>
      </div>
      <PayslipPreview template={template} line={preview}/>
    </div>
  );
}

export function PayslipPreview({ template, line }) {
  if (!line) return <div className="border border-border bg-card p-6 text-sm text-muted-foreground" data-testid="payslip-preview">Loading sample…</div>;
  const kn = template?.language === "en-kn";
  const shown = (id) => (template?.sections || []).find(s => s.id === id)?.show !== false;
  const money = (n) => `₹${Number(n || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  return (
    <article className="border border-border bg-white text-[#0D0D12] p-6 space-y-4" data-testid="payslip-preview" style={{ borderTop: `4px solid ${template?.accent || "#0047FF"}` }}>
      {shown("header") && (
        <header>
          <div className="text-lg font-semibold" data-testid="payslip-preview-legal">{template?.legal_name || line.legal_name || "Payslip"}</div>
          {(template?.address_lines || []).filter(Boolean).map((row, i) => <div key={i} className="text-xs text-[#52525B]">{row}</div>)}
          <div className="text-sm mt-2">Payslip for October 2026</div>
        </header>
      )}
      {shown("employee") && <Pairs rows={[["Name", line.name], ["Employee code", line.employee_code], ["Designation", line.designation], ["Department", line.department], ["Branch", line.branch_name], ["Date of joining", line.date_of_joining], ["PAN", line.pan]]}/>}
      {shown("bank") && <Pairs rows={[["UAN", line.uan], ["ESI number", line.esi_number], ["Bank", line.bank_name], ["Account", line.account_masked], ["IFSC", line.ifsc]]}/>}
      {shown("earnings") && (
        <table className="w-full text-sm">
          <thead><tr className="text-left text-[10px] uppercase tracking-[0.14em] text-[#52525B]"><th>Component</th><th className="text-right">Fixed</th><th className="text-right">This month</th></tr></thead>
          <tbody>
            {Object.entries(line.earnings || {}).map(([code, amount]) => (
              <tr key={code} className="border-t border-[#E4E4E7]">
                <td className="py-1">{line.component_labels?.[code] || code}{kn && code === "TA" ? " / ಪ್ರಯಾಣ ಭತ್ಯೆ" : ""}</td>
                <td className="text-right">{money(line.fixed?.[code])}</td>
                <td className="text-right">{money(amount)}</td>
              </tr>
            ))}
            <tr className="border-t border-[#0D0D12] font-medium"><td>Gross</td><td/><td className="text-right">{money(line.gross)}</td></tr>
          </tbody>
        </table>
      )}
      {shown("adjustments") && (
        <div>
          <div className="text-[10px] uppercase tracking-[0.14em] text-[#52525B] mb-1">Deductions and additions</div>
          {(line.adjustments || []).map((item, i) => (
            <div key={i} className="flex justify-between text-sm border-t border-[#E4E4E7] py-1" data-testid={`payslip-preview-item-${i}`}>
              <span className="capitalize">{item.type}</span>
              <span>{money(item.amount)}</span>
              <span>{item.label}</span>
            </div>
          ))}
        </div>
      )}
      {shown("net") && <div className="text-sm font-medium" data-testid="payslip-preview-net">Net pay {money(line.atc)}</div>}
      {shown("footer") && <footer className="text-xs text-[#52525B]">{template?.no_signature_required ? "Computer-generated, no signature required." : template?.signatory_name} {template?.footer_text}</footer>}
    </article>
  );
}

function Pairs({ rows }) {
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
      {rows.map(([k, v]) => (
        <div key={k} className="contents"><dt className="text-[#52525B]">{k}</dt><dd>{v || "—"}</dd></div>
      ))}
    </dl>
  );
}
