import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { fmtDay } from "@/lib/format";
import { Check, X, Hourglass } from "@phosphor-icons/react";

const STATUSES = ["pending", "approved", "rejected", "all"];
const STATUS_STYLE = {
  pending: "bg-yellow-400 text-black",
  approved: "bg-[#00E676] text-black",
  rejected: "bg-[#FF3B30] text-white",
  cancelled: "bg-secondary text-muted-foreground",
};

export default function LeaveTab({ isAdmin, currentUserId, onDecided }) {
  const [status, setStatus] = useState("pending");
  const [requests, setRequests] = useState([]);
  const [balances, setBalances] = useState({ rows: [], types: [] });
  const [view, setView] = useState("requests");
  const [busy, setBusy] = useState(null);

  const load = async () => {
    try {
      const [r, b] = await Promise.all([
        api.get(`/admin/leave?status=${status}`),
        api.get("/admin/leave/balances"),
      ]);
      setRequests(r.data.requests || []);
      setBalances(b.data);
    } catch { toast.error("Failed to load leave data"); }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [status]);

  const decide = async (req, decision) => {
    let note = "";
    if (decision === "rejected") {
      const input = window.prompt(`Reason for rejecting ${req.user_name}'s leave?`);
      if (input === null) return;
      note = input;
    }
    setBusy(req.leave_id);
    try {
      await api.post(`/admin/leave/${req.leave_id}/decide`, { status: decision, note });
      toast.success(`Leave ${decision}`);
      load();
      onDecided?.();
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not update"); }
    finally { setBusy(null); }
  };

  return (
    <div data-testid="leave-tab">
      <div className="flex items-center gap-2 flex-wrap">
        <TabBtn active={view === "requests"} onClick={() => setView("requests")} testid="leave-view-requests">Requests</TabBtn>
        <TabBtn active={view === "balances"} onClick={() => setView("balances")} testid="leave-view-balances">Balances</TabBtn>
        {isAdmin && <TabBtn active={view === "types"} onClick={() => setView("types")} testid="leave-view-types">Leave Types</TabBtn>}
      </div>

      {view === "requests" && (
        <div className="mt-4 border border-border bg-card">
          <div className="p-4 border-b border-border flex items-center justify-between gap-3 flex-wrap">
            <div className="flex items-center gap-2">
              <Hourglass size={16} weight="bold" className="text-primary"/>
              <span className="label-overline">Leave Requests</span>
            </div>
            <div className="flex items-center gap-1">
              {STATUSES.map(s => (
                <button key={s} onClick={() => setStatus(s)} data-testid={`leave-filter-${s}`}
                  className={`text-[10px] label-overline border px-2 py-1 ${status === s ? "bg-foreground text-background border-foreground" : "border-border hover:border-foreground"}`}>
                  {s}
                </button>
              ))}
            </div>
          </div>
          <div className="divide-y divide-border max-h-[640px] overflow-y-auto" data-testid="leave-requests-list">
            {requests.map(r => (
              <div key={r.leave_id} className="p-4 flex items-start gap-3 flex-wrap" data-testid={`leave-row-${r.leave_id}`}>
                <div className="flex-1 min-w-[220px]">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium">{r.user_name}</span>
                    <span className={`text-[9px] font-mono uppercase tracking-wider px-1.5 py-0.5 ${STATUS_STYLE[r.status]}`}>{r.status}</span>
                    <span className="text-[9px] font-mono uppercase tracking-wider border border-border px-1.5 py-0.5">{r.type_code}</span>
                  </div>
                  <div className="text-xs text-muted-foreground mt-0.5">{r.email}{r.department ? ` · ${r.department}` : ""}</div>
                  <div className="font-mono text-sm mt-1">
                    {fmtDay(r.start_date)} → {fmtDay(r.end_date)} <span className="text-muted-foreground">· {r.days}d{r.half_day ? " (half)" : ""}{r.lop_days > 0 ? ` · ${r.lop_days} unpaid` : ""}</span>
                  </div>
                  {r.reason && <div className="text-xs mt-1 text-muted-foreground italic">“{r.reason}”</div>}
                  {r.decided_by_name && (
                    <div className="text-[10px] font-mono text-muted-foreground mt-1">
                      {r.status} by {r.decided_by_name}{r.decision_note ? ` · ${r.decision_note}` : ""}
                    </div>
                  )}
                </div>
                {r.status === "pending" && r.user_id !== currentUserId && (
                  <div className="flex items-center gap-2">
                    <button disabled={busy === r.leave_id} onClick={() => decide(r, "approved")} data-testid={`approve-${r.leave_id}`}
                      className="bg-[#00E676] text-black px-3 py-2 text-xs font-medium inline-flex items-center gap-1.5 hover:brightness-95 disabled:opacity-50">
                      <Check size={14} weight="bold"/> Approve
                    </button>
                    <button disabled={busy === r.leave_id} onClick={() => decide(r, "rejected")} data-testid={`reject-${r.leave_id}`}
                      className="border border-border px-3 py-2 text-xs font-medium inline-flex items-center gap-1.5 hover:border-[#FF3B30] hover:text-[#FF3B30] disabled:opacity-50">
                      <X size={14} weight="bold"/> Reject
                    </button>
                  </div>
                )}
                {r.status === "pending" && r.user_id === currentUserId && (
                  <span className="text-[10px] label-overline text-muted-foreground" data-testid={`own-request-${r.leave_id}`}>
                    Your own request · another manager must decide
                  </span>
                )}
              </div>
            ))}
            {requests.length === 0 && <div className="p-8 text-sm text-muted-foreground text-center" data-testid="leave-empty">No {status === "all" ? "" : status} leave requests.</div>}
          </div>
        </div>
      )}

      {view === "balances" && (
        <div className="mt-4 border border-border bg-card overflow-x-auto" data-testid="leave-balances">
          <table className="w-full text-sm min-w-[620px]">
            <thead className="text-[10px] label-overline">
              <tr className="border-b border-border">
                <th className="text-left p-3">Employee</th>
                {balances.types?.map(t => <th key={t.type_id} className="text-right p-3">{t.code}</th>)}
              </tr>
            </thead>
            <tbody>
              {balances.rows?.map(row => (
                <tr key={row.user_id} className="border-b border-border hover:bg-secondary/40">
                  <td className="p-3">
                    <div className="font-medium">{row.name}</div>
                    <div className="text-xs text-muted-foreground">{row.department || "—"}</div>
                  </td>
                  {row.balances.map(b => (
                    <td key={b.type_id} className="p-3 text-right font-mono">
                      {b.entitled == null ? <span className="text-muted-foreground">∞</span> : (
                        <>
                          <span className={b.available <= 0 ? "text-[#FF3B30]" : ""}>{b.available}</span>
                          <span className="text-muted-foreground text-xs">/{b.entitled}</span>
                        </>
                      )}
                    </td>
                  ))}
                </tr>
              ))}
              {(!balances.rows || balances.rows.length === 0) && (
                <tr><td colSpan={9} className="p-8 text-center text-muted-foreground">No employees yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {view === "types" && isAdmin && <LeaveTypes onChange={load}/>}
    </div>
  );
}

const TabBtn = ({ active, onClick, children, testid }) => (
  <button onClick={onClick} data-testid={testid}
    className={`text-xs label-overline border px-3 py-2 transition-colors ${active ? "bg-foreground text-background border-foreground" : "border-border hover:border-foreground"}`}>
    {children}
  </button>
);

function LeaveTypes() {
  return (
    <div className="mt-4 border border-border bg-card max-w-xl" data-testid="leave-types">
      <div className="p-4 border-b border-border">
        <span className="label-overline">Leave Policy</span>
      </div>
      <div className="p-4 space-y-2 text-sm">
        <p className="font-medium">One paid leave day per calendar month.</p>
        <p className="text-muted-foreground">It does not carry forward. An unused day lapses at the end of the month. Days beyond that one paid day are unpaid. Older casual, sick and earned leave records stay readable and still count in past payroll.</p>
      </div>
    </div>
  );
}
