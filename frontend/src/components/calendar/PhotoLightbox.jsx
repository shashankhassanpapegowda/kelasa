import { useEffect, useRef, useState } from "react";
import AuthPhoto from "@/components/AuthPhoto";
import { fmtTime } from "@/lib/format";
import { CaretLeft, CaretRight, X } from "@phosphor-icons/react";

/**
 * Full-screen viewer for one day's selfies.
 * Closes with the X, a tap on the backdrop, or Esc.
 * Arrows and a horizontal swipe move between photos.
 * Images come from AuthPhoto, which fetches /api/files with the session.
 */
export default function PhotoLightbox({ shots, index = 0, onClose }) {
  const [cursor, setCursor] = useState(index);
  const touch = useRef(null);
  const count = shots?.length || 0;
  const safe = Math.min(Math.max(cursor, 0), Math.max(count - 1, 0));
  const shot = shots[safe];

  useEffect(() => { setCursor(index); }, [index]);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight") setCursor((n) => Math.min(count - 1, n + 1));
      if (e.key === "ArrowLeft") setCursor((n) => Math.max(0, n - 1));
    };
    window.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [count, onClose]);

  if (!shot) return null;

  const go = (delta) => setCursor((n) => Math.min(count - 1, Math.max(0, n + delta)));

  const onTouchStart = (e) => {
    const t = e.changedTouches[0];
    touch.current = { x: t.clientX, y: t.clientY };
  };
  const onTouchEnd = (e) => {
    if (!touch.current) return;
    const t = e.changedTouches[0];
    const dx = t.clientX - touch.current.x;
    const dy = t.clientY - touch.current.y;
    touch.current = null;
    if (Math.abs(dx) < 48 || Math.abs(dx) < Math.abs(dy)) return;
    go(dx < 0 ? 1 : -1);
  };

  return (
    <div
      className="fixed inset-0 z-[1000] bg-black/80 flex items-center justify-center p-3 sm:p-6 pt-[max(0.75rem,env(safe-area-inset-top))] pb-[max(0.75rem,env(safe-area-inset-bottom))]"
      onClick={onClose}
      data-testid="day-photo-lightbox"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`${shot.label} selfie`}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        onTouchStart={onTouchStart}
        onTouchEnd={onTouchEnd}
        className="w-full max-w-lg max-h-[100dvh] bg-black text-white border border-white/15 flex flex-col outline-none"
      >
        <div className="flex items-start justify-between gap-3 px-4 py-3">
          <div className="min-w-0">
            <div className="text-base font-semibold" data-testid="day-photo-label">{shot.label}</div>
            <div className="font-mono text-sm text-white/80" data-testid="day-photo-time">{shot.time ? fmtTime(shot.time) : "—"}</div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 min-h-11 min-w-11 grid place-items-center"
            data-testid="day-photo-lightbox-close"
            aria-label="Close photos"
          >
            <X size={22} weight="bold"/>
          </button>
        </div>

        <div className="relative min-h-[240px] flex-1 grid place-items-center bg-black px-12">
          {shot.path ? (
            <AuthPhoto
              path={shot.path}
              alt={`${shot.label} selfie`}
              className="w-full max-h-[70dvh] object-contain"
              fallback={<div className="w-full aspect-[4/3] bg-white/10"/>}
            />
          ) : (
            <div className="w-full aspect-[4/3] max-h-[50dvh] grid place-items-center text-center text-sm text-white/80 px-6" data-testid="day-photo-missing">
              {shot.note}
            </div>
          )}
          <button
            type="button"
            onClick={() => go(-1)}
            disabled={safe === 0}
            className="absolute left-1 top-1/2 -translate-y-1/2 min-h-11 min-w-11 grid place-items-center disabled:opacity-30"
            data-testid="day-photo-prev"
            aria-label="Previous photo"
          >
            <CaretLeft size={26} weight="bold"/>
          </button>
          <button
            type="button"
            onClick={() => go(1)}
            disabled={safe >= count - 1}
            className="absolute right-1 top-1/2 -translate-y-1/2 min-h-11 min-w-11 grid place-items-center disabled:opacity-30"
            data-testid="day-photo-next"
            aria-label="Next photo"
          >
            <CaretRight size={26} weight="bold"/>
          </button>
        </div>

        <div className="px-4 py-3 space-y-1">
          <div className="text-sm text-white/90" data-testid="day-photo-place">{shot.place}</div>
          <div className="font-mono text-xs text-white/60" data-testid="day-photo-index">{safe + 1} / {count}</div>
        </div>
      </div>
    </div>
  );
}
