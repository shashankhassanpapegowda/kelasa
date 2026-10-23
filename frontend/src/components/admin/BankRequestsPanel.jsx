import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { Bank, Check, X } from "@phosphor-icons/react";

export default function BankRequestsPanel() {
  const [items, setItems] = useState([]);
  const load = () => api.get("/admin/bank-requests").then(r => setItems(r.data.requests || [])).catch(() => {});
  useEffect(() => { load(); }, []);

  const decide = async (r, status) => {
    let note = null;
    if (status === "rejected") {
      note = window.prompt(`Reason for rejecting ${r.user_name}'s bank change (shown to them):`, "");
      if (note === null) return;
    }
    try {
      await api.post(`/admin/bank-requests/${r.request_id}/decide`, { status, note });
      toast.success(`Bank change ${status}`);
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not update"); }
  };

  if (!items.length) return null;
  return (
    <div className="border-2 border-yellow-500/60 bg-yellow-500/5 mb-6" data-testid="bank-requests-panel">
      <div className="p-3 border-b border-yellow-500/30 flex items-center gap-2">
        <Bank size={16} weight="bold" className="text-yellow-600"/>
        <span className="label-overline">Bank detail changes waiting · {items.length}</span>
      </div>
      <div className="divide-y divide-yellow-500/20">
        {items.map(r => (
          <div key={r.request_id} className="p-3 flex items-center justify-between gap-3 flex-wrap" data-testid={`bank-request-${r.request_id}`}>
            <div className="text-sm min-w-0">
              <div className="font-medium">{r.user_name}</div>
              <div className="text-xs font-mono">
                New: {r.account_holder} · {r.account_number} · {r.ifsc}{r.bank_name ? ` · ${r.bank_name}` : ""}
              </div>
              <div className="text-[11px] font-mono text-muted-foreground">
                Current: {r.current_bank ? `${r.current_bank.account_number} · ${r.current_bank.ifsc}` : "none"}
              </div>
            </div>
            <div className="flex gap-2">
              <button onClick={() => decide(r, "approved")} data-testid={`bank-approve-${r.request_id}`}
                className="bg-[#00A86B] text-white px-3 py-1.5 text-xs inline-flex items-center gap-1"><Check size={12} weight="bold"/> Approve</button>
              <button onClick={() => decide(r, "rejected")} data-testid={`bank-reject-${r.request_id}`}
                className="border border-border bg-card px-3 py-1.5 text-xs inline-flex items-center gap-1 hover:border-[#FF3B30] hover:text-[#FF3B30]"><X size={12} weight="bold"/> Reject</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
