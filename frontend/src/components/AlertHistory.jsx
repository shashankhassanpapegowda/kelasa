import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { fmtDay, fmtDuration } from "@/lib/format";
import { useAuth } from "@/lib/auth";
import { Download, SignOut } from "@phosphor-icons/react";

export default function AlertHistory({ from, to, showDownload = true }) {
  const { user } = useAuth();
  const tz = user?.timezone || "Asia/Kolkata";
  const [data, setData] = useState({ alerts: [], escalate_minutes: 30 });
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!from || !to) return;
    setLoading(true);
    api.get("/admin/geofence-alerts/history", { params: { from, to } })
      .then(r => setData(r.data))
      .catch(() => toast.error("Failed to load alert history"))
      .finally(() => setLoading(false));
  }, [from, to]);

  const days = useMemo(() => {
    const g = {};
    data.alerts.forEach(a => { (g[a.date] ||= []).push(a); });
    return Object.entries(g).sort((a, b) => b[0].localeCompare(a[0]));
  }, [data.alerts]);

  const totalMin = data.alerts.reduce((s, a) => s + a.minutes_outside, 0);
  const longest = data.alerts.reduce((m, a) => (a.minutes_outside > (m?.minutes_outside ?? -1) ? a : m), null);
  const stillOut = data.alerts.filter(a => !a.resolved_at).length;

  const download = async () => {
    try {
      const res = await api.get("/admin/geofence-alerts/history.csv", { params: { from, to }, responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url; a.download = `left_area_log_${from}_to_${to}.csv`; a.click();
      URL.revokeObjectURL(url);
    } catch { toast.error("Download failed"); }
  };

  return (
    <div className="space-y-6" data-testid="alert-history">
      <div className="grid grid-cols-2 md:grid-cols-4 border border-border bg-card">
        <Stat label="Times left area" value={data.alerts.length} testid="alert-history-count"/>
        <Stat label="Total time outside" value={fmtDuration(totalMin)} testid="alert-history-total"/>
        <Stat label="Longest" value={longest ? `${fmtDuration(longest.minutes_outside)}` : "—"} sub={longest?.name} testid="alert-history-longest"/>
        <Stat label="Still outside" value={stillOut} accent={stillOut > 0} testid="alert-history-open"/>
      </div>

      {showDownload && (
        <button onClick={download} data-testid="alert-history-csv"
          className="border border-border bg-card px-3 py-2 text-xs uppercase tracking-[0.15em] inline-flex items-center gap-2 hover:border-foreground">
          <Download size={14} weight="bold"/> Left-Area Log CSV
        </button>
      )}

      {loading && <div className="text-sm text-muted-foreground">Loading…</div>}
      {!loading && days.length === 0 && (
        <div className="border border-border bg-card p-8 text-center text-sm text-muted-foreground" data-testid="alert-history-empty">
          Nobody left a branch area in this period.
        </div>
      )}

      {days.map(([day, list]) => <DayBlock key={day} day={day} list={list} every={data.escalate_minutes} tz={tz}/>)}
    </div>
  );
}

function DayBlock({ day, list, every, tz }) {
  const fmtTime = (iso) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", timeZone: tz });
  const total = list.reduce((s, a) => s + a.minutes_outside, 0);
  return (
    <div className="border border-border bg-card overflow-x-auto" data-testid={`alert-day-${day}`}>
      <div className="p-4 border-b border-border flex items-center gap-3 flex-wrap">
        <SignOut size={16} weight="bold" className="text-[#FF3B30]"/>
        <span className="label-overline">{fmtDay(day)}</span>
        <span className="font-mono text-xs text-muted-foreground">{list.length} exits · {fmtDuration(total)} outside</span>
      </div>
      <table className="w-full text-sm">
        <thead className="text-[10px] label-overline border-b border-border">
          <tr>
            <th className="text-left p-3">Employee</th>
            <th className="text-left p-3">Left</th>
            <th className="text-left p-3">Returned</th>
            <th className="text-right p-3">Away</th>
            <th className="text-left p-3">Near</th>
            <th className="text-right p-3">Repeats</th>
            <th className="text-left p-3">Acknowledged</th>
          </tr>
        </thead>
        <tbody>
          {list.map(a => (
            <tr key={a.alert_id} className="border-b border-border last:border-b-0" data-testid={`alert-row-${a.alert_id}`}>
              <td className="p-3 font-medium">{a.name}</td>
              <td className="p-3 font-mono text-xs">{fmtTime(a.created_at)}</td>
              <td className="p-3 font-mono text-xs">
                {a.resolved_at
                  ? <>{fmtTime(a.resolved_at)} <span className="text-muted-foreground">· {a.resolved_reason === "checked out" ? "checked out" : "came back"}</span></>
                  : <span className="text-[#FF3B30]">still outside</span>}
              </td>
              <td className={`p-3 font-mono text-right ${a.minutes_outside >= every ? "text-[#FF3B30] font-semibold" : ""}`}>{fmtDuration(a.minutes_outside)}</td>
              <td className="p-3 text-xs">{a.nearest_branch} <span className="text-muted-foreground font-mono">({a.distance_m} m)</span></td>
              <td className="p-3 font-mono text-right">{a.escalation_level || "—"}</td>
              <td className="p-3 text-xs">{a.acknowledged_by || <span className="text-muted-foreground">—</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const Stat = ({ label, value, sub, accent, testid }) => (
  <div className={`p-5 border-b md:border-b-0 md:border-r border-border last:border-r-0 ${accent ? "bg-[#FF3B30]/5" : ""}`}>
    <div className="label-overline mb-1.5">{label}</div>
    <div className={`font-mono text-2xl font-semibold ${accent ? "text-[#FF3B30]" : ""}`} data-testid={testid}>{value}</div>
    {sub && <div className="text-[10px] text-muted-foreground mt-0.5 truncate">{sub}</div>}
  </div>
);
