import { useEffect, useRef, useState } from "react";
import AppHeader from "@/components/AppHeader";
import CelebrationsCard from "@/components/CelebrationsCard";
import ProfileNudge from "@/components/ProfileNudge";
import CelebrationBanner from "@/components/CelebrationBanner";
import MapView from "@/components/MapView";
import FaceCapture from "@/components/FaceCapture";
import AuthPhoto from "@/components/AuthPhoto";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { useAuth } from "@/lib/auth";
import { useNavigate } from "react-router-dom";
import { getAccuratePosition, startLiveWatch } from "@/lib/geo";
import { Camera, Clock, Path as PathIcon, MapPin, ArrowsClockwise, GpsFix, WarningCircle, Coffee, ArrowCounterClockwise, Megaphone, PushPin } from "@phosphor-icons/react";

const PING_INTERVAL_MS = 30_000;

const distM = (a, b) => {
  const R = 6371000, rad = (d) => d * Math.PI / 180;
  const dLat = rad(b.lat - a.lat), dLng = rad(b.lng - a.lng);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
};

const zoneFor = (fence, pos) => {
  if (!fence || fence.field_staff || !fence.branches.length || !pos) return null;
  const slack = Math.min(pos.accuracy || 0, fence.tolerance_m);
  let best = null;
  for (const b of fence.branches) {
    const gap = distM(pos, b) - b.radius_m;
    if (!best || gap < best.gap) best = { name: b.name, gap, inside: gap <= slack };
  }
  return best;
};

const fmtTime = (iso) => iso ? new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : "—";
const fmtDate = (iso) => iso ? new Date(iso).toLocaleDateString([], { day: '2-digit', month: 'short' }) : "—";
const fmtDuration = (mins) => {
  if (mins == null) return "—";
  const h = Math.floor(mins / 60); const m = mins % 60;
  return `${h}h ${m}m`;
};
const fmtAccuracy = (m) => {
  if (m == null) return "—";
  if (m < 1000) return `±${Math.round(m)}m`;
  return `±${(m/1000).toFixed(1)}km`;
};
const accClass = (m) => {
  if (m == null) return "text-muted-foreground";
  if (m > 200) return "text-[#FF3B30]";
  if (m > 100) return "text-yellow-600";
  return "text-[#00E676]";
};

export default function Dashboard() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [active, setActive] = useState(null);
  const [todayRecords, setTodayRecords] = useState([]);
  const [pings, setPings] = useState([]);
  const [history, setHistory] = useState([]);
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState("00:00:00");
  const [faceOpen, setFaceOpen] = useState(false);
  const [faceMode, setFaceMode] = useState("in");
  const [pendingGeo, setPendingGeo] = useState(null);
  const [livePos, setLivePos] = useState(null);
  const [notice, setNotice] = useState(null);
  const [fence, setFence] = useState(null);
  const [profile, setProfile] = useState(null);
  const [zone, setZone] = useState(null);
  const pingTimer = useRef(null);
  const tickTimer = useRef(null);
  const liveStopRef = useRef(null);
  const lastPingAtRef = useRef(0);

  useEffect(() => {
    if (user && !user.face_enrolled) navigate("/enroll", { replace: true });
  }, [user, navigate]);

  const refresh = async () => {
    const [t, l, h] = await Promise.all([
      api.get("/attendance/today"),
      api.get("/location/today"),
      api.get("/attendance/me?limit=20"),
    ]);
    setActive(t.data.active);
    setTodayRecords(t.data.today_records || []);
    setPings(l.data.pings || []);
    setHistory(h.data.records || []);
  };

  useEffect(() => { refresh(); }, []);

  useEffect(() => {
    api.get("/attendance/geofence").then(r => setFence(r.data)).catch(() => {});
    api.get("/profile/me").then(r => setProfile(r.data)).catch(() => {});
  }, []);

  useEffect(() => {
    api.get("/announcements?limit=1")
      .then(r => setNotice((r.data.announcements || [])[0] || null))
      .catch(() => {});
  }, []);

  // Elapsed clock + live watcher when active
  useEffect(() => {
    if (pingTimer.current) { clearInterval(pingTimer.current); pingTimer.current = null; }
    if (tickTimer.current) { clearInterval(tickTimer.current); tickTimer.current = null; }
    if (liveStopRef.current) { liveStopRef.current(); liveStopRef.current = null; }
    if (!active) { setElapsed("00:00:00"); setLivePos(null); return; }

    const tick = () => {
      const start = new Date(active.check_in).getTime();
      const diff = Math.max(0, Math.floor((Date.now() - start) / 1000));
      const h = String(Math.floor(diff / 3600)).padStart(2, "0");
      const m = String(Math.floor((diff % 3600) / 60)).padStart(2, "0");
      const s = String(diff % 60).padStart(2, "0");
      setElapsed(`${h}:${m}:${s}`);
    };
    tick();
    tickTimer.current = setInterval(tick, 1000);

    if (!active.on_break) {
      // start LIVE watcher — pushes ping at most every PING_INTERVAL_MS
      liveStopRef.current = startLiveWatch(async (p) => {
        setLivePos(p);
        const now = Date.now();
        if (now - lastPingAtRef.current < PING_INTERVAL_MS) return;
        lastPingAtRef.current = now;
        try {
          await api.post("/location/ping", p);
          const l = await api.get("/location/today");
          setPings(l.data.pings || []);
        } catch (e) {
          console.warn("ping failed", e?.response?.data?.detail || e.message);
        }
      });
    }

    return () => {
      if (pingTimer.current) clearInterval(pingTimer.current);
      if (tickTimer.current) clearInterval(tickTimer.current);
      if (liveStopRef.current) liveStopRef.current();
    };
  }, [active?.record_id, active?.on_break]);

  const startCheck = async (mode) => {
    setBusy(true);
    try {
      const g = await getAccuratePosition({ desiredAccuracy: 30, fallbackAccuracy: 150, maxWait: 15000 });
      if (g.accuracy > 200) {
        toast.warning(`Low GPS accuracy (±${Math.round(g.accuracy)}m). Move outside / enable Precise Location.`);
      }
      const z = zoneFor(fence, g);
      setZone(z);
      if (z && !z.inside) {
        toast.error(`You are ${Math.round(z.gap)} m outside ${z.name}. Move inside a branch area to punch ${mode}.`);
        return;
      }
      setPendingGeo(g);
      setFaceMode(mode);
      setFaceOpen(true);
    } catch (e) {
      toast.error(e?.message || "Could not get your location.");
    } finally {
      setBusy(false);
    }
  };

  const handleFaceCapture = async ({ descriptor, image_b64 }) => {
    const payload = {
      lat: pendingGeo.lat, lng: pendingGeo.lng, accuracy: pendingGeo.accuracy,
      descriptor, image_b64,
    };
    try {
      if (faceMode === "in") {
        const res = await api.post("/attendance/checkin", payload);
        if (res.data.late_by_minutes > 0) {
          toast.warning(`Checked in — you are ${res.data.late_by_minutes} min late.`);
        } else {
          toast.success("Checked in. Tracking started.");
        }
      } else {
        await api.post("/attendance/checkout", payload);
        toast.success("Checked out. Session saved.");
      }
      setFaceOpen(false);
      setPendingGeo(null);
      await refresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed");
      throw e;
    }
  };

  const handleBreak = async (action) => {
    setBusy(true);
    try {
      let pos = {};
      try {
        const g = await getAccuratePosition({ desiredAccuracy: 100, maxWait: 8000 });
        pos = { lat: g.lat, lng: g.lng };
      } catch (_) { /* break location is optional */ }
      const url = action === "start" ? "/attendance/break/start" : "/attendance/break/end";
      await api.post(url, pos);
      toast.success(action === "start" ? "Break started — tracking paused." : "Break ended — tracking resumed.");
      await refresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed");
    } finally {
      setBusy(false);
    }
  };

  const todayMinutes = todayRecords.reduce((acc, r) => acc + (r.net_work_minutes || r.duration_minutes || 0), 0);
  const todayBreakMinutes = todayRecords.reduce((acc, r) => acc + (r.total_break_minutes || 0), 0);
  const onBreak = !!active?.on_break;
  const lateBy = todayRecords[0]?.late_by_minutes ?? null;

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <AppHeader/>
      <main className="flex-1">
        <div className="px-4 sm:px-6 py-6">
          <div className="flex items-end justify-between gap-4 flex-wrap">
            <div>
              <div className="label-overline" data-testid="dashboard-overline">My Day</div>
              <h1 className="text-3xl sm:text-4xl font-semibold tracking-tight mt-1">{new Date().toLocaleDateString([], { weekday:'long', day:'2-digit', month:'long' })}</h1>
              {user?.shift_start && (
                <div className="mt-2 text-xs font-mono text-muted-foreground">
                  Shift · <span className="text-foreground">{user.shift_start}</span>{user.shift_end ? ` – ${user.shift_end}` : ""} · Break limit {user.break_max_minutes ?? 60}m
                </div>
              )}
            </div>
            <button onClick={refresh} className="text-xs label-overline flex items-center gap-2 hover:text-foreground" data-testid="refresh-btn">
              <ArrowsClockwise size={14} weight="bold"/> Refresh
            </button>
          </div>

          <CelebrationBanner/>
          {/* Status card */}
          {notice && (
            <div className="mt-6 border border-border bg-card p-4 flex items-start gap-3" data-testid="dashboard-notice">
              {notice.pinned ? <PushPin size={16} weight="fill" className="text-primary mt-0.5 shrink-0"/> : <Megaphone size={16} weight="bold" className="text-primary mt-0.5 shrink-0"/>}
              <div className="min-w-0">
                <div className="text-sm font-medium">{notice.title}</div>
                {notice.body && <p className="text-sm text-muted-foreground mt-0.5 line-clamp-2">{notice.body}</p>}
                <div className="text-[10px] font-mono text-muted-foreground mt-1">{notice.author_name}</div>
              </div>
            </div>
          )}

          <div className="mt-6 grid lg:grid-cols-3 gap-0 border border-border bg-card">
            <div className="lg:col-span-2 p-6 sm:p-8 border-b lg:border-b-0 lg:border-r border-border">
              <div className="flex items-center gap-3 flex-wrap">
                <span className={`inline-block w-2.5 h-2.5 rounded-full ${onBreak ? "bg-yellow-400" : active ? "bg-[#00E676]" : "bg-[#52525B]"}`} data-testid="duty-indicator"/>
                <span className="label-overline" data-testid="duty-status">{onBreak ? "ON BREAK" : active ? "ON DUTY" : "OFF DUTY"}</span>
                {livePos && !onBreak && (
                  <span className={`text-[10px] font-mono inline-flex items-center gap-1 ${accClass(livePos.accuracy)}`}>
                    <GpsFix size={12} className="animate-pulse"/> LIVE · {fmtAccuracy(livePos.accuracy)}
                  </span>
                )}
                {lateBy > 0 && (
                  <span className="text-[10px] font-mono uppercase tracking-wider bg-[#FF3B30] text-white px-1.5 py-0.5">
                    LATE BY {lateBy}m
                  </span>
                )}
              </div>
              <div className="mt-6 flex items-end gap-6 flex-wrap">
                <div>
                  <div className="label-overline mb-1">Elapsed</div>
                  <div className="font-mono text-5xl font-semibold tracking-tight" data-testid="elapsed-time">{elapsed}</div>
                </div>
                {active && (
                  <div>
                    <div className="label-overline mb-1">Started</div>
                    <div className="font-mono text-lg" data-testid="start-time">{fmtTime(active.check_in)}</div>
                  </div>
                )}
                {active && (
                  <div>
                    <div className="label-overline mb-1">Breaks Today</div>
                    <div className="font-mono text-lg" data-testid="break-total">{todayBreakMinutes}m</div>
                  </div>
                )}
              </div>

              <div className="mt-8 flex flex-wrap items-center gap-3">
                {!active ? (
                  <button onClick={() => startCheck("in")} disabled={busy} data-testid="check-in-btn"
                    className="bg-foreground text-background px-6 py-4 inline-flex items-center gap-3 hover:bg-primary disabled:opacity-50 transition-colors">
                    <Camera size={18} weight="bold"/>
                    <span className="font-medium">Face Check-In</span>
                  </button>
                ) : (
                  <>
                    <button onClick={() => startCheck("out")} disabled={busy || onBreak} data-testid="check-out-btn"
                      className="bg-[#FF3B30] text-white px-6 py-4 inline-flex items-center gap-3 hover:bg-[#d93128] disabled:opacity-50 transition-colors">
                      <Camera size={18} weight="bold"/>
                      <span className="font-medium">Face Check-Out</span>
                    </button>
                    {!onBreak ? (
                      <button onClick={() => handleBreak("start")} disabled={busy} data-testid="break-start-btn"
                        className="border border-border bg-card px-5 py-4 inline-flex items-center gap-2 hover:bg-secondary disabled:opacity-50">
                        <Coffee size={16} weight="bold"/>
                        <span className="font-medium">Start Break</span>
                      </button>
                    ) : (
                      <button onClick={() => handleBreak("end")} disabled={busy} data-testid="break-end-btn"
                        className="bg-yellow-400 text-black px-5 py-4 inline-flex items-center gap-2 hover:bg-yellow-300 disabled:opacity-50">
                        <ArrowCounterClockwise size={16} weight="bold"/>
                        <span className="font-medium">End Break · Resume</span>
                      </button>
                    )}
                  </>
                )}
                {busy && <div className="loading-bar w-full mt-2"/>}
              </div>
              {fence && (
                <div className="mt-4 text-xs font-mono flex items-center gap-1.5" data-testid="geofence-zone">
                  <MapPin size={13} weight="bold" className={zone ? (zone.inside ? "text-[#00E676]" : "text-[#FF3B30]") : "text-muted-foreground"}/>
                  {fence.field_staff
                    ? <span className="text-muted-foreground">Field staff · you can punch from anywhere</span>
                    : !fence.branches.length
                      ? <span className="text-muted-foreground">No branch area set · punch from anywhere</span>
                      : zone
                        ? zone.inside
                          ? <span className="text-[#00E676]">Inside {zone.name}</span>
                          : <span className="text-[#FF3B30]">{Math.round(zone.gap)} m outside {zone.name}</span>
                        : <span className="text-foreground/80" data-testid="geofence-allowed-branches">You can check in at: {fence.branches.map(b => b.name).join(", ")}</span>}
                </div>
              )}
              <p className="mt-3 text-xs text-muted-foreground flex items-start gap-1.5 max-w-md">
                <WarningCircle size={14} weight="bold" className="mt-0.5 shrink-0"/>
                <span>Allow camera + <strong>Precise Location</strong>. Location tracking pauses during breaks.</span>
              </p>
            </div>

            <div className="grid grid-cols-2 lg:grid-cols-1">
              <Stat label="Today Sessions" value={todayRecords.length} testid="stat-sessions"/>
              <Stat label="Net Work Today" value={fmtDuration(todayMinutes)} testid="stat-worked"/>
              <Stat label="Pings Logged" value={pings.length} testid="stat-pings" full/>
            </div>
          </div>

          <ProfileNudge profile={profile}/>
          <CelebrationsCard/>

          {/* Map + history */}
          <div className="mt-6 grid lg:grid-cols-3 gap-0 border border-border bg-card">
            <div className="lg:col-span-2 border-b lg:border-b-0 lg:border-r border-border">
              <div className="p-4 flex items-center justify-between border-b border-border">
                <div className="flex items-center gap-2">
                  <PathIcon size={16} weight="bold" className="text-primary"/>
                  <span className="label-overline">Today's Route</span>
                </div>
                <span className="font-mono text-xs text-muted-foreground">{pings.length} POINTS</span>
              </div>
              <div className="h-[420px]">
                {pings.length === 0 ? (
                  <div className="h-full grid place-items-center text-sm text-muted-foreground p-6 text-center">
                    <div>
                      <MapPin size={28} weight="thin" className="mx-auto mb-3 opacity-50"/>
                      Check in to start tracking your route. Live GPS updates as you move.
                    </div>
                  </div>
                ) : <MapView pings={pings}/>}
              </div>
            </div>

            <div>
              <div className="p-4 flex items-center justify-between border-b border-border">
                <div className="flex items-center gap-2">
                  <Clock size={16} weight="bold" className="text-primary"/>
                  <span className="label-overline">Recent Sessions</span>
                </div>
              </div>
              <div className="divide-y divide-border max-h-[420px] overflow-y-auto" data-testid="history-list">
                {history.length === 0 && <div className="p-6 text-sm text-muted-foreground">No history yet.</div>}
                {history.map(r => (
                  <div key={r.record_id} className="p-4 flex items-center gap-3">
                    <AuthPhoto path={r.check_in_photo_path} className="w-12 h-12 object-cover border border-border"
                      fallback={<div className="w-12 h-12 bg-secondary border border-border"/>}/>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <div className="text-sm font-medium">{fmtDate(r.check_in)}</div>
                        {r.late_by_minutes > 0 && <span className="text-[9px] font-mono uppercase bg-[#FF3B30]/15 text-[#FF3B30] px-1">+{r.late_by_minutes}m late</span>}
                        {r.over_break && <span className="text-[9px] font-mono uppercase bg-yellow-500/20 text-yellow-700 px-1">over-break</span>}
                      </div>
                      <div className="font-mono text-xs text-muted-foreground mt-0.5">
                        {fmtTime(r.check_in)} → {r.check_out ? fmtTime(r.check_out) : "active"}
                        {r.total_break_minutes > 0 && <span> · {r.total_break_minutes}m break</span>}
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="font-mono text-sm font-semibold">{fmtDuration(r.net_work_minutes ?? r.duration_minutes)}</div>
                      <div className="text-[10px] label-overline mt-0.5">{r.status}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </main>

      <FaceCapture
        open={faceOpen}
        title={faceMode === "in" ? "Face Check-In" : "Face Check-Out"}
        subtitle={faceMode === "in" ? "Verify your identity to start your duty session." : "Verify your identity to end your duty session."}
        cta={faceMode === "in" ? "Check In" : "Check Out"}
        onClose={() => { setFaceOpen(false); setPendingGeo(null); }}
        onCapture={handleFaceCapture}
      />
    </div>
  );
}

const Stat = ({ label, value, testid, full }) => (
  <div className={`p-6 border-b border-border lg:border-b ${full ? "col-span-2 lg:col-span-1" : ""}`}>
    <div className="label-overline mb-2">{label}</div>
    <div className="stat-value" data-testid={testid}>{value}</div>
  </div>
);
