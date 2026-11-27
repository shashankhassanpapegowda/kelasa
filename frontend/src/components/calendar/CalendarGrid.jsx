import { Camera, Warning } from "@phosphor-icons/react";
import { dayHasSelfies } from "./dayPhotos.mjs";

export const STATUS = {
  present: { label: "Present", cell: "bg-[#E7F7EE] text-[#15803D]", dot: "bg-[#16A34A]" },
  absent: { label: "Absent", cell: "bg-[#FDE4E4] text-[#DC2626]", dot: "bg-[#DC2626]" },
  leave: { label: "On leave", cell: "bg-[#F0E9FF] text-[#7C3AED]", dot: "bg-[#8B5CF6]" },
  half_day: { label: "Half Day", cell: "bg-[#FCE7F3] text-[#BE185D]", dot: "bg-[#EC4899]" },
  weekly_off: { label: "Week Off", cell: "bg-[#E5E7EB] text-[#4B5563]", dot: "bg-[#4B5563]" },
  holiday: { label: "Holiday", cell: "bg-[#DDF4F6] text-[#0E7490]", dot: "bg-[#0891B2]" },
  late: { label: "Late", cell: "bg-[#FFEDD5] text-[#C2410C]", dot: "bg-[#F97316]" },
  punch_error: { label: "Punch Error", cell: "bg-[#FEF9C3] text-[#A16207]", dot: null },
  today: { label: "Today", cell: "bg-[#EFF6FF] text-[#1D4ED8]", dot: null },
  future: { label: "Upcoming", cell: "bg-[#F1F5F9] text-[#94A3B8]", dot: null },
  not_joined: { label: "Before joining", cell: "bg-[#F1F5F9] text-[#CBD5E1]", dot: null },
  no_shift: { label: "No shift", cell: "bg-[#F1F5F9] text-[#64748B]", dot: null },
};

const LEGEND = ["present", "absent", "leave", "half_day", "weekly_off", "holiday", "late", "punch_error"];
const WEEK = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export const Legend = () => (
  <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm text-muted-foreground" data-testid="calendar-legend">
    <span className="inline-flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full border-2 border-[#1D4ED8]"/>Today</span>
    {LEGEND.map(k => (
      <span key={k} className="inline-flex items-center gap-1.5">
        {STATUS[k].dot ? <span className={`w-2.5 h-2.5 rounded-full ${STATUS[k].dot}`}/> : <Warning size={13} weight="fill" className="text-[#EAB308]"/>}
        {STATUS[k].label}
      </span>
    ))}
  </div>
);

export const CalendarGrid = ({ days, today, selected, onSelect }) => {
  if (!days.length) return null;
  const lead = (new Date(`${days[0].date}T00:00:00`).getDay() + 6) % 7;
  return (
    <div data-testid="calendar-grid">
      <div className="grid grid-cols-7 gap-1.5 sm:gap-2.5 mb-2">
        {WEEK.map(w => <div key={w} className="text-center text-xs sm:text-sm text-muted-foreground py-1">{w}</div>)}
      </div>
      <div className="grid grid-cols-7 gap-1.5 sm:gap-2.5">
        {Array.from({ length: lead }).map((_, i) => <div key={`pad${i}`}/>)}
        {days.map(d => {
          const st = STATUS[d.status] || STATUS.future;
          const isToday = d.date === today;
          const photos = dayHasSelfies(d);
          return (
            <button key={d.date} onClick={() => onSelect(d.date)} data-testid={`cal-day-${d.date}`} data-status={d.status}
              data-timing={d.timing ? (d.timing.off || !d.timing.working ? "off" : `${d.timing.start}-${d.timing.end}`) : ""}
              title={d.timing ? (d.timing.off || !d.timing.working ? "Scheduled day off" : `Timing ${d.timing.start}–${d.timing.end}`) : undefined}
              className={`relative aspect-square sm:aspect-[5/4] rounded-md grid place-items-center text-base sm:text-lg font-semibold transition-transform hover:scale-[1.04] ${st.cell}
                ${isToday ? "ring-2 ring-[#1D4ED8]" : ""} ${selected === d.date ? "outline outline-2 outline-offset-2 outline-foreground" : ""}`}>
              {Number(d.date.slice(8))}
              {photos && <Camera size={12} weight="fill" className="absolute bottom-1 left-1 opacity-80" data-testid={`cal-photo-${d.date}`} aria-hidden="true"/>}
              {d.status === "punch_error" && <Warning size={11} weight="fill" className="absolute top-1 right-1 text-[#EAB308]"/>}
              {d.regularization?.status === "pending" && <span className="absolute bottom-1 right-1 w-1.5 h-1.5 rounded-full bg-[#1D4ED8]" title="Correction pending"/>}
            </button>
          );
        })}
      </div>
    </div>
  );
};
