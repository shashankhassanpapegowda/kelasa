import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import LiveMap from "@/components/LiveMap";
import MapView from "@/components/MapView";
import AuthPhoto from "@/components/AuthPhoto";
import PhotoModal from "@/components/admin/PhotoModal";
import { fmtTime, fmtDuration, fmtAgo, fmtAcc, accClass, today } from "@/lib/format";
import { Broadcast, GpsFix, Path as PathIcon } from "@phosphor-icons/react";

export default function LiveTab() {
  const [liveEmployees, setLiveEmployees] = useState([]);
  const [liveOn, setLiveOn] = useState(true);
  const [date, setDate] = useState(today());
  const [selectedEmp, setSelectedEmp] = useState(null);
  const [empRoute, setEmpRoute] = useState({ pings: [], attendance: [] });
  const [photoModal, setPhotoModal] = useState(null);

  useEffect(() => {
    if (!liveOn) return;
    const fetchLive = async () => {
      try {
        const res = await api.get("/admin/live");
        setLiveEmployees(res.data.employees || []);
      } catch { /* silent polling */ }
    };
    fetchLive();
    const id = setInterval(fetchLive, 15000);
    return () => clearInterval(id);
  }, [liveOn]);

  const openEmp = async (emp) => {
    setSelectedEmp(emp);
    try {
      const res = await api.get(`/admin/employees/${emp.user_id}/route?date=${date}`);
      setEmpRoute(res.data);
    } catch { setEmpRoute({ pings: [], attendance: [] }); }
  };

  useEffect(() => { if (selectedEmp) openEmp(selectedEmp); /* eslint-disable-next-line */ }, [date]);

  return (
    <div data-testid="live-tab">
      <div className="border border-border bg-card">
        <div className="p-4 flex items-center justify-between border-b border-border flex-wrap gap-2">
          <div className="flex items-center gap-2">
            <Broadcast size={16} weight="bold" className={liveOn ? "text-[#00E676]" : "text-muted-foreground"}/>
            <span className="label-overline">Live Field Map</span>
            <span className="text-xs text-muted-foreground ml-1 hidden sm:inline">
              {liveEmployees.filter(e => e.lat != null).length} tracking · refreshes every 15s
            </span>
          </div>
          <div className="flex items-center gap-3">
            <span className="font-mono text-xs text-muted-foreground" data-testid="live-count">{liveEmployees.length} ON DUTY</span>
            <button onClick={() => setLiveOn(v => !v)} data-testid="live-toggle"
              className={`text-[10px] label-overline flex items-center gap-1.5 border px-2 py-1 transition-colors ${liveOn ? "border-[#00E676] text-[#00E676]" : "border-border text-muted-foreground hover:text-foreground"}`}>
              <span className={`w-1.5 h-1.5 rounded-full ${liveOn ? "bg-[#00E676] animate-pulse" : "bg-muted-foreground"}`}/>
              {liveOn ? "LIVE" : "PAUSED"}
            </button>
          </div>
        </div>
        <div className="grid lg:grid-cols-3">
          <div className="lg:col-span-2 h-[440px] border-b lg:border-b-0 lg:border-r border-border">
            {liveEmployees.length === 0
              ? <div className="h-full grid place-items-center text-sm text-muted-foreground p-6 text-center" data-testid="live-empty">No one is on duty right now.</div>
              : <LiveMap employees={liveEmployees}/>}
          </div>
          <div className="max-h-[440px] overflow-y-auto" data-testid="live-list">
            <div className="p-4 border-b border-border"><span className="label-overline">On Duty · Now</span></div>
            <div className="divide-y divide-border">
              {liveEmployees.map(e => (
                <div key={e.user_id} className="p-3 flex items-center gap-3 hover:bg-secondary/40 cursor-pointer" onClick={() => openEmp(e)} data-testid={`live-row-${e.user_id}`}>
                  <AuthPhoto path={e.face_photo_path} className="w-9 h-9 rounded-full object-cover border border-border"
                    fallback={e.picture
                      ? <img src={e.picture} className="w-9 h-9 rounded-full border border-border" alt=""/>
                      : <div className="w-9 h-9 rounded-full bg-secondary grid place-items-center text-xs font-medium">{e.name?.[0]}</div>}/>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium truncate">{e.name}</span>
                      {e.on_break
                        ? <span className="text-[9px] font-mono uppercase tracking-wider bg-yellow-400 text-black px-1.5 py-0.5">BREAK</span>
                        : <span className="text-[9px] font-mono uppercase tracking-wider bg-[#00E676] text-black px-1.5 py-0.5">DUTY</span>}
                    </div>
                    <div className="text-[10px] font-mono text-muted-foreground mt-0.5 flex items-center gap-1.5">
                      <GpsFix size={10} weight="bold" className={e.lat != null ? accClass(e.accuracy) : "text-muted-foreground"}/>
                      {e.lat != null ? `${fmtAcc(e.accuracy)} · ${fmtAgo(e.last_ping)}` : "awaiting GPS"}
                    </div>
                  </div>
                </div>
              ))}
              {liveEmployees.length === 0 && <div className="p-6 text-sm text-muted-foreground">Nobody checked in.</div>}
            </div>
          </div>
        </div>
      </div>

      <div className="mt-6 border border-border bg-card">
        <div className="p-4 flex items-center justify-between border-b border-border flex-wrap gap-2">
          <div className="flex items-center gap-2">
            <PathIcon size={16} weight="bold" className="text-primary"/>
            <span className="label-overline">Route Inspector</span>
            {selectedEmp && <span className="text-sm font-medium ml-2" data-testid="selected-emp">{selectedEmp.name}</span>}
          </div>
          <div className="flex items-center gap-3">
            <input type="date" value={date} onChange={e => setDate(e.target.value)} data-testid="route-date"
              className="bg-background border border-border px-3 py-1.5 text-sm font-mono"/>
            <span className="font-mono text-xs text-muted-foreground">{empRoute.pings?.length || 0} POINTS</span>
          </div>
        </div>
        <div className="grid lg:grid-cols-3">
          <div className="lg:col-span-2 h-[460px] border-b lg:border-b-0 lg:border-r border-border">
            {!selectedEmp
              ? <div className="h-full grid place-items-center text-sm text-muted-foreground p-6 text-center">Pick someone from the on-duty list or the Team tab to inspect their route.</div>
              : empRoute.pings?.length === 0
                ? <div className="h-full grid place-items-center text-sm text-muted-foreground p-6 text-center">No location pings on {date}.</div>
                : <MapView pings={empRoute.pings}/>}
          </div>
          <div className="max-h-[460px] overflow-y-auto" data-testid="timeline">
            <div className="p-4 border-b border-border"><span className="label-overline">Timeline</span></div>
            <div className="divide-y divide-border">
              {(empRoute.attendance || []).map(r => (
                <div key={r.record_id} className="p-4">
                  <div className="flex items-center gap-2 mb-2">
                    {r.check_in_photo_path && (
                      <button onClick={() => setPhotoModal({ path: r.check_in_photo_path, label: "Check-In", record: { ...r, name: selectedEmp?.name }, kind: "in" })}>
                        <AuthPhoto path={r.check_in_photo_path} className="w-10 h-10 object-cover border border-border" fallback={<div className="w-10 h-10 bg-secondary"/>}/>
                      </button>
                    )}
                    {r.check_out_photo_path && (
                      <button onClick={() => setPhotoModal({ path: r.check_out_photo_path, label: "Check-Out", record: { ...r, name: selectedEmp?.name }, kind: "out" })}>
                        <AuthPhoto path={r.check_out_photo_path} className="w-10 h-10 object-cover border border-border" fallback={<div className="w-10 h-10 bg-secondary"/>}/>
                      </button>
                    )}
                  </div>
                  <div className="text-xs label-overline mb-1">Session</div>
                  <div className="font-mono text-sm">{fmtTime(r.check_in)} → {r.check_out ? fmtTime(r.check_out) : "live"}</div>
                  <div className="text-xs text-muted-foreground mt-1">
                    {fmtDuration(r.net_work_minutes ?? r.duration_minutes)} net · {r.total_break_minutes || 0}m break
                    {r.late_by_minutes > 0 && <span className="text-[#FF3B30]"> · {r.late_by_minutes}m late</span>}
                  </div>
                </div>
              ))}
              {(empRoute.pings || []).slice(0, 50).map((p) => (
                <div key={p.ping_id} className="p-3 flex items-center justify-between">
                  <div>
                    <div className="font-mono text-xs">{fmtTime(p.timestamp)}</div>
                    <div className={`font-mono text-[10px] ${accClass(p.accuracy)}`}><GpsFix size={10} className="inline mr-0.5"/>{fmtAcc(p.accuracy)}</div>
                  </div>
                  <div className="font-mono text-[10px] text-muted-foreground">{p.lat.toFixed(5)}, {p.lng.toFixed(5)}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <PhotoModal data={photoModal} onClose={() => setPhotoModal(null)}/>
    </div>
  );
}
