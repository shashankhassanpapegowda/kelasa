import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { useAuth } from "@/lib/auth";
import AppHeader from "@/components/AppHeader";
import { Cake, Heart, Briefcase, PaperPlaneRight, ChatsCircle } from "@phosphor-icons/react";

const KIND = {
  birthday: { label: "Birthday", icon: Cake, color: "#FF3B30" },
  wedding_anniversary: { label: "Wedding anniversary", icon: Heart, color: "#E91E63" },
  work_anniversary: { label: "Work anniversary", icon: Briefcase, color: "#0047FF" },
};
const fmtWhen = (iso) => new Date(iso).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

export default function WishesPage() {
  const { user } = useAuth();
  const [items, setItems] = useState(null);
  const [openId, setOpenId] = useState(() => new URLSearchParams(window.location.search).get("open"));

  const load = () => api.get("/wishes").then(r => setItems(r.data.wishes || [])).catch(() => setItems([]));
  useEffect(() => { load(); }, []);

  const open = items?.find(w => w.wish_id === openId) || null;
  useEffect(() => {
    if (open?.unread) {
      api.post(`/wishes/${open.wish_id}/read`).then(() => {
        setItems(list => list.map(w => w.wish_id === open.wish_id ? { ...w, unread: false } : w));
        window.dispatchEvent(new Event("kelasa-wishes-read"));
      }).catch(() => {});
    }
  }, [open]);

  return (
    <div className="min-h-screen bg-background">
      <AppHeader/>
      <main className="max-w-[1100px] mx-auto px-4 sm:px-6 lg:px-8 py-8" data-testid="wishes-page">
        <div className="label-overline">Private</div>
        <h1 className="text-3xl sm:text-4xl font-semibold tracking-tight mt-1">Wishes</h1>
        {!items ? <div className="mt-8 text-sm text-muted-foreground">Loading…</div> : items.length === 0 ? (
          <div className="mt-8 border border-border bg-card p-8 text-center text-sm text-muted-foreground" data-testid="wishes-empty">
            No wishes yet. When a teammate celebrates, tap <strong>Wish</strong> on the home screen.
          </div>
        ) : (
          <div className="mt-8 grid md:grid-cols-[320px_1fr] gap-6 items-start">
            <div className="border border-border bg-card divide-y divide-border" data-testid="wishes-list">
              {items.map(w => <ThreadRow key={w.wish_id} w={w} active={w.wish_id === openId} onClick={() => setOpenId(w.wish_id)}/>)}
            </div>
            {open ? <Thread key={open.wish_id} w={open} me={user?.user_id} onReplied={load}/> : (
              <div className="border border-border bg-card p-8 text-sm text-muted-foreground hidden md:block">Pick a conversation.</div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}

function ThreadRow({ w, active, onClick }) {
  const { icon: Icon, color } = KIND[w.kind];
  const other = w.direction === "received" ? w.from_name : w.to_name;
  const last = w.messages[w.messages.length - 1];
  return (
    <button onClick={onClick} data-testid={`wish-thread-${w.wish_id}`}
      className={`w-full text-left p-3 flex items-start gap-3 transition-colors ${active ? "bg-secondary" : "hover:bg-secondary/50"}`}>
      <span className="w-8 h-8 rounded-full grid place-items-center text-white shrink-0" style={{ background: color }}><Icon size={14} weight="fill"/></span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span className="text-sm font-medium truncate">{other}</span>
          {w.unread && <span className="w-2 h-2 rounded-full bg-primary shrink-0" data-testid={`wish-unread-${w.wish_id}`}/>}
        </span>
        <span className="block text-[11px] text-muted-foreground">{w.direction === "received" ? `Wished you · ${KIND[w.kind].label}` : `You wished · ${KIND[w.kind].label}`}</span>
        <span className="block text-xs text-muted-foreground truncate mt-0.5">{last.message}</span>
      </span>
    </button>
  );
}

function Thread({ w, me, onReplied }) {
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "nearest" }); }, [w.messages.length]);

  const reply = async () => {
    if (!msg.trim()) return;
    setBusy(true);
    try { await api.post(`/wishes/${w.wish_id}/reply`, { message: msg }); setMsg(""); onReplied(); }
    catch (e) { toast.error(e?.response?.data?.detail || "Could not send"); }
    finally { setBusy(false); }
  };
  const title = w.direction === "received" ? `${w.from_name} → you` : `You → ${w.to_name}`;
  return (
    <div className="border border-border bg-card flex flex-col" data-testid="wish-conversation">
      <div className="p-4 border-b border-border flex items-center gap-2">
        <ChatsCircle size={16} weight="bold" className="text-primary"/>
        <span className="text-sm font-medium">{title}</span>
        <span className="text-[10px] font-mono text-muted-foreground">{KIND[w.kind].label}{w.years ? ` · ${w.years} yrs` : ""} · {w.occasion_date}</span>
      </div>
      <div className="p-4 space-y-3 max-h-[420px] overflow-y-auto">
        {w.messages.map((m, i) => {
          const mine = m.from_user_id === me;
          return (
            <div key={i} className={`flex ${mine ? "justify-end" : "justify-start"}`} data-testid="wish-message-bubble">
              <div className={`max-w-[80%] px-3 py-2 text-sm ${mine ? "bg-foreground text-background" : "bg-secondary"}`}>
                <div className="whitespace-pre-wrap break-words">{m.message}</div>
                <div className={`text-[10px] mt-1 font-mono ${mine ? "opacity-60" : "text-muted-foreground"}`}>{mine ? "You" : m.from_name} · {fmtWhen(m.created_at)}</div>
              </div>
            </div>
          );
        })}
        <div ref={end}/>
      </div>
      <div className="p-3 border-t border-border flex gap-2">
        <input value={msg} onChange={e => setMsg(e.target.value)} onKeyDown={e => e.key === "Enter" && reply()} maxLength={500}
          placeholder={w.direction === "received" ? "Say thanks…" : "Write a reply…"} className="flex-1 bg-background border border-border px-3 py-2 text-sm" data-testid="wish-reply-input"/>
        <button onClick={reply} disabled={busy || !msg.trim()} data-testid="wish-reply-btn"
          className="bg-foreground text-background px-3 py-2 hover:bg-primary transition-colors disabled:opacity-40"><PaperPlaneRight size={16} weight="bold"/></button>
      </div>
    </div>
  );
}
