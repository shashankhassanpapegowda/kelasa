import { useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { fmtTime, fmtDuration } from "@/lib/format";
import { STATUS } from "./CalendarGrid";
import { dayHasSelfies, dayPhotoShots } from "./dayPhotos.mjs";
import { Camera, Coffee, SignIn, SignOut, Warning, PencilSimple, X } from "@phosphor-icons/react";

const hhmm = (iso) => (iso ? new Date(iso).toTimeString().slice(0, 5) : "");

const CorrectionForm = ({ day, onDone, onCancel }) => {
  const s = day.sessions[0];
  const [f, setF] = useState({ check_in: hhmm(s?.check_in) || "09:00", check_out: (s?.check_out && !s.auto_closed && hhmm(s.check_out)) || "18:00", reason: "" });
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try {
      await api.post("/regularizations", { date: day.date, ...f });
      toast.success("Correction sent to your manager");
      onDone();
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not send"); }
    finally { setBusy(false); }
  };
  const input = "w-full bg-background border border-border px-3 py-2 text-sm";
  return (
    <div className="border border-border p-4 space-y-3 bg-secondary/40" data-testid="correction-form">
      <div className="flex items-center justify-between">
        <span className="label-overline">Request correction</span>
        <button onClick={onCancel} className="p-1 hover:bg-secondary" data-testid="correction-form-cancel"><X size={14}/></button>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <label className="text-xs text-muted-foreground">Correct check-in
          <input type="time" value={f.check_in} onChange={e => setF({ ...f, check_in: e.target.value })} className={`${input} font-mono mt-1`} data-testid="correction-in"/>
        </label>
        <label className="text-xs text-muted-foreground">Correct check-out
          <input type="time" value={f.check_out} onChange={e => setF({ ...f, check_out: e.target.value })} className={`${input} font-mono mt-1`} data-testid="correction-out"/>
        </label>
      </div>
      <textarea rows={2} value={f.reason} onChange={e => setF({ ...f, reason: e.target.value })} placeholder="Reason — e.g. phone battery died, forgot to check out"
        className={input} data-testid="correction-reason"/>
      <button onClick={submit} disabled={busy} data-testid="correction-submit"
        className="w-full bg-foreground text-background py-2.5 text-sm hover:bg-primary transition-colors disabled:opacity-50">
        {busy ? "Sending…" : "Send to manager"}
      </button>
    </div>
  );
};

const Session = ({ s }) => (
  <div className="border border-border p-3 space-y-2" data-testid={`day-session-${s.record_id}`}>
    <div className="flex items-center justify-between text-sm">
      <span className="inline-flex items-center gap-1.5"><SignIn size={14} className="text-[#16A34A]"/> <span className="font-mono">{fmtTime(s.check_in)}</span></span>
      <span className="text-muted-foreground">→</span>
      <span className="inline-flex items-center gap-1.5"><SignOut size={14} className="text-[#DC2626]"/> <span className="font-mono">{s.check_out ? fmtTime(s.check_out) : "on duty"}</span></span>
      <span className="font-mono font-semibold">{fmtDuration(s.net_work_minutes || 0)}</span>
    </div>
    <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
      {s.check_in_branch && <span>at {s.check_in_branch}</span>}
      {(s.late_by_minutes || 0) > 0 && <span className="text-[#C2410C]">late by {s.late_by_minutes} min</span>}
      {(s.early_by_minutes || 0) > 0 && <span className="text-[#B45309]">left {s.early_by_minutes} min early</span>}
      {(s.total_break_minutes || 0) > 0 && <span className="inline-flex items-center gap-1"><Coffee size={12}/> {s.total_break_minutes} min break{s.over_break ? " (over limit)" : ""}</span>}
      {s.regularized && <span className="text-[#1D4ED8]">corrected by manager</span>}
      {s.auto_closed && !s.regularized && <span className="text-[#A16207] inline-flex items-center gap-1"><Warning size={12} weight="fill"/> missed check-out — closed automatically</span>}
    </div>
    {(s.breaks || []).length > 0 && (
      <div className="text-[11px] font-mono text-muted-foreground" data-testid={`day-breaks-${s.record_id}`}>
        {s.breaks.map((b, i) => <span key={b.break_id || i} className="mr-3">break {fmtTime(b.start)}–{b.end ? fmtTime(b.end) : "…"}</span>)}
      </div>
    )}
  </div>
);

export const DayDetail = ({ day, today, onChanged, onOpenPhotos }) => {
  const [form, setForm] = useState(false);
  if (!day) return null;
  const st = STATUS[day.status] || STATUS.future;
  const shots = dayPhotoShots(day);
  const showPhotos = dayHasSelfies(day);
  const canCorrect = day.date <= today && !["holiday", "weekly_off", "leave", "future", "not_joined"].includes(day.status) && day.regularization?.status !== "pending";
  const label = new Date(`${day.date}T00:00:00`).toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" });
  return (
    <div className="space-y-3" data-testid="day-detail">
      <div className="flex items-center justify-between gap-2">
        <div>
          <div className="font-semibold">{label}</div>
          <div className="text-xs text-muted-foreground">{day.holiday || (day.leave ? `${day.leave.leave_type || "Leave"}${day.leave.half_day ? " (half day)" : ""}` : "")}</div>
        </div>
        <span className={`text-xs px-2 py-1 rounded ${st.cell}`} data-testid="day-status">{st.label}</span>
      </div>
      {day.timing && (
        <div className="text-sm font-mono" data-testid="day-timing">
          {day.timing.off || !day.timing.working
            ? "Scheduled day off"
            : `Timing ${day.timing.start}–${day.timing.end}${day.timing.break_minutes != null ? ` · break ${day.timing.break_minutes}m` : ""}`}
        </div>
      )}
      {day.sessions.length ? day.sessions.map(s => <Session key={s.record_id} s={s}/>)
        : <div className="text-sm text-muted-foreground border border-dashed border-border p-4 text-center">No punches on this day.</div>}
      {showPhotos && (
        <div className="space-y-2" data-testid="day-photo-triggers">
          <button type="button" onClick={() => onOpenPhotos?.(0)} data-testid="day-photos-open"
            className="w-full min-h-11 border border-border py-2 text-sm inline-flex items-center justify-center gap-2 hover:bg-secondary">
            <Camera size={16} weight="bold"/> View selfies
          </button>
          <div className="flex gap-2 overflow-x-auto pb-1">
            {shots.map((s) => (
              <button key={s.id} type="button" onClick={() => onOpenPhotos?.(s.index)} data-testid={`day-photo-open-${s.index}`}
                className="shrink-0 min-h-11 px-3 border border-border text-xs inline-flex items-center gap-1.5 hover:bg-secondary">
                <Camera size={14} weight="bold"/> {s.label}
              </button>
            ))}
          </div>
        </div>
      )}
      {day.sessions.length > 0 && <div className="text-sm flex justify-between"><span className="text-muted-foreground">Total worked</span><span className="font-mono font-semibold" data-testid="day-total">{fmtDuration(day.net_work_minutes)}</span></div>}
      {day.regularization && (
        <div className="text-xs border border-border p-2" data-testid="day-correction-status">
          Correction {day.regularization.check_in}–{day.regularization.check_out}: <b className="capitalize">{day.regularization.status}</b>
          {day.regularization.manager_note && <span className="text-muted-foreground"> — “{day.regularization.manager_note}”</span>}
        </div>
      )}
      {form ? <CorrectionForm day={day} onCancel={() => setForm(false)} onDone={() => { setForm(false); onChanged(); }}/>
        : canCorrect && (
          <button onClick={() => setForm(true)} data-testid="request-correction-btn"
            className="w-full border border-border py-2.5 text-sm inline-flex items-center justify-center gap-2 hover:bg-secondary transition-colors">
            <PencilSimple size={14} weight="bold"/> Request correction
          </button>
        )}
    </div>
  );
};
