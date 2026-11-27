import { useEffect, useState } from "react";
import AppHeader from "@/components/AppHeader";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { fmtTime, fmtDuration } from "@/lib/format";
import { CalendarGrid, Legend, STATUS } from "@/components/calendar/CalendarGrid";
import { DayDetail } from "@/components/calendar/DayDetail";
import { CalendarBlank, ListBullets, CaretLeft, CaretRight, DownloadSimple, ClockCounterClockwise, Camera } from "@phosphor-icons/react";
import PhotoLightbox from "@/components/calendar/PhotoLightbox";
import { dayHasSelfies, dayPhotoShots } from "@/components/calendar/dayPhotos.mjs";

const thisMonth = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; };
const shiftMonth = (m, n) => { const [y, mo] = m.split("-").map(Number); const d = new Date(y, mo - 1 + n, 1); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; };

const ListView = ({ days, onSelect }) => (
  <div className="divide-y divide-border" data-testid="calendar-list">
    {days.filter(d => d.status !== "future").slice().reverse().map(d => {
      const st = STATUS[d.status] || STATUS.future;
      const first = d.sessions[0], last = d.sessions[d.sessions.length - 1];
      return (
        <button key={d.date} onClick={() => onSelect(d.date)} className="w-full py-3 flex items-center gap-3 text-left hover:bg-secondary/50 px-1" data-testid={`list-day-${d.date}`}>
          <div className="w-12 text-center shrink-0">
            <div className="text-lg font-semibold leading-none">{Number(d.date.slice(8))}</div>
            <div className="text-[11px] text-muted-foreground">{new Date(`${d.date}T00:00:00`).toLocaleDateString([], { weekday: "short" })}</div>
          </div>
          <span className={`text-[11px] px-2 py-0.5 rounded shrink-0 w-24 text-center ${st.cell}`}>{st.label}</span>
          <div className="flex-1 min-w-0">
            <div className="font-mono text-sm text-muted-foreground truncate">
              {first ? `${fmtTime(first.check_in)} → ${last.check_out ? fmtTime(last.check_out) : "on duty"}` : (d.holiday || "")}
            </div>
            {d.timing && (
              <div className="text-[11px] text-muted-foreground truncate" data-testid={`list-timing-${d.date}`}>
                {d.timing.off || !d.timing.working ? "Scheduled off" : `${d.timing.start}–${d.timing.end}`}
              </div>
            )}
          </div>
          {dayHasSelfies(d) && <Camera size={16} weight="fill" className="text-muted-foreground shrink-0" data-testid={`list-photo-${d.date}`} aria-hidden="true"/>}
          <div className="font-mono text-sm font-semibold">{d.sessions.length ? fmtDuration(d.net_work_minutes) : ""}</div>
        </button>
      );
    })}
  </div>
);

const MyCorrections = ({ items }) => (
  <section className="bg-card border border-border rounded-xl p-5" data-testid="my-corrections">
    <div className="flex items-center gap-2 mb-3">
      <ClockCounterClockwise size={18} weight="bold"/>
      <span className="font-semibold">Pending Regularization</span>
    </div>
    {items.length === 0 ? <div className="text-sm text-muted-foreground">No correction requests. Tap a day to request one.</div> : (
      <div className="divide-y divide-border">
        {items.map(r => (
          <div key={r.request_id} className="py-2.5 flex items-center justify-between gap-3 text-sm" data-testid={`my-correction-${r.request_id}`}>
            <div>
              <div className="font-medium">{new Date(`${r.date}T00:00:00`).toLocaleDateString([], { day: "numeric", month: "short" })} · <span className="font-mono">{r.check_in}–{r.check_out}</span></div>
              <div className="text-xs text-muted-foreground truncate max-w-[240px]">{r.manager_note ? `Manager: ${r.manager_note}` : r.reason}</div>
            </div>
            <span className={`text-[11px] px-2 py-0.5 uppercase ${r.status === "approved" ? "bg-[#E7F7EE] text-[#15803D]" : r.status === "rejected" ? "bg-[#FDE4E4] text-[#DC2626]" : "bg-[#FEF3C7] text-[#B45309]"}`}>{r.status}</span>
          </div>
        ))}
      </div>
    )}
  </section>
);

export default function CalendarPage() {
  const [month, setMonth] = useState(thisMonth());
  const [view, setView] = useState("calendar");
  const [cal, setCal] = useState(null);
  const [selected, setSelected] = useState(null);
  const [lightbox, setLightbox] = useState(null);
  const [regs, setRegs] = useState([]);

  const load = () => {
    api.get(`/me/calendar?month=${month}`).then(r => setCal(r.data)).catch(() => toast.error("Could not load your calendar"));
    api.get("/regularizations/mine").then(r => setRegs((r.data.items || []).filter(x => x.status !== "cancelled").slice(0, 8))).catch(() => {});
  };
  useEffect(() => { setCal(null); load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [month]);
  useEffect(() => { if (cal && !selected) setSelected(cal.days.some(d => d.date === cal.today) ? cal.today : null); }, [cal, selected]);

  const download = async () => {
    try {
      const res = await api.get(`/me/calendar.csv?month=${month}`, { responseType: "blob" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(res.data); a.download = `my_attendance_${month}.csv`; a.click();
    } catch { toast.error("Download failed"); }
  };

  const title = new Date(`${month}-01T00:00:00`).toLocaleDateString([], { month: "long", year: "numeric" });
  const day = cal?.days.find(d => d.date === selected);
  const c = cal?.counts || {};
  const lightboxDay = lightbox ? cal?.days.find(d => d.date === lightbox.date) : null;
  const lightboxShots = lightboxDay ? dayPhotoShots(lightboxDay) : [];

  // A tap opens the day's selfies. The automatic "today" selection on load does not.
  const openPhotos = (date, index = 0) => {
    setSelected(date);
    const picked = cal?.days.find(d => d.date === date);
    if (picked && dayHasSelfies(picked)) setLightbox({ date, index });
    else setLightbox(null);
  };

  const shift = (delta) => {
    setLightbox(null);
    setMonth(shiftMonth(month, delta));
    setSelected(null);
  };

  return (
    <div className="min-h-screen bg-background">
      <AppHeader/>
      <main className="max-w-6xl mx-auto px-4 sm:px-6 py-6 space-y-5" data-testid="calendar-page">
        <div className="flex items-center justify-between">
          <h1 className="text-3xl sm:text-4xl font-semibold tracking-tight">Calendar</h1>
          <div className="flex items-center gap-2">
            <button onClick={download} className="p-2.5 border border-border rounded-full hover:bg-secondary" title="Download CSV" data-testid="calendar-download"><DownloadSimple size={18}/></button>
            <div className="flex bg-secondary rounded-full p-1" data-testid="calendar-view-toggle">
              <button onClick={() => setView("calendar")} data-testid="view-calendar" className={`p-2 rounded-full transition-colors ${view === "calendar" ? "bg-card shadow text-primary" : "text-muted-foreground"}`}><CalendarBlank size={20} weight="bold"/></button>
              <button onClick={() => setView("list")} data-testid="view-list" className={`p-2 rounded-full transition-colors ${view === "list" ? "bg-card shadow text-primary" : "text-muted-foreground"}`}><ListBullets size={20} weight="bold"/></button>
            </div>
          </div>
        </div>

        <div className="flex items-center justify-between">
          <button onClick={() => shift(-1)} className="p-2.5 rounded-full bg-[#EFF6FF] text-[#1D4ED8]" data-testid="month-prev"><CaretLeft size={20} weight="bold"/></button>
          <div className="text-xl sm:text-2xl font-semibold" data-testid="month-title">{title}</div>
          <button onClick={() => shift(1)} disabled={month >= thisMonth()} className="p-2.5 rounded-full bg-[#EFF6FF] text-[#1D4ED8] disabled:opacity-30" data-testid="month-next"><CaretRight size={20} weight="bold"/></button>
        </div>

        <div className="grid lg:grid-cols-[1fr_360px] gap-5 items-start">
          <div className="space-y-5">
            <section className="bg-card border border-border rounded-xl p-4 sm:p-6 space-y-6">
              {!cal ? <div className="loading-bar"/> : view === "calendar"
                ? <CalendarGrid days={cal.days} today={cal.today} selected={selected} onSelect={openPhotos}/>
                : <ListView days={cal.days} onSelect={openPhotos}/>}
              <div className="border-t border-border pt-4"><Legend/></div>
            </section>
            {cal && (
              <div className="grid grid-cols-3 sm:grid-cols-7 gap-2 text-center" data-testid="calendar-summary">
                {[["Worked", fmtDuration(cal.total_work_minutes)], ["Present", (c.present || 0) + (c.late || 0) + (c.half_day || 0) + (c.punch_error || 0)],
                  ["Absent", c.absent || 0], ["Leave", c.leave || 0], ["Late", c.late || 0], ["Half Day", c.half_day || 0], ["Punch Error", c.punch_error || 0]].map(([k, v]) => (
                  <div key={k} className="bg-card border border-border rounded-lg p-3">
                    <div className="text-lg font-semibold font-mono">{v}</div>
                    <div className="text-[11px] text-muted-foreground uppercase tracking-wide">{k}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="space-y-5 lg:sticky lg:top-20">
            <section className="bg-card border border-border rounded-xl p-5">
              {day ? <DayDetail key={day.date} day={day} today={cal.today} onChanged={load} onOpenPhotos={(index) => openPhotos(day.date, index)}/>
                : <div className="text-sm text-muted-foreground">Tap a day to see your hours. A camera mark opens that day's selfies.</div>}
            </section>
            <MyCorrections items={regs}/>
          </div>
        </div>
      </main>
      {lightbox && lightboxShots.length > 0 && (
        <PhotoLightbox shots={lightboxShots} index={lightbox.index || 0} onClose={() => setLightbox(null)}/>
      )}
    </div>
  );
}
