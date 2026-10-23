import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import WishDialog from "@/components/WishDialog";
import { api } from "@/lib/api";
import AuthPhoto from "@/components/AuthPhoto";
import { Cake, Heart, Briefcase, Confetti, HandHeart, CheckCircle, ChatsCircle } from "@phosphor-icons/react";

const KIND = {
  birthday: { label: "Birthday", icon: Cake, color: "#FF3B30" },
  wedding_anniversary: { label: "Wedding anniversary", icon: Heart, color: "#E91E63" },
  work_anniversary: { label: "Work anniversary", icon: Briefcase, color: "#0047FF" },
};

const when = (c) => {
  if (c.days_away === 0) return "Today";
  if (c.days_away === 1) return "Tomorrow";
  return new Date(c.date + "T00:00:00").toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
};

const caption = (c) => {
  const k = KIND[c.kind].label;
  if (c.kind === "birthday") return k;
  return `${c.years} year${c.years === 1 ? "" : "s"} · ${k.toLowerCase()}`;
};

export default function CelebrationsCard() {
  const [items, setItems] = useState(null);
  const [wishing, setWishing] = useState(null);
  useEffect(() => {
    api.get("/celebrations").then(r => setItems(r.data.celebrations || [])).catch(() => setItems([]));
  }, []);
  if (!items || items.length === 0) return null;

  const today = items.filter(c => c.days_away === 0);
  const later = items.filter(c => c.days_away > 0);
  const onWish = setWishing;
  const sent = (w) => {
    setItems(list => list.map(c => (c.user_id === wishing.user_id && c.kind === wishing.kind ? { ...c, my_wish_id: w.wish_id } : c)));
    setWishing(null);
  };

  return (
    <div className="mt-6 border border-border bg-card" data-testid="celebrations-card">
      <div className="p-4 border-b border-border flex items-center gap-2">
        <Confetti size={16} weight="bold" className="text-primary"/>
        <span className="label-overline">Celebrations</span>
        <span className="font-mono text-xs text-muted-foreground">this week</span>
      </div>
      {today.length > 0 && (
        <div className="p-4 grid sm:grid-cols-2 gap-3 border-b border-border bg-[#0047FF]/5" data-testid="celebrations-today">
          {today.map(c => <Person key={`${c.user_id}-${c.kind}`} c={c} big onWish={onWish}/>)}
        </div>
      )}
      {later.length > 0 && (
        <div className="divide-y divide-border" data-testid="celebrations-upcoming">
          {later.map(c => <Person key={`${c.user_id}-${c.kind}`} c={c} onWish={onWish}/>)}
        </div>
      )}
      {wishing && <WishDialog c={wishing} onClose={() => setWishing(null)} onSent={sent}/>}
    </div>
  );
}

function WishAction({ c, onWish }) {
  const cls = "text-[10px] label-overline inline-flex items-center gap-1 shrink-0";
  if (c.is_me) {
    if (!c.wish_count) return null;
    return <Link to="/wishes" className={`${cls} text-primary hover:underline`} data-testid={`celebration-wishes-${c.kind}`}><ChatsCircle size={12} weight="bold"/> {c.wish_count} WISH{c.wish_count > 1 ? "ES" : ""}</Link>;
  }
  if (c.my_wish_id) {
    return <Link to={`/wishes?open=${c.my_wish_id}`} className={`${cls} text-[#00A86B]`} data-testid={`celebration-wished-${c.user_id}-${c.kind}`}><CheckCircle size={12} weight="fill"/> WISHED</Link>;
  }
  if (c.days_away > 0) return null;
  return (
    <button onClick={() => onWish(c)} className={`${cls} border border-border px-2 py-1 hover:border-primary hover:text-primary`} data-testid={`celebration-wish-${c.user_id}-${c.kind}`}>
      <HandHeart size={12} weight="bold"/> WISH
    </button>
  );
}

function Person({ c, big, onWish }) {
  const { icon: Icon, color } = KIND[c.kind];
  const size = big ? "w-12 h-12" : "w-9 h-9";
  return (
    <div className={`flex items-center gap-3 min-w-0 ${big ? "pr-1" : "px-4 py-3"}`} data-testid={`celebration-${c.user_id}-${c.kind}`}>
      <div className="relative shrink-0">
        <AuthPhoto path={c.avatar_path} className={`${size} rounded-full object-cover border border-border`}
          fallback={<div className={`${size} rounded-full bg-secondary grid place-items-center text-sm font-medium`}>{c.name?.[0]}</div>}/>
        <span className="absolute -bottom-1 -right-1 w-5 h-5 rounded-full grid place-items-center text-white" style={{ background: color }}>
          <Icon size={11} weight="fill"/>
        </span>
      </div>
      <div className="min-w-0 flex-1">
        <div className={`${big ? "text-base" : "text-sm"} font-medium truncate`}>
          {c.is_me && c.days_away === 0 ? (c.kind === "birthday" ? "Happy birthday, you!" : `Happy anniversary, ${c.name?.split(" ")[0]}!`) : c.is_me ? "You" : c.name}
        </div>
        <div className="text-xs text-muted-foreground truncate">{caption(c)}{c.site ? ` · ${c.site}` : ""}</div>
      </div>
      <div className="flex flex-col items-end gap-1 shrink-0">
        <div className={`text-[10px] font-mono uppercase tracking-wider ${c.days_away === 0 ? "text-primary font-semibold" : "text-muted-foreground"}`}>{when(c)}</div>
        <WishAction c={c} onWish={onWish}/>
      </div>
    </div>
  );
}
