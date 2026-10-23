import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import confetti from "canvas-confetti";
import { api } from "@/lib/api";
import AuthPhoto from "@/components/AuthPhoto";
import WishDialog from "@/components/WishDialog";
import { Cake, Heart, Briefcase, HandHeart, CheckCircle, ChatsCircle } from "@phosphor-icons/react";

const LABEL = { birthday: "Birthday", wedding_anniversary: "Wedding Anniversary", work_anniversary: "Work Anniversary" };
const ICON = { birthday: Cake, wedding_anniversary: Heart, work_anniversary: Briefcase };
const COLORS = ["#0047FF", "#FF3B30", "#FFD600", "#00E676", "#E91E63"];

const burst = (big) => {
  if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
  const base = { colors: COLORS, zIndex: 900, disableForReducedMotion: true };
  confetti({ ...base, particleCount: big ? 140 : 60, spread: big ? 100 : 70, origin: { y: 0.3 } });
  if (big) {
    setTimeout(() => confetti({ ...base, particleCount: 60, angle: 60, spread: 60, origin: { x: 0, y: 0.5 } }), 250);
    setTimeout(() => confetti({ ...base, particleCount: 60, angle: 120, spread: 60, origin: { x: 1, y: 0.5 } }), 400);
  }
};

const occasionText = (list) => list.map(c => (c.kind === "birthday" ? "Birthday" : `${c.years}-year ${LABEL[c.kind]}`)).join(" & ");

export default function CelebrationBanner() {
  const [items, setItems] = useState(null);
  const [wishing, setWishing] = useState(null);
  const fired = useRef(false);

  useEffect(() => {
    api.get("/celebrations?days=0").then(r => setItems(r.data.celebrations || [])).catch(() => setItems([]));
  }, []);

  const mine = (items || []).filter(c => c.is_me);
  const others = (items || []).filter(c => !c.is_me);

  useEffect(() => {
    if (!items || fired.current || (!mine.length && !others.length)) return;
    fired.current = true;
    const t = setTimeout(() => burst(mine.length > 0), 300);
    return () => clearTimeout(t);
  }, [items, mine.length, others.length]);

  if (!items || (!mine.length && !others.length)) return null;

  const sent = (w) => {
    setItems(list => list.map(c => (c.user_id === wishing.user_id && c.kind === wishing.kind ? { ...c, my_wish_id: w.wish_id } : c)));
    setWishing(null);
  };

  return (
    <div className="mt-6 space-y-3" data-testid="celebration-banner">
      {mine.length > 0 && <MyBanner list={mine}/>}
      {others.length > 0 && <TeamBanner list={others} onWish={setWishing}/>}
      {wishing && <WishDialog c={wishing} onClose={() => setWishing(null)} onSent={sent}/>}
    </div>
  );
}

function MyBanner({ list }) {
  const c = list[0];
  const first = c.name?.split(" ")[0];
  const wishes = list.reduce((s, x) => s + (x.wish_count || 0), 0);
  const Icon = ICON[c.kind];
  return (
    <div className="relative overflow-hidden border-2 border-foreground bg-foreground text-background p-6 sm:p-8 celebrate-in" data-testid="celebration-banner-mine">
      <div className="absolute inset-0 opacity-25 pointer-events-none celebrate-dots"/>
      <div className="relative flex flex-col sm:flex-row sm:items-center gap-5">
        <div className="relative w-20 h-20 shrink-0">
          <AuthPhoto path={c.avatar_path} className="w-20 h-20 rounded-full object-cover border-4 border-[#FFD600]"
            fallback={<div className="w-20 h-20 rounded-full bg-[#FFD600] text-black grid place-items-center text-3xl font-semibold">{first?.[0]}</div>}/>
          <span className="absolute -bottom-1 -right-1 w-8 h-8 rounded-full bg-[#FF3B30] grid place-items-center text-white celebrate-pop"><Icon size={16} weight="fill"/></span>
        </div>
        <div className="min-w-0 w-full sm:flex-1">
          <div className="text-[10px] uppercase tracking-[0.3em] text-[#FFD600]">It's your day</div>
          <div className="text-2xl sm:text-4xl font-semibold tracking-tight mt-1" data-testid="celebration-banner-title">Happy {occasionText(list)}, {first}!</div>
          <div className="text-sm opacity-70 mt-1">Everyone at work is celebrating with you today.</div>
        </div>
        <Link to="/wishes" className="self-start sm:self-auto shrink-0 bg-[#FFD600] text-black px-4 py-2.5 text-sm font-medium inline-flex items-center gap-2 hover:bg-white transition-colors" data-testid="celebration-banner-wishes">
          <ChatsCircle size={16} weight="bold"/> {wishes ? `${wishes} wish${wishes > 1 ? "es" : ""} for you` : "Your wishes"}
        </Link>
      </div>
    </div>
  );
}

function TeamBanner({ list, onWish }) {
  return (
    <div className="relative overflow-hidden border border-[#FFD600] bg-[#FFD600]/15 p-4 celebrate-in" data-testid="celebration-banner-team">
      <div className="text-[10px] uppercase tracking-[0.3em] font-semibold mb-3">Celebrating today</div>
      <div className="grid sm:grid-cols-2 gap-3">
        {list.map(c => {
          const Icon = ICON[c.kind];
          return (
            <div key={`${c.user_id}-${c.kind}`} className="flex items-center gap-3 bg-card border border-border p-3 min-w-0" data-testid={`celebration-banner-${c.user_id}-${c.kind}`}>
              <div className="relative shrink-0">
                <AuthPhoto path={c.avatar_path} className="w-11 h-11 rounded-full object-cover border-2 border-[#FFD600]"
                  fallback={<div className="w-11 h-11 rounded-full bg-[#FFD600] text-black grid place-items-center font-semibold">{c.name?.[0]}</div>}/>
                <span className="absolute -bottom-1 -right-1 w-5 h-5 rounded-full bg-[#FF3B30] grid place-items-center text-white"><Icon size={11} weight="fill"/></span>
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium truncate">{c.name}</div>
                <div className="text-xs text-muted-foreground truncate">{c.kind === "birthday" ? "Birthday" : `${c.years} yrs · ${LABEL[c.kind].toLowerCase()}`}</div>
              </div>
              {c.my_wish_id ? (
                <Link to={`/wishes?open=${c.my_wish_id}`} className="text-[10px] label-overline text-[#00A86B] inline-flex items-center gap-1 shrink-0" data-testid={`banner-wished-${c.user_id}-${c.kind}`}>
                  <CheckCircle size={12} weight="fill"/> WISHED
                </Link>
              ) : (
                <button onClick={() => onWish(c)} className="shrink-0 bg-foreground text-background px-3 py-1.5 text-xs inline-flex items-center gap-1 hover:bg-primary transition-colors" data-testid={`banner-wish-${c.user_id}-${c.kind}`}>
                  <HandHeart size={13} weight="bold"/> Wish
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
