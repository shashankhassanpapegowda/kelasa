import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "@/lib/api";
import { toast } from "sonner";
import AuthPhoto from "@/components/AuthPhoto";
import { BankView } from "@/pages/ProfilePage";
import { X } from "@phosphor-icons/react";

const fmt = (d) => (d ? new Date(d + "T00:00:00").toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" }) : "—");

export default function EmployeeProfileModal({ emp, onClose }) {
  const [p, setP] = useState(null);
  useEffect(() => {
    api.get(`/admin/employees/${emp.user_id}/profile`).then(r => setP(r.data))
      .catch(e => { toast.error(e?.response?.data?.detail || "Could not load profile"); onClose(); });
  }, [emp.user_id, onClose]);

  return createPortal(
    <div className="fixed inset-0 z-[1000] bg-black/80 backdrop-blur-sm grid place-items-center p-4 overflow-y-auto" onClick={onClose} data-testid="employee-profile-modal">
      <div className="bg-card border border-border max-w-lg w-full my-8" onClick={e => e.stopPropagation()}>
        <div className="p-4 border-b border-border flex items-center justify-between">
          <div className="flex items-center gap-3">
            <AuthPhoto path={p?.avatar_path} className="w-10 h-10 rounded-full object-cover border border-border"
              fallback={<div className="w-10 h-10 rounded-full bg-secondary grid place-items-center text-sm font-medium">{emp.name?.[0]}</div>}/>
            <div>
              <div className="font-semibold">{emp.name}</div>
              <div className="text-xs text-muted-foreground">{emp.email}</div>
            </div>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-secondary" data-testid="employee-profile-close"><X size={18} weight="bold"/></button>
        </div>
        {!p ? <div className="p-6 text-sm text-muted-foreground">Loading…</div> : (
          <div className="p-5 space-y-5 text-sm">
            <div className="grid grid-cols-3 gap-3" data-testid="employee-profile-dates">
              <div><div className="label-overline mb-1">Birthday</div>{fmt(p.dob)}</div>
              <div><div className="label-overline mb-1">Wedding</div>{fmt(p.wedding_anniversary)}</div>
              <div><div className="label-overline mb-1">Joined</div>{fmt(p.date_of_joining)}</div>
            </div>
            <div className="grid grid-cols-2 gap-3" data-testid="employee-profile-statutory">
              <div><div className="label-overline mb-1">EPF UAN</div><span className="font-mono">{p.uan || "—"}</span></div>
              <div><div className="label-overline mb-1">ESI Number</div><span className="font-mono">{p.esi_not_applicable ? "Not applicable" : p.esi || "—"}</span></div>
            </div>
            <div className="border-t border-border pt-4">
              <div className="label-overline mb-3">Bank Account</div>
              {p.bank ? <BankView bank={p.bank}/> : <div className="text-muted-foreground">Not added yet.</div>}
              {p.bank?.approved_by && <div className="text-[10px] text-muted-foreground mt-2">Approved by {p.bank.approved_by}</div>}
              {p.pending_bank && (
                <div className="mt-3 border border-yellow-500/50 bg-yellow-500/5 p-3 text-xs" data-testid="employee-profile-pending-bank">
                  Pending change: {p.pending_bank.account_holder} · <span className="font-mono">{p.pending_bank.account_number} · {p.pending_bank.ifsc}</span>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>,
    document.body
  );
}
