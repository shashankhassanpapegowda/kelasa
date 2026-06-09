import { useEffect, useRef, useState } from "react";
import AppHeader from "@/components/AppHeader";
import MapView from "@/components/MapView";
import FaceCapture from "@/components/FaceCapture";
import AuthPhoto from "@/components/AuthPhoto";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { useAuth } from "@/lib/auth";
import { useNavigate } from "react-router-dom";
import { getAccuratePosition } from "@/lib/geo";
import { Play, Stop, Clock, Path as PathIcon, MapPin, ArrowsClockwise, Camera, GpsFix, WarningCircle } from "@phosphor-icons/react";

const PING_INTERVAL_MS = 60_000;

const fmtTime = (iso) => iso ? new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : "—";
const fmtDate = (iso) => iso ? new Date(iso).toLocaleDateString([], { day: '2-digit', month: 'short' }) : "—";
const fmtDuration = (mins) => {
  if (mins == null) return "—";
  const h = Math.floor(mins / 60); const m = mins % 60;
  return `${h}h ${m}m`;
};
const fmtAccuracy = (m) => m == null ? "—" : m < 1000 ? `±${Math.round(m)}m` : `±${(m/1000).toFixed(1)}km`;

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
  const [faceMode, setFaceMode] = useState("in"); // "in" | "out"
  const [pendingGeo, setPendingGeo] = useState(null);
  const [geoStatus, setGeoStatus] = useState({ accuracy: null, fetching: false });
  const pingTimer = useRef(null);
  const tickTimer = useRef(null);

  useEffect(() => {
    if (user && !user.face_enrolled) {
      navigate("/enroll", { replace: true });
    }
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
    if (pingTimer.current) { clearInterval(pingTimer.current); pingTimer.current = null; }
    if (tickTimer.current) { clearInterval(tickTimer.current); tickTimer.current = null; }
    if (!active) { setElapsed("00:00:00"); return; }
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

    const sendPing = async () => {
      try {
        const g = await getAccuratePosition({ desiredAccuracy: 50, maxWait: 10000 });
        await api.post("/location/ping", g);
        const l = await api.get("/location/today");
        setPings(l.data.pings || []);
      } catch (e) {
        console.warn("ping failed", e.message);
      }
    };
    pingTimer.current = setInterval(sendPing, PING_INTERVAL_MS);
    return () => {
      if (pingTimer.current) clearInterval(pingTimer.current);
      if (tickTimer.current) clearInterval(tickTimer.current);
    };
  }, [active?.record_id]);

  const startCheck = async (mode) => {
    setBusy(true);
    setGeoStatus({ accuracy: null, fetching: true });
    try {
      const g = await getAccuratePosition({ desiredAccuracy: 30, fallbackAccuracy: 150, maxWait: 15000 });
      setGeoStatus({ accuracy: g.accuracy, fetching: false });
      if (g.accuracy > 200) {
        toast.warning(`Low location accuracy (±${Math.round(g.accuracy)}m). Move outside / enable Precise Location for best results.`);
      }
      setPendingGeo(g);
      setFaceMode(mode);
      setFaceOpen(true);
    } catch (e) {
      setGeoStatus({ accuracy: null, fetching: false });
      toast.error(e?.message || "Could not get your location. Enable Precise Location.");
    } finally {
      setBusy(false);
    }
  };

  const handleFaceCapture = async ({ descriptor, image_b64 }) => {
    const payload = {
      lat: pendingGeo.lat,
      lng: pendingGeo.lng,
      accuracy: pendingGeo.accuracy,
      descriptor,
      image_b64,
    };
    try {
      if (faceMode === "in") {
        await api.post("/attendance/checkin", payload);
        toast.success("Checked in. Tracking started.");
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

  const todayMinutes = todayRecords.reduce((acc, r) => acc + (r.duration_minutes || 0), 0);

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <AppHeader/>
      <main className="flex-1">
        <div className="px-4 sm:px-6 py-6">
          <div className="flex items-end justify-between gap-4 flex-wrap">
            <div>
              <div className="label-overline" data-testid="dashboard-overline">My Day</div>
              <h1 className="text-3xl sm:text-4xl font-semibold tracking-tight mt-1">{new Date().toLocaleDateString([], { weekday:'long', day:'2-digit', month:'long' })}</h1>
            </div>
            <button onClick={refresh} className="text-xs label-overline flex items-center gap-2 hover:text-foreground" data-testid="refresh-btn">
              <ArrowsClockwise size={14} weight="bold"/> Refresh
            </button>
          </div>

          {/* Status card */}
          <div className="mt-6 grid lg:grid-cols-3 gap-0 border border-border bg-card">
            <div className="lg:col-span-2 p-6 sm:p-8 border-b lg:border-b-0 lg:border-r border-border">
              <div className="flex items-center gap-3">
                <span className={`inline-block w-2.5 h-2.5 rounded-full ${active ? "bg-[#00E676]" : "bg-[#52525B]"}`} data-testid="duty-indicator"/>
                <span className="label-overline" data-testid="duty-status">{active ? "ON DUTY" : "OFF DUTY"}</span>
                {geoStatus.fetching && <span className="text-[10px] font-mono text-muted-foreground ml-2 inline-flex items-center gap-1"><GpsFix size={12} className="animate-pulse"/> getting GPS…</span>}
                {geoStatus.accuracy != null && (
                  <span className={`text-[10px] font-mono ml-2 inline-flex items-center gap-1 ${geoStatus.accuracy > 200 ? "text-[#FF3B30]" : geoStatus.accuracy > 100 ? "text-yellow-600" : "text-[#00E676]"}`}>
                    <GpsFix size={12}/> {fmtAccuracy(geoStatus.accuracy)}
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
              </div>
              <div className="mt-8">
                {!active ? (
                  <button onClick={() => startCheck("in")} disabled={busy} data-testid="check-in-btn"
                    className="bg-foreground text-background px-6 py-4 inline-flex items-center gap-3 hover:bg-primary disabled:opacity-50 transition-colors">
                    <Camera size={18} weight="bold"/>
                    <span className="font-medium">Face Check-In · Start Tracking</span>
                  </button>
                ) : (
                  <button onClick={() => startCheck("out")} disabled={busy} data-testid="check-out-btn"
                    className="bg-[#FF3B30] text-white px-6 py-4 inline-flex items-center gap-3 hover:bg-[#d93128] disabled:opacity-50 transition-colors">
                    <Camera size={18} weight="bold"/>
                    <span className="font-medium">Face Check-Out · End Session</span>
                  </button>
                )}
                {busy && <div className="loading-bar mt-4"/>}
                <p className="mt-3 text-xs text-muted-foreground flex items-start gap-1.5 max-w-md">
                  <WarningCircle size={14} weight="bold" className="mt-0.5 shrink-0"/>
                  Allow camera + <strong>Precise Location</strong>. Coarse / WiFi-based location can be off by 10+ km.
                </p>
              </div>
            </div>

            <div className="grid grid-cols-2 lg:grid-cols-1">
              <Stat label="Today Sessions" value={todayRecords.length} testid="stat-sessions"/>
              <Stat label="Today Worked" value={fmtDuration(todayMinutes)} testid="stat-worked"/>
              <Stat label="Pings Logged" value={pings.length} testid="stat-pings" full/>
            </div>
          </div>

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
                      Check in to start tracking your route. Pings record every minute.
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
                    <AuthPhoto
                      path={r.check_in_photo_path}
                      className="w-12 h-12 object-cover border border-border"
                      fallback={<div className="w-12 h-12 bg-secondary border border-border"/>}
                    />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium">{fmtDate(r.check_in)}</div>
                      <div className="font-mono text-xs text-muted-foreground mt-0.5">
                        {fmtTime(r.check_in)} → {r.check_out ? fmtTime(r.check_out) : "active"}
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="font-mono text-sm font-semibold">{r.duration_minutes != null ? fmtDuration(r.duration_minutes) : "—"}</div>
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
