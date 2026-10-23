import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { fmtAgo } from "@/lib/format";
import { Siren, SpeakerHigh, SpeakerSlash, Check, MapTrifold } from "@phosphor-icons/react";

const POLL_MS = 15000;

const beep = () => {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    [0, 0.25].forEach((t) => {
      const o = ctx.createOscillator(); const g = ctx.createGain();
      o.type = "square"; o.frequency.value = 880;
      g.gain.setValueAtTime(0.15, ctx.currentTime + t);
      g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + t + 0.2);
      o.connect(g); g.connect(ctx.destination);
      o.start(ctx.currentTime + t); o.stop(ctx.currentTime + t + 0.2);
    });
  } catch { /* audio not available */ }
};

export default function GeofenceAlerts({ onShowMap }) {
  const [alerts, setAlerts] = useState([]);
  const [muted, setMuted] = useState(() => localStorage.getItem("kelasa_alert_muted") === "1");
  const seen = useRef(null);

  useEffect(() => {
    const load = async () => {
      try {
        const { data } = await api.get("/admin/geofence-alerts");
        const active = data.active || [];
        const levels = new Map(active.map(a => [a.alert_id, a.escalation_level]));
        if (seen.current) {
          const fresh = active.filter(a => !seen.current.has(a.alert_id) && a.needs_attention);
          const escalated = active.filter(a => seen.current.has(a.alert_id) && a.escalation_level > seen.current.get(a.alert_id));
          if (fresh.length || escalated.length) {
            if (localStorage.getItem("kelasa_alert_muted") !== "1") beep();
            fresh.forEach(a => toast.error(`${a.name} left the branch area`));
            escalated.forEach(a => toast.error(`${a.name} still outside · ${a.minutes_outside} min`));
          }
        }
        seen.current = levels;
        setAlerts(active);
      } catch { /* silent polling */ }
    };
    load();
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, []);

  const toggleMute = () => {
    const next = !muted;
    setMuted(next);
    localStorage.setItem("kelasa_alert_muted", next ? "1" : "0");
    if (!next) beep();
  };

  const ack = async (a) => {
    try {
      await api.post(`/admin/geofence-alerts/${a.alert_id}/ack`);
      setAlerts(list => list.map(x => x.alert_id === a.alert_id ? { ...x, needs_attention: false } : x));
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not acknowledge"); }
  };

  const pending = alerts.filter(a => a.needs_attention);
  if (!pending.length) return null;

  return (
    <div className="mt-6 border-2 border-[#FF3B30] bg-[#FF3B30]/5" data-testid="geofence-alerts">
      <div className="p-3 border-b border-[#FF3B30]/30 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-[#FF3B30]">
          <Siren size={16} weight="fill" className="animate-pulse"/>
          <span className="label-overline text-[#FF3B30]">Left branch area · {pending.length}</span>
        </div>
        <button onClick={toggleMute} className="text-[10px] label-overline inline-flex items-center gap-1 hover:text-foreground" data-testid="geofence-alerts-mute">
          {muted ? <SpeakerSlash size={13} weight="bold"/> : <SpeakerHigh size={13} weight="bold"/>} {muted ? "SOUND OFF" : "SOUND ON"}
        </button>
      </div>
      <div className="divide-y divide-[#FF3B30]/20">
        {pending.map(a => (
          <div key={a.alert_id} className="p-3 flex items-center justify-between gap-3 flex-wrap" data-testid={`geofence-alert-${a.alert_id}`}>
            <div className="min-w-0">
              <div className="text-sm font-medium flex items-center gap-2 flex-wrap">
                {a.name}
                {a.escalation_level > 0 && (
                  <span className="text-[9px] font-mono uppercase tracking-wider bg-[#FF3B30] text-white px-1.5 py-0.5" data-testid={`geofence-alert-escalated-${a.alert_id}`}>
                    STILL OUTSIDE · {a.minutes_outside} MIN
                  </span>
                )}
              </div>
              <div className="text-xs text-muted-foreground font-mono">
                {a.distance_m} m outside {a.nearest_branch} · left {fmtAgo(a.created_at)} · seen {fmtAgo(a.last_seen_at)}
              </div>
            </div>
            <div className="flex items-center gap-3">
              <button onClick={onShowMap} className="text-[10px] label-overline inline-flex items-center gap-1 hover:text-primary" data-testid={`geofence-alert-map-${a.alert_id}`}>
                <MapTrifold size={12} weight="bold"/> MAP
              </button>
              <button onClick={() => ack(a)} className="text-[10px] label-overline inline-flex items-center gap-1 border border-border bg-card px-2 py-1 hover:border-foreground" data-testid={`geofence-alert-ack-${a.alert_id}`}>
                <Check size={12} weight="bold"/> ACKNOWLEDGE
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
