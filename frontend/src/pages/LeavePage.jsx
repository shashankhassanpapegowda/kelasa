import { useEffect, useState } from "react";
import AppHeader from "@/components/AppHeader";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { fmtDay, today } from "@/lib/format";
import PhoneAlertsCard from "@/components/admin/PhoneAlertsCard";
import { pushSupported, currentSubscription, enablePush } from "@/lib/push";
import { AirplaneTilt, CalendarBlank, Megaphone, PushPin, X } from "@phosphor-icons/react";

const STATUS_STYLE = {
  pending: "bg-yellow-400 text-black",
  approved: "bg-[#00E676] text-black",
  rejected: "bg-[#FF3B30] text-white",
  cancelled: "bg-secondary text-muted-foreground",
};

export default function LeavePage() {
  const [types, setTypes] = useState([]);
  const [balances, setBalances] = useState([]);
  const [requests, setRequests] = useState([]);
  const [holidays, setHolidays] = useState([]);
  const [notices, setNotices] = useState([]);
  const [f, setF] = useState({ type_id: "", start_date: today(), end_date: today(), half_day: false, reason: "" });
  const [busy, setBusy] = useState(false);
  const [pushKey, setPushKey] = useState(0);
  const [sandwich, setSandwich] = useState(false);
  const [preview, setPreview] = useState(null);

  const load = async () => {
    try {
      const [t, b, r, h, n] = await Promise.all([
        api.get("/leave/types"),
        api.get("/leave/balance"),
        api.get("/leave/me"),
        api.get("/holidays"),
        api.get("/announcements", { params: { limit: 100 } }),
      ]);
      const offered = (t.data.types || []).filter(x => x.code === "LV" || x.policy === "monthly_reset");
      setTypes(offered);
      setBalances(b.data.balances || []);
      setSandwich(!!b.data.leave_sandwich_lop);
      setRequests(r.data.requests || []);
      setHolidays((h.data.holidays || []).filter(x => x.date >= today()).slice(0, 6));
      setNotices(n.data.announcements || []);
      setF(prev => ({ ...prev, type_id: prev.type_id || (offered[0]?.type_id ?? "") }));
    } catch { toast.error("Failed to load leave data"); }
  };

  useEffect(() => { load(); }, []);

  useEffect(() => {
    if (!f.start_date || !f.end_date) return;
    let cancelled = false;
    api.get("/leave/preview", { params: { start_date: f.start_date, end_date: f.half_day ? f.start_date : f.end_date, half_day: f.half_day } })
      .then(r => { if (!cancelled) { setPreview(r.data); setSandwich(!!r.data.leave_sandwich_lop); } })
      .catch(() => { if (!cancelled) setPreview(null); });
    return () => { cancelled = true; };
  }, [f.start_date, f.end_date, f.half_day]);

  const apply = async () => {
    if (!f.type_id) return toast.error("Pick a leave type");
    setBusy(true);
    try {
      await api.post("/leave/request", { ...f, end_date: f.half_day ? f.start_date : f.end_date });
      toast.success("Leave request sent for approval");
      setF({ ...f, reason: "" });
      load();
      setTimeout(offerPush, 1800);
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not submit"); }
    finally { setBusy(false); }
  };

  const offerPush = async () => {
    if (!pushSupported() || Notification.permission === "denied" || await currentSubscription()) return;
    toast("Want to know the moment it's decided?", {
      description: "Get a phone notification when your leave is approved or rejected.",
      duration: 12000,
      action: {
        label: "Turn on",
        onClick: async () => {
          try { await enablePush(); toast.success("Notifications turned on"); setPushKey(k => k + 1); }
          catch (e) { toast.error(e?.response?.data?.detail || e?.message || "Could not turn on"); }
        },
      },
    });
  };

  const cancel = async (r) => {
    if (!window.confirm("Cancel this leave request?")) return;
    try { await api.post(`/leave/${r.leave_id}/cancel`); toast.success("Cancelled"); load(); }
    catch (e) { toast.error(e?.response?.data?.detail || "Could not cancel"); }
  };

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <AppHeader/>
      <main className="flex-1">
        <div className="px-4 sm:px-6 py-6">
          <div className="label-overline" data-testid="leave-overline">Time Off</div>
          <h1 className="text-3xl sm:text-4xl font-semibold tracking-tight mt-1">My Leave</h1>

          <div className="mt-6"><PhoneAlertsCard audience="employee" refreshKey={pushKey}/></div>

          <div className="mt-6 grid grid-cols-2 lg:grid-cols-4 gap-0 border border-border bg-card" data-testid="leave-balance-cards">
            {balances.map(b => (
              <div key={b.type_id} className="p-5 border-b lg:border-b-0 border-r last:border-r-0 border-border" data-testid={`balance-${b.code}`}>
                <div className="flex items-center justify-between gap-2">
                  <span className="label-overline">{b.name}</span>
                  <span className="w-2 h-2" style={{ background: b.color }}/>
                </div>
                <div className="stat-value mt-3">{b.available}</div>
                <div className="text-[10px] font-mono text-muted-foreground mt-1" data-testid="leave-balance-caption">
                  {b.available} available / {b.used} used this month{b.pending ? ` · ${b.pending} pending` : ""}
                </div>
              </div>
            ))}
            {balances.length === 0 && <div className="p-6 text-sm text-muted-foreground col-span-4">No leave types configured yet.</div>}
          </div>

          <div className="mt-6 grid lg:grid-cols-3 gap-6 items-start">
            <div className="border border-border bg-card">
              <div className="p-4 border-b border-border flex items-center gap-2">
                <AirplaneTilt size={16} weight="bold" className="text-primary"/>
                <span className="label-overline">Apply for Leave</span>
              </div>
              <div className="p-4 space-y-3">
                <div>
                  <label className="label-overline mb-1.5 block">Leave</label>
                  <div className="text-sm" data-testid="leave-type-select">{types[0]?.name || "Leave"} · one paid day this month. It does not carry forward.</div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="label-overline mb-1.5 block">From</label>
                    <input type="date" value={f.start_date} data-testid="leave-start"
                      onChange={e => setF({ ...f, start_date: e.target.value, end_date: e.target.value > f.end_date ? e.target.value : f.end_date })}
                      className="w-full bg-background border border-border px-3 py-2 text-sm font-mono"/>
                  </div>
                  <div>
                    <label className="label-overline mb-1.5 block">To</label>
                    <input type="date" value={f.half_day ? f.start_date : f.end_date} disabled={f.half_day} data-testid="leave-end"
                      onChange={e => setF({ ...f, end_date: e.target.value })}
                      className="w-full bg-background border border-border px-3 py-2 text-sm font-mono disabled:opacity-50"/>
                  </div>
                </div>
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={f.half_day} onChange={e => setF({ ...f, half_day: e.target.checked })} data-testid="leave-half-day"/>
                  Half day only
                </label>
                <p className="text-xs text-muted-foreground">One paid day each month. Further days are unpaid and are not blocked.</p>
                {sandwich && preview?.warning_dates?.length > 0 && (
                  <div className="text-sm border border-[#FF3B30]/40 bg-[#FF3B30]/10 px-3 py-2" data-testid="sandwich-lop-warning">
                    These dates will be loss of pay: {preview.warning_dates.map(d => fmtDay(d)).join(", ")}. They are not taken from your paid leave.
                  </div>
                )}
                <div>
                  <label className="label-overline mb-1.5 block">Reason</label>
                  <textarea value={f.reason} onChange={e => setF({ ...f, reason: e.target.value })} rows={3} data-testid="leave-reason"
                    placeholder="Short note for your manager" className="w-full bg-background border border-border px-3 py-2 text-sm"/>
                </div>
                <button onClick={apply} disabled={busy} data-testid="submit-leave-btn"
                  className="w-full bg-foreground text-background px-4 py-3 hover:bg-primary transition-colors font-medium disabled:opacity-50">
                  Send for Approval
                </button>
              </div>
            </div>

            <div className="lg:col-span-2 border border-border bg-card">
              <div className="p-4 border-b border-border flex items-center justify-between">
                <span className="label-overline">My Requests</span>
                <span className="font-mono text-xs text-muted-foreground">{requests.length}</span>
              </div>
              <div className="divide-y divide-border max-h-[420px] overflow-y-auto" data-testid="my-leave-list">
                {requests.map(r => (
                  <div key={r.leave_id} className="p-4 flex items-start gap-3" data-testid={`my-leave-${r.leave_id}`}>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-medium">{r.type_name}</span>
                        <span className={`text-[9px] font-mono uppercase tracking-wider px-1.5 py-0.5 ${STATUS_STYLE[r.status]}`}>{r.status}</span>
                      </div>
                      <div className="font-mono text-sm mt-1">
                        {fmtDay(r.start_date)} → {fmtDay(r.end_date)} <span className="text-muted-foreground">· {r.days}d{r.paid_days != null ? ` · ${r.paid_days} paid` : ""}{r.lop_days > 0 ? ` · ${r.lop_days} unpaid` : ""}</span>
                      </div>
                      {r.reason && <div className="text-xs text-muted-foreground italic mt-1">“{r.reason}”</div>}
                      {r.status === "cancelled" && r.cancelled_by_name && (
                        <div className="text-[10px] font-mono text-muted-foreground mt-1">
                          cancelled by {r.cancelled_by_name}
                        </div>
                      )}
                      {r.status !== "cancelled" && r.decided_by_name && (
                        <div className="text-[10px] font-mono text-muted-foreground mt-1">
                          {r.status} by {r.decided_by_name}{r.decision_note ? ` · ${r.decision_note}` : ""}
                        </div>
                      )}
                    </div>
                    {(r.status === "pending" || r.status === "approved") && (
                      <button onClick={() => cancel(r)} className="text-[10px] label-overline text-muted-foreground hover:text-[#FF3B30] inline-flex items-center gap-1" data-testid={`cancel-leave-${r.leave_id}`}>
                        <X size={11} weight="bold"/> CANCEL
                      </button>
                    )}
                  </div>
                ))}
                {requests.length === 0 && <div className="p-8 text-sm text-muted-foreground text-center">You haven't applied for leave yet.</div>}
              </div>
            </div>
          </div>

          <div className="mt-6 grid lg:grid-cols-2 gap-6 items-start">
            <div className="border border-border bg-card">
              <div className="p-4 border-b border-border flex items-center gap-2">
                <CalendarBlank size={16} weight="bold" className="text-primary"/>
                <span className="label-overline">Upcoming Holidays</span>
              </div>
              <div className="divide-y divide-border" data-testid="upcoming-holidays">
                {holidays.map(h => (
                  <div key={h.holiday_id} className="p-3 flex items-center gap-3">
                    <span className="font-mono text-xs text-muted-foreground w-28">{fmtDay(h.date)}</span>
                    <span className="text-sm">{h.name}</span>
                  </div>
                ))}
                {holidays.length === 0 && <div className="p-6 text-sm text-muted-foreground">No holidays coming up.</div>}
              </div>
            </div>

            <div className="border border-border bg-card">
              <div className="p-4 border-b border-border flex items-center gap-2">
                <Megaphone size={16} weight="bold" className="text-primary"/>
                <span className="label-overline">Notices</span>
              </div>
              <div className="divide-y divide-border max-h-[300px] overflow-y-auto" data-testid="employee-notices">
                {notices.map(a => (
                  <div key={a.announcement_id} className="p-4">
                    <div className="flex items-center gap-2">
                      {a.pinned && <PushPin size={13} weight="fill" className="text-primary"/>}
                      <span className="text-sm font-medium">{a.title}</span>
                    </div>
                    {a.body && <p className="text-sm text-muted-foreground mt-1 whitespace-pre-wrap">{a.body}</p>}
                    <div className="text-[10px] font-mono text-muted-foreground mt-2">{a.author_name} · {new Date(a.created_at).toLocaleDateString()}</div>
                  </div>
                ))}
                {notices.length === 0 && <div className="p-6 text-sm text-muted-foreground">Nothing posted yet.</div>}
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
