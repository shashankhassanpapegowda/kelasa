import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { Megaphone, Trash, PushPin } from "@phosphor-icons/react";

export default function NoticesTab() {
  const [items, setItems] = useState([]);
  const [f, setF] = useState({ title: "", body: "", pinned: false });

  const load = async () => {
    try { setItems((await api.get("/announcements")).data.announcements || []); }
    catch { toast.error("Failed to load notices"); }
  };
  useEffect(() => { load(); }, []);

  const post = async () => {
    if (!f.title.trim()) return toast.error("Add a title");
    try {
      await api.post("/admin/announcements", f);
      toast.success("Notice posted to the whole team");
      setF({ title: "", body: "", pinned: false });
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not post"); }
  };

  const remove = async (a) => {
    if (!window.confirm(`Remove "${a.title}"?`)) return;
    try { await api.delete(`/admin/announcements/${a.announcement_id}`); toast.success("Removed"); load(); }
    catch (e) { toast.error(e?.response?.data?.detail || "Could not remove"); }
  };

  return (
    <div className="grid lg:grid-cols-2 gap-6 items-start" data-testid="notices-tab">
      <div className="border border-border bg-card">
        <div className="p-4 border-b border-border flex items-center gap-2">
          <Megaphone size={16} weight="bold" className="text-primary"/>
          <span className="label-overline">Post a Notice</span>
        </div>
        <div className="p-4 space-y-3">
          <input value={f.title} onChange={e => setF({ ...f, title: e.target.value })} placeholder="Title" data-testid="notice-title"
            className="w-full bg-background border border-border px-3 py-2 text-sm"/>
          <textarea value={f.body} onChange={e => setF({ ...f, body: e.target.value })} rows={5} placeholder="What should the team know?" data-testid="notice-body"
            className="w-full bg-background border border-border px-3 py-2 text-sm"/>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={f.pinned} onChange={e => setF({ ...f, pinned: e.target.checked })} data-testid="notice-pinned"/>
            Pin to the top of everyone's dashboard
          </label>
          <button onClick={post} data-testid="post-notice-btn"
            className="w-full bg-foreground text-background px-4 py-3 hover:bg-primary transition-colors font-medium">Publish</button>
        </div>
      </div>

      <div className="border border-border bg-card">
        <div className="p-4 border-b border-border flex items-center justify-between">
          <span className="label-overline">Published</span>
          <span className="font-mono text-xs text-muted-foreground">{items.length}</span>
        </div>
        <div className="divide-y divide-border max-h-[520px] overflow-y-auto" data-testid="notice-list">
          {items.map(a => (
            <div key={a.announcement_id} className="p-4" data-testid={`notice-${a.announcement_id}`}>
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2">
                  {a.pinned && <PushPin size={13} weight="fill" className="text-primary"/>}
                  <span className="text-sm font-medium">{a.title}</span>
                </div>
                <button onClick={() => remove(a)} className="text-muted-foreground hover:text-[#FF3B30]" data-testid={`delete-notice-${a.announcement_id}`}>
                  <Trash size={14} weight="bold"/>
                </button>
              </div>
              {a.body && <p className="text-sm text-muted-foreground mt-1 whitespace-pre-wrap">{a.body}</p>}
              <div className="text-[10px] font-mono text-muted-foreground mt-2">
                {a.author_name} · {new Date(a.created_at).toLocaleString()}
              </div>
            </div>
          ))}
          {items.length === 0 && <div className="p-8 text-sm text-muted-foreground text-center">No notices yet.</div>}
        </div>
      </div>
    </div>
  );
}
