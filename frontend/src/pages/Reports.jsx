import { useEffect, useState } from "react";
import AppHeader from "@/components/AppHeader";
import { api, API } from "@/lib/api";
import { toast } from "sonner";
import { Download, Calendar, ChartBar, WarningCircle, Clock as ClockIcon, Coffee } from "@phosphor-icons/react";

const todayStr = () => new Date().toISOString().slice(0, 10);
const monthAgoStr = () => {
  const d = new Date();
  d.setDate(d.getDate() - 29);
  return d.toISOString().slice(0, 10);
};

const fmtHm = (mins) => {
  const h = Math.floor((mins || 0) / 60);
  const m = (mins || 0) % 60;
  return `${h}h ${m}m`;
};

export default function Reports() {
  const [from, setFrom] = useState(monthAgoStr());
  const [to, setTo] = useState(todayStr());
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const res = await api.get(`/admin/reports?from=${from}&to=${to}`);
      setRows(res.data.rows || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to load report");
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const totals = rows.reduce((acc, r) => ({
    present: acc.present + r.present_days,
    absent: acc.absent + r.absent_days,
    late: acc.late + r.late_days,
    work: acc.work + r.total_work_minutes,
    breakM: acc.breakM + r.total_break_minutes,
    overBreak: acc.overBreak + r.over_break_days,
  }), { present: 0, absent: 0, late: 0, work: 0, breakM: 0, overBreak: 0 });

  const downloadCsv = async () => {
    try {
      const res = await api.get(`/admin/reports.csv?from=${from}&to=${to}`, { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `attendance_report_${from}_to_${to}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success("CSV downloaded");
    } catch {
      toast.error("Failed to download CSV");
    }
  };

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <AppHeader/>
      <main className="flex-1">
        <div className="px-4 sm:px-6 py-6">
          <div className="flex items-end justify-between gap-4 flex-wrap">
            <div>
              <div className="label-overline" data-testid="reports-overline">Workforce Analytics</div>
              <h1 className="text-3xl sm:text-4xl font-semibold tracking-tight mt-1">Reports</h1>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <label className="flex items-center gap-2 text-xs label-overline">
                <Calendar size={14} weight="bold"/> From
                <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} data-testid="from-date"
                  className="bg-card border border-border px-2 py-1.5 text-sm font-mono"/>
              </label>
              <label className="flex items-center gap-2 text-xs label-overline">To
                <input type="date" value={to} onChange={(e) => setTo(e.target.value)} data-testid="to-date"
                  className="bg-card border border-border px-2 py-1.5 text-sm font-mono"/>
              </label>
              <button onClick={load} className="border border-border bg-card px-3 py-1.5 text-sm hover:bg-secondary" data-testid="apply-range">Apply</button>
              <button onClick={downloadCsv} className="bg-foreground text-background px-3 py-1.5 text-sm inline-flex items-center gap-2 hover:bg-primary" data-testid="download-csv">
                <Download size={14} weight="bold"/> CSV
              </button>
            </div>
          </div>

          {/* Totals strip */}
          <div className="mt-6 grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-0 border border-border bg-card">
            <Tot label="Present Days" value={totals.present} testid="total-present"/>
            <Tot label="Absent Days" value={totals.absent} testid="total-absent"/>
            <Tot label="Late Days" value={totals.late} testid="total-late" warn={totals.late > 0}/>
            <Tot label="Over-Break Days" value={totals.overBreak} testid="total-overbreak" warn={totals.overBreak > 0}/>
            <Tot label="Total Work" value={fmtHm(totals.work)} testid="total-work"/>
            <Tot label="Total Break" value={fmtHm(totals.breakM)} testid="total-break"/>
          </div>

          {loading && <div className="loading-bar mt-2"/>}

          {/* Table */}
          <div className="mt-6 border border-border bg-card overflow-x-auto">
            <table className="w-full text-sm" data-testid="reports-table">
              <thead className="text-[10px] label-overline border-b border-border">
                <tr>
                  <th className="text-left p-3">Employee</th>
                  <th className="text-left p-3">Shift</th>
                  <th className="text-right p-3">Present</th>
                  <th className="text-right p-3">Absent</th>
                  <th className="text-right p-3">Late Days</th>
                  <th className="text-right p-3">Late Mins</th>
                  <th className="text-right p-3">Net Work</th>
                  <th className="text-right p-3">Break</th>
                  <th className="text-right p-3">Over-Brk</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(r => (
                  <tr key={r.user_id} className="border-b border-border hover:bg-secondary/40" data-testid={`report-row-${r.user_id}`}>
                    <td className="p-3">
                      <div className="font-medium">{r.name}</div>
                      <div className="text-xs text-muted-foreground">{r.email}</div>
                    </td>
                    <td className="p-3 font-mono text-xs">
                      {r.shift_start ? `${r.shift_start}${r.shift_end ? ` – ${r.shift_end}` : ""}` : <span className="text-yellow-700">—</span>}
                      <div className="text-[10px] text-muted-foreground">brk {r.break_max_minutes}m</div>
                    </td>
                    <td className="p-3 font-mono text-right">{r.present_days}</td>
                    <td className={`p-3 font-mono text-right ${r.absent_days > 0 ? "text-[#FF3B30]" : ""}`}>{r.absent_days}</td>
                    <td className={`p-3 font-mono text-right ${r.late_days > 0 ? "text-[#FF3B30]" : ""}`}>{r.late_days}</td>
                    <td className={`p-3 font-mono text-right ${r.total_late_minutes > 0 ? "text-[#FF3B30]" : ""}`}>{r.total_late_minutes}</td>
                    <td className="p-3 font-mono text-right font-semibold">{fmtHm(r.total_work_minutes)}</td>
                    <td className="p-3 font-mono text-right">{r.total_break_minutes}m</td>
                    <td className={`p-3 font-mono text-right ${r.over_break_days > 0 ? "text-yellow-700" : ""}`}>{r.over_break_days}</td>
                  </tr>
                ))}
                {rows.length === 0 && !loading && (
                  <tr><td colSpan={9} className="p-8 text-center text-muted-foreground">No data for this date range.</td></tr>
                )}
              </tbody>
            </table>
          </div>

          <p className="mt-4 text-xs text-muted-foreground flex items-start gap-1.5 max-w-2xl">
            <WarningCircle size={14} weight="bold" className="mt-0.5 shrink-0"/>
            Late = checked in more than <strong>15 minutes</strong> after the employee's mapped shift start. Over-break = total break time exceeds the employee's break limit on a given day. Net Work excludes break time.
          </p>
        </div>
      </main>
    </div>
  );
}

const Tot = ({ label, value, testid, warn }) => (
  <div className={`p-5 border-b lg:border-b-0 lg:border-r last:border-r-0 border-border ${warn ? "bg-[#FF3B30]/5" : ""}`}>
    <div className="label-overline mb-1.5">{label}</div>
    <div className="font-mono text-2xl font-semibold tracking-tight" data-testid={testid}>{value}</div>
  </div>
);
