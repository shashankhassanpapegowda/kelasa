import { useEffect, useState } from "react";
import AppHeader from "@/components/AppHeader";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { DownloadSimple } from "@phosphor-icons/react";

const money = (n) => Number(n || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const monthName = (ym) => {
  if (!ym) return "";
  const [y, m] = ym.split("-");
  return new Date(Number(y), Number(m) - 1, 1).toLocaleDateString("en-IN", { month: "long", year: "numeric" });
};

export default function SalaryPage() {
  const [data, setData] = useState({ payslips: [], structure: null });
  const [fy, setFy] = useState(String(new Date().getMonth() >= 3 ? new Date().getFullYear() : new Date().getFullYear() - 1));
  const [queryFor, setQueryFor] = useState(null);
  const [message, setMessage] = useState("");

  const load = () => api.get("/me/payslips").then(r => setData(r.data)).catch(() => toast.error("Could not load salary"));
  useEffect(() => { load(); }, []);

  const download = async (line) => {
    try {
      const res = await api.get(`/me/payslips/${line.line_id}.pdf`, { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url; a.download = `payslip-${line.month}.pdf`; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 4000);
    } catch { toast.error("Could not download the payslip"); }
  };

  const zip = async () => {
    try {
      const res = await api.get(`/me/payslips/financial-year/${fy}.zip`, { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url; a.download = `payslips-${fy}.zip`; a.click();
    } catch { toast.error("Could not download the year"); }
  };

  const send = async () => {
    if (!message.trim()) return;
    try {
      await api.post(`/me/payslips/${queryFor.line_id}/query`, { message });
      toast.success("Query sent to the admin");
      setQueryFor(null); setMessage("");
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not send"); }
  };

  const fixed = data.structure?.fixed || {};

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <AppHeader/>
      <main className="flex-1 px-4 sm:px-6 py-6 space-y-6 max-w-3xl">
        <div>
          <div className="label-overline">Salary</div>
          <h1 className="text-3xl font-semibold tracking-tight mt-1">Payslips</h1>
        </div>
        <section className="border border-border bg-card p-4" data-testid="salary-structure">
          <div className="label-overline mb-2">Monthly structure</div>
          {data.structure ? (
            <div className="grid grid-cols-3 gap-3 text-sm">
              <div><div className="text-muted-foreground text-xs">Basic</div><div data-testid="salary-basic">₹{money(fixed.BASIC)}</div></div>
              <div><div className="text-muted-foreground text-xs">HRA</div><div>₹{money(fixed.HRA)}</div></div>
              <div><div className="text-muted-foreground text-xs">Travel Allowance</div><div data-testid="salary-ta">₹{money(fixed.TA)}</div></div>
            </div>
          ) : <div className="text-sm text-muted-foreground">No salary structure has been saved yet.</div>}
        </section>
        <section className="border border-border bg-card" data-testid="salary-list">
          <div className="p-4 border-b border-border flex items-center justify-between gap-3 flex-wrap">
            <div className="label-overline">Published months</div>
            <div className="flex items-center gap-2">
              <input value={fy} onChange={e => setFy(e.target.value)} className="bg-background border border-border px-2 py-1 text-sm w-24" data-testid="salary-fy"/>
              <button onClick={zip} className="border border-border px-3 py-1.5 text-sm inline-flex items-center gap-1" data-testid="salary-zip"><DownloadSimple size={14}/> Year ZIP</button>
            </div>
          </div>
          <div className="divide-y divide-border">
            {(data.payslips || []).map(line => (
              <div key={line.line_id} className="p-4 flex items-center justify-between gap-3" data-testid={`salary-row-${line.month}`}>
                <div>
                  <div className="font-medium">{monthName(line.month)}{line.superseded && <span className="ml-2 text-[10px] uppercase tracking-[0.14em] border border-border px-1">Superseded</span>}{line.imported && <span className="ml-2 text-[10px] uppercase tracking-[0.14em] border border-border px-1">Imported</span>}</div>
                  <div className="text-xs text-muted-foreground">Days paid {line.ndp} · Net ₹{money(line.atc)}</div>
                </div>
                <div className="flex gap-2">
                  <button onClick={() => download(line)} className="border border-border px-3 py-1.5 text-sm" data-testid={`salary-download-${line.month}`}>Download</button>
                  <button onClick={() => setQueryFor(line)} className="border border-border px-3 py-1.5 text-sm" data-testid={`salary-query-${line.month}`}>Raise a query</button>
                </div>
              </div>
            ))}
            {(data.payslips || []).length === 0 && <div className="p-8 text-sm text-muted-foreground text-center">No published payslips yet.</div>}
          </div>
        </section>
        {queryFor && (
          <div className="border border-border bg-card p-4 space-y-2" data-testid="salary-query-box">
            <div className="text-sm font-medium">Query for {monthName(queryFor.month)}</div>
            <textarea value={message} onChange={e => setMessage(e.target.value)} className="bg-background border border-border px-3 py-2 text-sm w-full" rows={3} data-testid="salary-query-message"/>
            <button onClick={send} className="bg-foreground text-background px-3 py-2 text-sm" data-testid="salary-query-send">Send</button>
          </div>
        )}
      </main>
    </div>
  );
}
