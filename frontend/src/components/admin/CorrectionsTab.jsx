import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { ClockCounterClockwise, Check, X } from "@phosphor-icons/react";

const STATUS_CLS = {
  pending: "bg-[#FFC107]/20 text-[#8A6200]", approved: "bg-[#00E676]/15 text-[#00A152]",
  rejected: "bg-[#FF3B30]/15 text-[#FF3B30]", cancelled: "bg-secondary text-muted-foreground",
};

const fmtDay = (d) => new Date(`${d}T00:00:00`).toLocaleDateString([], { weekday: "short", day: "2-digit", month: "short", year: "numeric" });

export default function CorrectionsTab({ onChange }) {
  const [status, setStatus] = useState("pending");
  const [items, setItems] = useState([]);
  const [notes, setNotes] = useState({});
  const [busy, setBusy] = useState(null);

  const load = () => api.get(`/admin/regularizations?status=${status}`).then(r => setItems(r.data.items || [])).catch(() => toast.error("Failed to load corrections"));
  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [status]);

  const decide = async (r, decision) => {
    if (decision === "rejected" && !(notes[r.request_id] || "").trim()) {
      toast.error("Add a note explaining why it was rejected");
      return;
    }
    setBusy(r.request_id);
    try {
      await api.post(`/admin/regularizations/${r.request_id}/decide`, { decision, note: notes[r.request_id] || "" });
      toast.success(decision === "approved" ? `Approved — ${r.name}'s attendance was updated` : "Rejected");
      load(); onChange?.();
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not save"); }
    finally { setBusy(null); }
  };

  return (
    <div className="border border-border bg-card max-w-4xl" data-testid="corrections-tab">
      <div className="p-4 border-b border-border flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <ClockCounterClockwise size={16} weight="bold" className="text-primary"/>
          <span className="label-overline">Attendance Corrections</span>
        </div>
        <div className="flex border border-border text-xs" data-testid="corrections-status-filter">
          {["pending", "approved", "rejected", "all"].map(s => (
            <button key={s} onClick={() => setStatus(s)} data-testid={`corrections-filter-${s}`}
              className={`px-3 py-1.5 capitalize transition-colors ${status === s ? "bg-foreground text-background" : "hover:bg-secondary"}`}>{s}</button>
          ))}
        </div>
      </div>
      <div className="divide-y divide-border" data-testid="corrections-list">
        {items.map(r => (
          <div key={r.request_id} className="p-4 space-y-3" data-testid={`correction-${r.request_id}`}>
            <div className="flex items-start justify-between gap-3 flex-wrap">
              <div>
                <div className="font-medium">{r.name}</div>
                <div className="text-sm text-muted-foreground">{fmtDay(r.date)} · <span className="font-mono text-foreground">{r.check_in} – {r.check_out}</span></div>
              </div>
              <span className={`text-[11px] px-2 py-0.5 uppercase tracking-wide ${STATUS_CLS[r.status]}`}>{r.status}</span>
            </div>
            <p className="text-sm bg-secondary/60 px-3 py-2">“{r.reason}”</p>
            {r.status === "pending" ? (
              <div className="flex gap-2 flex-wrap">
                <input value={notes[r.request_id] || ""} onChange={e => setNotes({ ...notes, [r.request_id]: e.target.value })}
                  placeholder="Note for the employee (required to reject)" data-testid={`correction-note-${r.request_id}`}
                  className="flex-1 min-w-[200px] bg-background border border-border px-3 py-2 text-sm"/>
                <button onClick={() => decide(r, "approved")} disabled={busy === r.request_id} data-testid={`correction-approve-${r.request_id}`}
                  className="px-3 py-2 text-sm bg-[#00A152] text-white inline-flex items-center gap-1.5 disabled:opacity-50"><Check size={14} weight="bold"/> Approve</button>
                <button onClick={() => decide(r, "rejected")} disabled={busy === r.request_id} data-testid={`correction-reject-${r.request_id}`}
                  className="px-3 py-2 text-sm border border-[#FF3B30] text-[#FF3B30] inline-flex items-center gap-1.5 disabled:opacity-50"><X size={14} weight="bold"/> Reject</button>
              </div>
            ) : (
              (r.manager_note || r.decided_by_name) && (
                <div className="text-xs text-muted-foreground">{r.decided_by_name && `by ${r.decided_by_name}`}{r.manager_note && ` — “${r.manager_note}”`}</div>
              )
            )}
          </div>
        ))}
        {items.length === 0 && <div className="p-8 text-center text-sm text-muted-foreground">{status === "pending" ? "No corrections waiting for approval." : "Nothing here."}</div>}
      </div>
      <div className="p-3 border-t border-border text-xs text-muted-foreground">
        Approving replaces that day's check-in and check-out with the requested times. The original times are kept on record.
      </div>
    </div>
  );
}
