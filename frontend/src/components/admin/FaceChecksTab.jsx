import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import AuthPhoto from "@/components/AuthPhoto";
import { fmtTime } from "@/lib/format";
import { ScanSmiley, CaretLeft, CaretRight, Warning, CheckCircle, XCircle, Lightbulb } from "@phosphor-icons/react";

const matchLabel = (d) => (d == null ? null : d <= 0.4 ? ["Strong match", "good"] : d <= 0.45 ? ["Good match", "good"] : ["Borderline", "warn"]);

const Shot = ({ path, label, purged }) => (
  <div className="flex-1 min-w-0">
    <div className="label-overline mb-1">{label}</div>
    {path ? <AuthPhoto path={path} className="w-full aspect-[4/3] object-cover bg-black" fallback={<div className="w-full aspect-[4/3] bg-secondary"/>}/>
      : <div className="w-full aspect-[4/3] bg-secondary grid place-items-center text-[11px] text-muted-foreground text-center px-2">{purged ? "Deleted after 7 days" : "No photo"}</div>}
  </div>
);

const Verdict = ({ item, kind, onReview }) => {
  const pre = `check_${kind}`;
  if (!item[`${pre}_photo_path`] && item[`${pre}_face_distance`] == null) return null;
  const m = matchLabel(item[`${pre}_face_distance`]);
  const flagged = item[`${pre}_face_review`];
  const status = item[`${pre}_face_review_status`];
  return (
    <div className="text-xs flex items-center gap-2 flex-wrap" data-testid={`face-verdict-${item.record_id}-${kind}`}>
      <span className="font-mono">{kind === "in" ? "IN" : "OUT"} {fmtTime(item[pre])}</span>
      {m && <span title={`distance ${item[`${pre}_face_distance`]} (lower is better)`} className={`px-1.5 py-0.5 ${m[1] === "good" ? "bg-[#00E676]/15 text-[#00A152]" : "bg-[#FFC107]/20 text-[#B07D00]"}`}>{m[0]}</span>}
      {item[`${pre}_liveness`] && <span className="text-muted-foreground">live: {item[`${pre}_liveness`]}</span>}
      {item[`${pre}_low_light`] && <span className="text-muted-foreground inline-flex items-center gap-0.5"><Lightbulb size={11}/> low light</span>}
      {flagged && !status && <span className="text-[#B07D00] inline-flex items-center gap-1"><Warning size={12} weight="fill"/> {item[`${pre}_face_review_reason`]}</span>}
      {status === "ok" && <span className="text-[#00A152] inline-flex items-center gap-1"><CheckCircle size={12} weight="fill"/> confirmed</span>}
      {status === "mismatch" && <span className="text-[#FF3B30] inline-flex items-center gap-1"><XCircle size={12} weight="fill"/> not the same person</span>}
      {flagged && !status && (
        <span className="inline-flex gap-1 ml-auto">
          <button onClick={() => onReview(item, kind, "ok")} data-testid={`face-ok-${item.record_id}-${kind}`}
            className="px-2 py-1 border border-border hover:border-[#00A152] hover:text-[#00A152] transition-colors">Looks right</button>
          <button onClick={() => onReview(item, kind, "mismatch")} data-testid={`face-mismatch-${item.record_id}-${kind}`}
            className="px-2 py-1 border border-border hover:border-[#FF3B30] hover:text-[#FF3B30] transition-colors">Not them</button>
        </span>
      )}
    </div>
  );
};

export default function FaceChecksTab() {
  const [data, setData] = useState({ items: [], total: 0, page: 1, page_size: 24, pending_review: 0, keep_days: 7 });
  const [employees, setEmployees] = useState([]);
  const [f, setF] = useState({ flagged: false, person: "", from: "", to: "", page: 1 });

  const load = async (q = f) => {
    const params = new URLSearchParams({ page: q.page, ...(q.flagged ? { flagged: "true" } : {}),
      ...(q.person ? { person: q.person } : {}), ...(q.from ? { from: q.from } : {}), ...(q.to ? { to: q.to } : {}) });
    try { setData((await api.get(`/admin/face-checks?${params}`)).data); }
    catch { toast.error("Failed to load face checks"); }
  };
  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [f]);
  useEffect(() => { api.get("/admin/employees").then(r => setEmployees(r.data.employees || [])).catch(() => {}); }, []);

  const set = (patch) => setF({ ...f, page: 1, ...patch });
  const review = async (item, kind, decision) => {
    const note = decision === "mismatch" ? window.prompt(`Note for ${item.name}'s check-${kind} (optional)`) : null;
    if (note === null && decision === "mismatch") return;
    try {
      await api.post(`/admin/face-checks/${item.record_id}`, { kind, decision, note });
      toast.success(decision === "ok" ? "Marked as correct" : "Marked as not the same person");
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not save"); }
  };
  const pages = Math.max(1, Math.ceil(data.total / data.page_size));

  return (
    <div className="border border-border bg-card" data-testid="face-checks-tab">
      <div className="p-4 border-b border-border flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <ScanSmiley size={16} weight="bold" className="text-primary"/>
          <span className="label-overline">Face Checks</span>
          {data.pending_review > 0 && <span className="text-xs bg-[#FFC107]/20 text-[#B07D00] px-2 py-0.5 font-medium" data-testid="face-pending-count">{data.pending_review} to review</span>}
        </div>
        <div className="flex items-center gap-2 flex-wrap text-sm">
          <label className="inline-flex items-center gap-1.5 cursor-pointer">
            <input type="checkbox" checked={f.flagged} onChange={e => set({ flagged: e.target.checked })} data-testid="face-flagged-only"/> Needs review only
          </label>
          <select value={f.person} onChange={e => set({ person: e.target.value })} data-testid="face-person-filter"
            className="bg-background border border-border px-2 py-1.5">
            <option value="">Everyone</option>
            {employees.map(e => <option key={e.user_id} value={e.user_id}>{e.name || e.email}</option>)}
          </select>
          <input type="date" value={f.from} onChange={e => set({ from: e.target.value })} data-testid="face-from" className="bg-background border border-border px-2 py-1.5 font-mono"/>
          <input type="date" value={f.to} onChange={e => set({ to: e.target.value })} data-testid="face-to" className="bg-background border border-border px-2 py-1.5 font-mono"/>
        </div>
      </div>
      <div className="p-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3" data-testid="face-check-list">
        {data.items.map(item => (
          <div key={item.record_id} className={`border p-3 space-y-3 ${(item.check_in_face_review && !item.check_in_face_review_status) || (item.check_out_face_review && !item.check_out_face_review_status) ? "border-[#FFC107]" : "border-border"}`} data-testid={`face-card-${item.record_id}`}>
            <div className="flex items-baseline justify-between gap-2">
              <div className="font-medium truncate">{item.name}</div>
              <div className="font-mono text-xs text-muted-foreground">{item.date}</div>
            </div>
            <div className="flex gap-2">
              <Shot path={item.enrollment_photo_path} label="Enrolled"/>
              <Shot path={item.check_in_photo_path} label="Check-in" purged={item.photos_purged_at}/>
              <Shot path={item.check_out_photo_path} label="Check-out" purged={item.photos_purged_at}/>
            </div>
            <Verdict item={item} kind="in" onReview={review}/>
            <Verdict item={item} kind="out" onReview={review}/>
          </div>
        ))}
        {data.items.length === 0 && <div className="col-span-full p-8 text-center text-sm text-muted-foreground">{f.flagged ? "Nothing needs review." : "No face checks in this range."}</div>}
      </div>
      <div className="p-3 border-t border-border flex items-center justify-between text-xs text-muted-foreground">
        <span>Check-in and check-out selfies are deleted after {data.keep_days} days. Enrolment photos stay until the face is reset.</span>
        <span className="inline-flex items-center gap-2">
          <button disabled={f.page <= 1} onClick={() => setF({ ...f, page: f.page - 1 })} data-testid="face-prev" className="p-1 disabled:opacity-30"><CaretLeft size={14}/></button>
          <span className="font-mono" data-testid="face-page">{f.page} / {pages}</span>
          <button disabled={f.page >= pages} onClick={() => setF({ ...f, page: f.page + 1 })} data-testid="face-next" className="p-1 disabled:opacity-30"><CaretRight size={14}/></button>
        </span>
      </div>
    </div>
  );
}
