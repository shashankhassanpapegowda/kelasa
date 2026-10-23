import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import AuthPhoto from "@/components/AuthPhoto";
import { Cake, Heart, Briefcase, Confetti } from "@phosphor-icons/react";

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
  useEffect(() => {
    api.get("/celebrations").then(r => setItems(r.data.celebrations || [])).catch(() => setItems([]));
  }, []);
  if (!items || items.length === 0) return null;

  const today = items.filter(c => c.days_away === 0);
  const later = items.filter(c => c.days_away > 0);

  return (
    <div className="mt-6 border border-border bg-card" data-testid="celebrations-card">
      <div className="p-4 border-b border-border flex items-center gap-2">
        <Confetti size={16} weight="bold" className="text-primary"/>
        <span className="label-overline">Celebrations</span>
        <span className="font-mono text-xs text-muted-foreground">this week</span>
      </div>
      {today.length > 0 && (
        <div className="p-4 grid sm:grid-cols-2 gap-3 border-b border-border bg-[#0047FF]/5" data-testid="celebrations-today">
          {today.map(c => <Person key={`${c.user_id}-${c.kind}`} c={c} big/>)}
        </div>
      )}
      {later.length > 0 && (
        <div className="divide-y divide-border" data-testid="celebrations-upcoming">
          {later.map(c => <Person key={`${c.user_id}-${c.kind}`} c={c}/>)}
        </div>
      )}
    </div>
  );
}

function Person({ c, big }) {
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
          {c.is_me ? (c.kind === "birthday" ? "Happy birthday, you!" : `Happy anniversary, ${c.name?.split(" ")[0]}!`) : c.name}
        </div>
        <div className="text-xs text-muted-foreground truncate">{caption(c)}{c.site ? ` · ${c.site}` : ""}</div>
      </div>
      <div className={`text-[10px] font-mono uppercase tracking-wider shrink-0 ${c.days_away === 0 ? "text-primary font-semibold" : "text-muted-foreground"}`}>{when(c)}</div>
    </div>
  );
}
