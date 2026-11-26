import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import AuthPhoto from "@/components/AuthPhoto";
import { fmtTime } from "@/lib/format";
import { Camera, CaretLeft, CaretRight } from "@phosphor-icons/react";

const Shot = ({ path, label, time, purged }) => (
  <div className="flex-1 min-w-0">
    <div className="flex items-baseline justify-between mb-1">
      <span className="label-overline">{label}</span>
      {time && <span className="font-mono text-[11px] text-muted-foreground">{fmtTime(time)}</span>}
    </div>
    {path ? (
      <AuthPhoto path={path} className="w-full aspect-[4/3] object-cover bg-black" fallback={<div className="w-full aspect-[4/3] bg-secondary"/>}/>
    ) : (
      <div className="w-full aspect-[4/3] bg-secondary grid place-items-center text-[11px] text-muted-foreground text-center px-2">
        {purged ? "Deleted after 7 days" : time ? "No photo" : "Not checked out"}
      </div>
    )}
  </div>
);

export default function SelfiesTab() {
  const [data, setData] = useState({ items: [], total: 0, page: 1, page_size: 24, keep_days: 7 });
  const [employees, setEmployees] = useState([]);
  const [f, setF] = useState({ person: "", from: "", to: "", page: 1 });

  useEffect(() => {
    const params = new URLSearchParams({ page: f.page, ...(f.person ? { person: f.person } : {}),
      ...(f.from ? { from: f.from } : {}), ...(f.to ? { to: f.to } : {}) });
    api.get(`/admin/face-checks?${params}`).then(r => setData(r.data)).catch(() => toast.error("Failed to load selfies"));
  }, [f]);
  useEffect(() => { api.get("/admin/employees").then(r => setEmployees(r.data.employees || [])).catch(() => {}); }, []);

  const set = (patch) => setF({ ...f, page: 1, ...patch });
  const pages = Math.max(1, Math.ceil(data.total / data.page_size));

  return (
    <div className="border border-border bg-card" data-testid="selfies-tab">
      <div className="p-4 border-b border-border flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <Camera size={16} weight="bold" className="text-primary"/>
          <span className="label-overline">Selfies</span>
          <span className="font-mono text-xs text-muted-foreground" data-testid="selfies-total">{data.total}</span>
        </div>
        <div className="flex items-center gap-2 flex-wrap text-sm">
          <select value={f.person} onChange={e => set({ person: e.target.value })} data-testid="selfies-person-filter"
            className="bg-background border border-border px-2 py-1.5">
            <option value="">Everyone</option>
            {employees.map(e => <option key={e.user_id} value={e.user_id}>{e.name || e.email}</option>)}
          </select>
          <input type="date" value={f.from} onChange={e => set({ from: e.target.value })} data-testid="selfies-from" className="bg-background border border-border px-2 py-1.5 font-mono"/>
          <input type="date" value={f.to} onChange={e => set({ to: e.target.value })} data-testid="selfies-to" className="bg-background border border-border px-2 py-1.5 font-mono"/>
        </div>
      </div>
      <div className="p-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3" data-testid="selfies-list">
        {data.items.map(item => (
          <div key={item.record_id} className="border border-border p-3 space-y-3" data-testid={`selfie-card-${item.record_id}`}>
            <div className="flex items-baseline justify-between gap-2">
              <div className="font-medium truncate">{item.name}</div>
              <div className="font-mono text-xs text-muted-foreground">{item.date}</div>
            </div>
            <div className="flex gap-2">
              <Shot path={item.check_in_photo_path} label="In" time={item.check_in} purged={item.photos_purged_at}/>
              <Shot path={item.check_out_photo_path} label="Out" time={item.check_out} purged={item.photos_purged_at}/>
            </div>
          </div>
        ))}
        {data.items.length === 0 && <div className="col-span-full p-8 text-center text-sm text-muted-foreground">No selfies in this range.</div>}
      </div>
      <div className="p-3 border-t border-border flex items-center justify-between text-xs text-muted-foreground">
        <span>Check-in and check-out selfies are deleted after {data.keep_days} days.</span>
        <span className="inline-flex items-center gap-2">
          <button disabled={f.page <= 1} onClick={() => setF({ ...f, page: f.page - 1 })} data-testid="selfies-prev" className="p-1 disabled:opacity-30"><CaretLeft size={14}/></button>
          <span className="font-mono" data-testid="selfies-page">{f.page} / {pages}</span>
          <button disabled={f.page >= pages} onClick={() => setF({ ...f, page: f.page + 1 })} data-testid="selfies-next" className="p-1 disabled:opacity-30"><CaretRight size={14}/></button>
        </span>
      </div>
    </div>
  );
}
