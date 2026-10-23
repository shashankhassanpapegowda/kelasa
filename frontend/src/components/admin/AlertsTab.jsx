import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { useAuth } from "@/lib/auth";
import AlertHistory from "@/components/AlertHistory";
import PhoneAlertsCard from "@/components/admin/PhoneAlertsCard";
import { BellRinging } from "@phosphor-icons/react";

const today = () => new Date().toLocaleDateString("en-CA");
const inputCls = "bg-background border border-border px-3 py-1.5 text-sm font-mono";

export default function AlertsTab() {
  const { user } = useAuth();
  const [from, setFrom] = useState(today());
  const [to, setTo] = useState(today());

  return (
    <div className="space-y-6" data-testid="alerts-tab">
      <PhoneAlertsCard/>
      {user?.role === "admin" && <EscalationSetting/>}
      <div className="flex items-end gap-3 flex-wrap">
        <div>
          <label className="label-overline mb-1.5 block">From</label>
          <input type="date" value={from} max={to} onChange={e => setFrom(e.target.value)} className={inputCls} data-testid="alerts-from"/>
        </div>
        <div>
          <label className="label-overline mb-1.5 block">To</label>
          <input type="date" value={to} min={from} onChange={e => setTo(e.target.value)} className={inputCls} data-testid="alerts-to"/>
        </div>
      </div>
      <AlertHistory from={from} to={to}/>
    </div>
  );
}

function EscalationSetting() {
  const [mins, setMins] = useState("");
  const [saved, setSaved] = useState(null);

  useEffect(() => {
    api.get("/admin/settings/geofence").then(r => { setMins(String(r.data.escalate_minutes)); setSaved(r.data.escalate_minutes); }).catch(() => {});
  }, []);

  const save = async () => {
    try {
      const r = await api.put("/admin/settings/geofence", { escalate_minutes: Number(mins) });
      setSaved(r.data.escalate_minutes);
      toast.success(`Repeat alert every ${r.data.escalate_minutes} min while outside`);
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not save"); }
  };

  return (
    <div className="border border-border bg-card p-4 flex items-center justify-between gap-4 flex-wrap" data-testid="escalation-setting">
      <div className="flex items-start gap-3">
        <BellRinging size={18} weight="bold" className="text-[#FF3B30] mt-0.5"/>
        <div>
          <div className="text-sm font-medium">Repeat the alert while someone stays outside</div>
          <div className="text-xs text-muted-foreground">Alert sounds again every {saved ?? "…"} minutes until they return or check out.</div>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-xs text-muted-foreground">Every</span>
        <input type="number" min="5" max="480" value={mins} onChange={e => setMins(e.target.value)}
          className="w-20 bg-background border border-border px-2 py-1.5 text-sm font-mono text-right" data-testid="escalation-minutes-input"/>
        <span className="text-xs text-muted-foreground">min</span>
        <button onClick={save} disabled={String(saved) === mins} data-testid="escalation-save-btn"
          className="bg-foreground text-background px-3 py-1.5 text-sm hover:bg-primary transition-colors disabled:opacity-40">Save</button>
      </div>
    </div>
  );
}
