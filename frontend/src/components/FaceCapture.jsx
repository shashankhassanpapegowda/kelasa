import { useEffect, useRef, useState } from "react";
import { Camera, CheckCircle, X, ArrowsClockwise } from "@phosphor-icons/react";
import { loadFaceModels, detectFace, captureFrameAsJpeg } from "@/lib/face";

/**
 * FaceCapture modal — opens the camera, detects a single face, on confirm
 * returns { descriptor: number[128], image_b64: dataURL }
 *
 * Props:
 *  - open: bool
 *  - title: string
 *  - subtitle: string
 *  - onClose: () => void
 *  - onCapture: ({descriptor, image_b64}) => Promise<void>
 *  - cta: string (button label, default "Capture")
 */
export default function FaceCapture({ open, title, subtitle, onClose, onCapture, cta = "Capture" }) {
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const detectTimerRef = useRef(null);
  const [modelsReady, setModelsReady] = useState(false);
  const [faceDetected, setFaceDetected] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    (async () => {
      try {
        await loadFaceModels();
        if (cancelled) return;
        setModelsReady(true);
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } },
          audio: false,
        });
        if (cancelled) { stream.getTracks().forEach(t => t.stop()); return; }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play().catch(() => {});
        }
        detectTimerRef.current = setInterval(async () => {
          if (!videoRef.current || videoRef.current.readyState < 2) return;
          try {
            const r = await detectFace(videoRef.current);
            setFaceDetected(!!r);
          } catch {}
        }, 700);
      } catch (e) {
        setError(e?.message || "Could not access camera");
      }
    })();
    return () => {
      cancelled = true;
      if (detectTimerRef.current) clearInterval(detectTimerRef.current);
      if (streamRef.current) streamRef.current.getTracks().forEach(t => t.stop());
      streamRef.current = null;
      setFaceDetected(false);
      setCapturing(false);
      setSubmitting(false);
      setError(null);
    };
  }, [open]);

  if (!open) return null;

  const handleCapture = async () => {
    if (!videoRef.current) return;
    setCapturing(true);
    setError(null);
    try {
      const result = await detectFace(videoRef.current);
      if (!result || !result.descriptor) {
        throw new Error("No face detected. Please align your face in the frame.");
      }
      const image_b64 = captureFrameAsJpeg(videoRef.current);
      const descriptor = Array.from(result.descriptor);
      setSubmitting(true);
      await onCapture({ descriptor, image_b64 });
    } catch (e) {
      setError(e?.message || "Capture failed");
    } finally {
      setCapturing(false);
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm grid place-items-center p-4" data-testid="face-capture-modal">
      <div className="bg-card border border-border w-full max-w-md">
        <div className="p-4 border-b border-border flex items-center justify-between">
          <div>
            <div className="label-overline">Face Verification</div>
            <div className="font-semibold tracking-tight mt-0.5">{title}</div>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-secondary" data-testid="face-close-btn">
            <X size={18} weight="bold"/>
          </button>
        </div>

        <div className="p-4">
          {subtitle && <p className="text-sm text-muted-foreground mb-3">{subtitle}</p>}

          <div className="relative bg-black aspect-[4/3] overflow-hidden">
            <video ref={videoRef} className="w-full h-full object-cover" playsInline muted/>
            {/* Face guide ring */}
            <div className="absolute inset-0 grid place-items-center pointer-events-none">
              <div className={`w-48 h-60 border-2 ${faceDetected ? "border-[#00E676]" : "border-white/50"} rounded-[50%] transition-colors`}/>
            </div>
            {/* Status badge */}
            <div className="absolute top-3 left-3 flex items-center gap-2 bg-black/70 px-2.5 py-1">
              <span className={`w-1.5 h-1.5 rounded-full ${faceDetected ? "bg-[#00E676]" : "bg-yellow-400"} animate-pulse`}/>
              <span className="text-[10px] uppercase tracking-[0.15em] text-white font-medium">
                {!modelsReady ? "Loading…" : faceDetected ? "Face Detected" : "Align your face"}
              </span>
            </div>
          </div>

          {error && (
            <div className="mt-3 text-sm text-[#FF3B30] bg-[#FF3B30]/10 border border-[#FF3B30]/30 p-2.5" data-testid="face-error">
              {error}
            </div>
          )}

          <div className="mt-4 flex items-center gap-3">
            <button
              onClick={handleCapture}
              disabled={!modelsReady || !faceDetected || capturing || submitting}
              data-testid="face-capture-btn"
              className="flex-1 bg-foreground text-background px-4 py-3 inline-flex items-center justify-center gap-2 disabled:opacity-50 hover:bg-primary transition-colors"
            >
              {submitting ? <ArrowsClockwise size={16} weight="bold" className="animate-spin"/> : faceDetected ? <CheckCircle size={16} weight="bold"/> : <Camera size={16} weight="bold"/>}
              <span className="font-medium">{submitting ? "Verifying…" : cta}</span>
            </button>
          </div>
          {(capturing || submitting) && <div className="loading-bar mt-3"/>}
          <p className="mt-3 text-[10px] text-muted-foreground font-mono">
            Your face descriptor (128-dim) is matched against your enrolled template. The selfie + GPS coordinates are saved as proof.
          </p>
        </div>
      </div>
    </div>
  );
}
