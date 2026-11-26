import { useEffect, useRef, useState } from "react";
import { X, Camera, ArrowCounterClockwise, Check } from "@phosphor-icons/react";

const toJpeg = (video, maxWidth = 640) => {
  const w = Math.min(video.videoWidth, maxWidth);
  const h = (video.videoHeight / video.videoWidth) * w;
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  const ctx = c.getContext("2d");
  ctx.translate(w, 0); ctx.scale(-1, 1);
  ctx.drawImage(video, 0, 0, w, h);
  return c.toDataURL("image/jpeg", 0.82);
};

/** Simple selfie capture: camera → snap → retake or confirm. onCapture({ image_b64 }) */
export default function SelfieCapture({ open, title, subtitle, cta = "Confirm", onClose, onCapture }) {
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const [ready, setReady] = useState(false);
  const [shot, setShot] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setShot(null); setError(null); setReady(false);
    navigator.mediaDevices.getUserMedia({ video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } }, audio: false })
      .then(async (stream) => {
        if (cancelled) { stream.getTracks().forEach(t => t.stop()); return; }
        streamRef.current = stream;
        if (videoRef.current) { videoRef.current.srcObject = stream; await videoRef.current.play().catch(() => {}); }
        setReady(true);
      })
      .catch((e) => setError(e?.name === "NotAllowedError"
        ? "Camera permission was blocked. Allow camera access for this site in Settings."
        : "Could not start the camera. Close other apps using it and try again."));
    return () => {
      cancelled = true;
      if (streamRef.current) streamRef.current.getTracks().forEach(t => t.stop());
      streamRef.current = null;
    };
  }, [open]);

  if (!open) return null;

  const snap = () => { if (videoRef.current?.videoWidth) setShot(toJpeg(videoRef.current)); };
  const confirm = async () => {
    setBusy(true); setError(null);
    try { await onCapture({ image_b64: shot }); }
    catch (e) { setError(e?.response?.data?.detail || e?.message || "Something went wrong"); }
    finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-[1000] bg-black/80 backdrop-blur-sm grid place-items-center p-4" data-testid="selfie-modal">
      <div className="bg-card border border-border w-full max-w-md">
        <div className="p-4 border-b border-border flex items-center justify-between">
          <div>
            <div className="label-overline">Selfie</div>
            <div className="font-semibold tracking-tight mt-0.5">{title}</div>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-secondary" data-testid="selfie-close-btn"><X size={18} weight="bold"/></button>
        </div>
        <div className="p-4">
          {subtitle && <p className="text-sm text-muted-foreground mb-3">{subtitle}</p>}
          <div className="relative bg-black aspect-[4/3] overflow-hidden">
            <video ref={videoRef} className={`w-full h-full object-cover ${shot ? "hidden" : ""}`} style={{ transform: "scaleX(-1)" }} playsInline muted/>
            {shot && <img src={shot} alt="Your selfie" className="w-full h-full object-cover" data-testid="selfie-preview"/>}
            {!ready && !error && <div className="absolute inset-0 grid place-items-center text-white/80 text-sm">Starting camera…</div>}
          </div>
          {error && <div className="mt-3 border border-[#FF3B30]/30 bg-[#FF3B30]/10 p-3 text-sm text-[#FF3B30]" data-testid="selfie-error">{error}</div>}
          <div className="mt-4 flex gap-2">
            {!shot ? (
              <button onClick={snap} disabled={!ready} data-testid="selfie-snap-btn"
                className="flex-1 bg-foreground text-background py-3 inline-flex items-center justify-center gap-2 hover:bg-primary transition-colors disabled:opacity-40">
                <Camera size={18} weight="bold"/> Take selfie
              </button>
            ) : (
              <>
                <button onClick={() => setShot(null)} disabled={busy} data-testid="selfie-retake-btn"
                  className="px-4 py-3 border border-border inline-flex items-center gap-2 hover:bg-secondary transition-colors">
                  <ArrowCounterClockwise size={16} weight="bold"/> Retake
                </button>
                <button onClick={confirm} disabled={busy} data-testid="selfie-confirm-btn"
                  className="flex-1 bg-primary text-white py-3 inline-flex items-center justify-center gap-2 hover:opacity-90 transition-opacity disabled:opacity-50">
                  <Check size={18} weight="bold"/> {busy ? "Saving…" : cta}
                </button>
              </>
            )}
          </div>
          <p className="mt-3 text-[11px] text-muted-foreground">Your selfie is kept for this calendar month and the previous one, then deleted.</p>
        </div>
      </div>
    </div>
  );
}
