import { useMemo, useState } from "react";
import { MapPinArea, WarningCircle } from "@phosphor-icons/react";

const OUTSIDE = "Outside / no zone";
const fmtHm = (m) => (m == null ? "—" : `${Math.floor(m / 60)}h ${m % 60}m`);

export default function BranchReport({ punches, zoneAlerts }) {
  const [filter, setFilter] = useState("all");

  const groups = useMemo(() => {
    const g = {};
    punches.forEach(p => { (g[p.check_in_branch || OUTSIDE] ||= []).push(p); });
    return Object.entries(g).sort((a, b) => (a[0] === OUTSIDE) - (b[0] === OUTSIDE) || b[1].length - a[1].length);
  }, [punches]);

  const shown = filter === "all" ? groups : groups.filter(([name]) => name === filter);

  return (
    <div className="mt-6 space-y-6" data-testid="branch-report">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-0 border border-border bg-card">
        {groups.map(([name, list]) => (
          <button key={name} onClick={() => setFilter(filter === name ? "all" : name)} data-testid={`branch-card-${name}`}
            className={`text-left p-5 border-b md:border-r border-border transition-colors ${filter === name ? "bg-foreground text-background" : "hover:bg-secondary/50"}`}>
            <div className="label-overline mb-1.5 truncate">{name}</div>
            <div className="font-mono text-2xl font-semibold">{list.length}</div>
            <div className="text-[10px] font-mono opacity-70 mt-0.5">{new Set(list.map(p => p.user_id)).size} employees</div>
          </button>
        ))}
        <div className={`p-5 border-b border-border ${zoneAlerts > 0 ? "bg-[#FF3B30]/5" : ""}`}>
          <div className="label-overline mb-1.5">Left-area alerts</div>
          <div className="font-mono text-2xl font-semibold" data-testid="branch-report-alerts">{zoneAlerts}</div>
        </div>
      </div>

      {shown.map(([name, list]) => (
        <div key={name} className="border border-border bg-card overflow-x-auto" data-testid={`branch-group-${name}`}>
          <div className="p-4 border-b border-border flex items-center gap-2">
            {name === OUTSIDE ? <WarningCircle size={16} weight="bold" className="text-yellow-600"/> : <MapPinArea size={16} weight="bold" className="text-primary"/>}
            <span className="label-overline">{name}</span>
            <span className="font-mono text-xs text-muted-foreground">{list.length} punches</span>
          </div>
          <table className="w-full text-sm">
            <thead className="text-[10px] label-overline border-b border-border">
              <tr>
                <th className="text-left p-3">Date</th>
                <th className="text-left p-3">Employee</th>
                <th className="text-left p-3">Home Branch</th>
                <th className="text-left p-3">In</th>
                <th className="text-left p-3">Out</th>
                <th className="text-left p-3">Out At</th>
                <th className="text-right p-3">Net</th>
              </tr>
            </thead>
            <tbody>
              {list.map(p => (
                <tr key={p.record_id} className="border-b border-border last:border-b-0" data-testid={`punch-row-${p.record_id}`}>
                  <td className="p-3 font-mono text-xs">{p.date}</td>
                  <td className="p-3">
                    <div className="font-medium">{p.name}</div>
                    {p.field_staff && <span className="text-[9px] font-mono uppercase text-[#0047FF]">field staff</span>}
                  </td>
                  <td className="p-3 text-xs">{p.home_branch || "—"}</td>
                  <td className="p-3 font-mono text-xs">{p.check_in || "—"}</td>
                  <td className="p-3 font-mono text-xs">{p.check_out || <span className="text-[#00A86B]">on duty</span>}</td>
                  <td className="p-3 text-xs">{p.check_out ? (p.check_out_branch || OUTSIDE) : "—"}</td>
                  <td className="p-3 font-mono text-right">{fmtHm(p.net_work_minutes)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
      {groups.length === 0 && <div className="border border-border bg-card p-8 text-center text-sm text-muted-foreground">No punches in this date range.</div>}
    </div>
  );
}
