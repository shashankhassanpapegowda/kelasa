import { useState } from "react";
import { createPortal } from "react-dom";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { X, PaperPlaneRight } from "@phosphor-icons/react";

const SUGGEST = {
  birthday: ["Happy birthday! Have a fantastic day!", "Many happy returns of the day!", "Wishing you a great year ahead!"],
  wedding_anniversary: ["Happy anniversary to you both!", "Wishing you many more years of happiness together!"],
  work_anniversary: ["Congratulations on your work anniversary!", "Thanks for all your hard work — here's to many more years!"],
};

export default function WishDialog({ c, onClose, onSent }) {
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const send = async () => {
    if (!msg.trim()) return toast.error("Write a message");
    setBusy(true);
    try {
      const { data } = await api.post("/wishes", { to_user_id: c.user_id, kind: c.kind, message: msg });
      toast.success(`Wish sent to ${c.name?.split(" ")[0]}`);
      onSent(data.wish);
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not send"); }
    finally { setBusy(false); }
  };
  return createPortal(
    <div className="fixed inset-0 z-[1000] bg-black/80 backdrop-blur-sm grid place-items-center p-4" onClick={onClose} data-testid="wish-dialog">
      <div className="bg-card border border-border max-w-md w-full" onClick={e => e.stopPropagation()}>
        <div className="p-4 border-b border-border flex items-center justify-between">
          <div>
            <div className="label-overline">Private wish</div>
            <div className="font-semibold mt-0.5">To {c.name}</div>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-secondary" data-testid="wish-dialog-close"><X size={18} weight="bold"/></button>
        </div>
        <div className="p-4 space-y-3">
          <div className="flex flex-wrap gap-1.5">
            {(SUGGEST[c.kind] || []).map(s => (
              <button key={s} onClick={() => setMsg(s)} className="text-[11px] border border-border px-2 py-1 hover:border-primary hover:text-primary" data-testid="wish-suggestion">{s}</button>
            ))}
          </div>
          <textarea value={msg} onChange={e => setMsg(e.target.value)} rows={4} maxLength={500} autoFocus
            placeholder="Write something nice…" className="w-full bg-background border border-border px-3 py-2 text-sm" data-testid="wish-message"/>
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-muted-foreground">Only {c.name?.split(" ")[0]} will see this.</span>
            <button onClick={send} disabled={busy} data-testid="wish-send-btn"
              className="bg-foreground text-background px-4 py-2 text-sm inline-flex items-center gap-1.5 hover:bg-primary transition-colors disabled:opacity-50">
              <PaperPlaneRight size={14} weight="bold"/> Send wish
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}
