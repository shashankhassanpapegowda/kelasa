import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { pushSupported, isIOS, isStandalone, currentSubscription, enablePush, disablePush, setDeviceSilent } from "@/lib/push";
import { DeviceMobile, BellSimpleRinging, BellSimpleSlash, PaperPlaneTilt, SpeakerHigh, SpeakerSlash } from "@phosphor-icons/react";

const COPY = {
  admin: {
    title: "Phone alerts",
    off: "Get a notification on this phone when someone leaves a branch area — even when the console is closed.",
    on: "This device gets leaving-area alerts and each repeat while they stay outside.",
  },
  employee: {
    title: "Leave updates on your phone",
    off: "Get a notification on this phone as soon as your leave is approved or rejected.",
    on: "This phone gets a notification when your leave is approved or rejected, with the reason.",
  },
};

export default function PhoneAlertsCard({ audience = "admin", refreshKey = 0 }) {
  const [state, setState] = useState("loading");
  const [devices, setDevices] = useState(0);
  const [silent, setSilent] = useState(false);
  const [busy, setBusy] = useState(false);
  const copy = COPY[audience];

  const refresh = async () => {
    if (!pushSupported()) return setState(isIOS() && !isStandalone() ? "ios-install" : "unsupported");
    if (Notification.permission === "denied") return setState("denied");
    const sub = await currentSubscription();
    try {
      const { data } = await api.get("/push/status", { params: { endpoint: sub?.endpoint } });
      setDevices(data.devices);
      setSilent(!!data.silent);
      setState(sub && data.this_device ? "on" : "off");
    } catch { setState(sub ? "on" : "off"); }
  };
  useEffect(() => { refresh(); }, [refreshKey]);

  const run = (fn, ok) => async () => {
    setBusy(true);
    try { await fn(); if (ok) toast.success(ok); await refresh(); }
    catch (e) { toast.error(e?.response?.data?.detail || e?.message || "Something went wrong"); await refresh(); }
    finally { setBusy(false); }
  };
  const test = run(async () => {
    const { data } = await api.post("/push/test");
    if (!data.sent) throw new Error("Couldn't reach your devices — turn notifications off and on again");
    toast.success(`Test sent to ${data.sent} device${data.sent === 1 ? "" : "s"}`);
  });
  const toggleSound = run(() => setDeviceSilent(!silent), silent ? "Sound on for this phone" : "Silent on this phone");

  const text = {
    loading: "Checking this device…",
    unsupported: "This browser can't receive notifications. Use Chrome or Samsung Internet on Android, or the Home Screen app on iPhone.",
    "ios-install": "On iPhone: tap Share → Add to Home Screen, open Kelasa from the icon, sign in, then turn this on here.",
    denied: "Notifications are blocked for this site. Allow them in your browser or phone settings, then reload.",
    off: copy.off,
    on: copy.on,
  }[state];

  const btn = "border border-border px-3 py-1.5 text-sm inline-flex items-center gap-1.5 hover:border-foreground disabled:opacity-50";

  return (
    <div className="border border-border bg-card p-4 flex items-center justify-between gap-4 flex-wrap" data-testid="phone-alerts-card">
      <div className="flex items-start gap-3 min-w-0">
        <DeviceMobile size={18} weight="bold" className={state === "on" ? "text-[#00A86B] mt-0.5" : "text-primary mt-0.5"}/>
        <div className="min-w-0">
          <div className="text-sm font-medium flex items-center gap-2 flex-wrap">
            {copy.title}
            <span className={`text-[9px] font-mono uppercase tracking-wider px-1.5 py-0.5 ${state === "on" ? "bg-[#00A86B] text-white" : "bg-secondary text-muted-foreground"}`} data-testid="phone-alerts-status">
              {state === "on" ? "ON" : "OFF"}
            </span>
            {state === "on" && (
              <span className="text-[9px] font-mono uppercase tracking-wider px-1.5 py-0.5 border border-border" data-testid="phone-alerts-sound-status">
                {silent ? "SILENT" : "SOUND"}
              </span>
            )}
            {devices > 0 && <span className="text-[10px] font-mono text-muted-foreground" data-testid="phone-alerts-devices">{devices} device{devices > 1 ? "s" : ""}</span>}
          </div>
          <div className="text-xs text-muted-foreground max-w-xl">{text}</div>
        </div>
      </div>
      <div className="flex items-center gap-2 flex-wrap">
        {state === "off" && (
          <button onClick={run(enablePush, "Notifications turned on")} disabled={busy} data-testid="phone-alerts-enable"
            className="bg-foreground text-background px-3 py-1.5 text-sm inline-flex items-center gap-1.5 hover:bg-primary transition-colors disabled:opacity-50">
            <BellSimpleRinging size={14} weight="bold"/> Turn on for this phone
          </button>
        )}
        {state === "on" && (
          <>
            <button onClick={toggleSound} disabled={busy} className={btn} data-testid="phone-alerts-sound-toggle">
              {silent ? <SpeakerSlash size={14} weight="bold"/> : <SpeakerHigh size={14} weight="bold"/>}
              {silent ? "Silent" : "Sound"}
            </button>
            <button onClick={test} disabled={busy} className={btn} data-testid="phone-alerts-test">
              <PaperPlaneTilt size={14} weight="bold"/> Send test
            </button>
            <button onClick={run(disablePush, "Notifications turned off")} disabled={busy} data-testid="phone-alerts-disable"
              className={`${btn} hover:border-[#FF3B30] hover:text-[#FF3B30]`}>
              <BellSimpleSlash size={14} weight="bold"/> Turn off
            </button>
          </>
        )}
      </div>
    </div>
  );
}
