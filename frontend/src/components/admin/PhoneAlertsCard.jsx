import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { pushSupported, isIOS, isStandalone, currentSubscription, enablePush, disablePush } from "@/lib/push";
import { DeviceMobile, BellSimpleRinging, BellSimpleSlash, PaperPlaneTilt } from "@phosphor-icons/react";

export default function PhoneAlertsCard() {
  const [state, setState] = useState("loading");
  const [devices, setDevices] = useState(0);
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    if (!pushSupported()) return setState(isIOS() && !isStandalone() ? "ios-install" : "unsupported");
    if (Notification.permission === "denied") return setState("denied");
    const sub = await currentSubscription();
    try {
      const { data } = await api.get("/push/status", { params: { endpoint: sub?.endpoint } });
      setDevices(data.devices);
      setState(sub && data.this_device ? "on" : "off");
    } catch { setState(sub ? "on" : "off"); }
  };
  useEffect(() => { refresh(); }, []);

  const run = (fn, ok) => async () => {
    setBusy(true);
    try { await fn(); if (ok) toast.success(ok); await refresh(); }
    catch (e) { toast.error(e?.response?.data?.detail || e?.message || "Something went wrong"); await refresh(); }
    finally { setBusy(false); }
  };
  const test = run(async () => {
    const { data } = await api.post("/push/test");
    if (!data.sent) throw new Error("Couldn't reach your devices — turn phone alerts off and on again");
    toast.success(`Test sent to ${data.sent} device${data.sent === 1 ? "" : "s"}`);
  });

  const text = {
    loading: "Checking this device…",
    unsupported: "This browser can't receive notifications. Use Chrome or Samsung Internet on Android, or the Home Screen app on iPhone.",
    "ios-install": "On iPhone: tap Share → Add to Home Screen, open Kelasa from the icon, sign in, then turn alerts on here.",
    denied: "Notifications are blocked for this site. Allow them in your browser or phone settings, then reload.",
    off: "Get a notification on this phone when someone leaves a branch area — even when the console is closed.",
    on: "This device gets leaving-area alerts and each repeat while they stay outside.",
  }[state];

  return (
    <div className="border border-border bg-card p-4 flex items-center justify-between gap-4 flex-wrap" data-testid="phone-alerts-card">
      <div className="flex items-start gap-3 min-w-0">
        <DeviceMobile size={18} weight="bold" className={state === "on" ? "text-[#00A86B] mt-0.5" : "text-primary mt-0.5"}/>
        <div className="min-w-0">
          <div className="text-sm font-medium flex items-center gap-2">
            Phone alerts
            <span className={`text-[9px] font-mono uppercase tracking-wider px-1.5 py-0.5 ${state === "on" ? "bg-[#00A86B] text-white" : "bg-secondary text-muted-foreground"}`} data-testid="phone-alerts-status">
              {state === "on" ? "ON" : "OFF"}
            </span>
            {devices > 0 && <span className="text-[10px] font-mono text-muted-foreground" data-testid="phone-alerts-devices">{devices} device{devices > 1 ? "s" : ""}</span>}
          </div>
          <div className="text-xs text-muted-foreground max-w-xl">{text}</div>
        </div>
      </div>
      <div className="flex items-center gap-2">
        {state === "off" && (
          <button onClick={run(enablePush, "Phone alerts turned on")} disabled={busy} data-testid="phone-alerts-enable"
            className="bg-foreground text-background px-3 py-1.5 text-sm inline-flex items-center gap-1.5 hover:bg-primary transition-colors disabled:opacity-50">
            <BellSimpleRinging size={14} weight="bold"/> Turn on for this phone
          </button>
        )}
        {state === "on" && (
          <>
            <button onClick={test} disabled={busy} data-testid="phone-alerts-test"
              className="border border-border px-3 py-1.5 text-sm inline-flex items-center gap-1.5 hover:border-foreground disabled:opacity-50">
              <PaperPlaneTilt size={14} weight="bold"/> Send test
            </button>
            <button onClick={run(disablePush, "Phone alerts turned off")} disabled={busy} data-testid="phone-alerts-disable"
              className="border border-border px-3 py-1.5 text-sm inline-flex items-center gap-1.5 hover:border-[#FF3B30] hover:text-[#FF3B30] disabled:opacity-50">
              <BellSimpleSlash size={14} weight="bold"/> Turn off
            </button>
          </>
        )}
      </div>
    </div>
  );
}
