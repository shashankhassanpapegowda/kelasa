import { useCallback, useEffect, useRef, useState } from "react";
import { X, ArrowsClockwise, Lightbulb, CheckCircle } from "@phosphor-icons/react";
import {
  loadFaceModels, trackFace, describeFace, captureFrameAsJpeg, frameLuminance,
  enhancedFrame, gainFor, headYaw, eyeOpenness,
} from "@/lib/face";

const TIMEOUT_MS = 25000;
const centred = (y) => y > 0.4 && y < 0.6;

const stepsFor = (mode, challenge) => mode === "enroll"
  ? [{ id: "center", say: "Look straight at the camera" },
     { id: "sideA", say: "Turn your head slightly to one side" },
     { id: "sideB", say: "Now turn slightly to the other side" }]
  : [{ id: "center", say: "Look straight at the camera" },
     challenge === "blink" ? { id: "blink", say: "Blink your eyes once" } : { id: "turn", say: "Slowly turn your head to one side" },
     { id: "center2", say: "Now look straight again" }];

const freshState = () => ({ step: 0, descs: [], photo: null, stable: 0, earMax: 0, closed: false, side: null, started: Date.now(), gain: 1, tick: 0, lowSeen: false });

const Tips = () => (
  <ul className="text-xs text-muted-foreground space-y-1 mt-2 list-disc pl-4" data-testid="face-tips">
    <li>Face a window or a light, not away from it.</li>
    <li>Take off a helmet, cap or mask. Glasses are fine — tilt slightly if they glare.</li>
    <li>Hold the phone at eye level, about an arm's length away.</li>
  </ul>
);

/**
 * Hands-free face check with a live (blink / head-turn) test.
 * mode "verify": onCapture({ descriptors, image_b64, liveness })
 * mode "enroll": onCapture({ descriptors[3], image_b64 })
 */
export default function FaceCapture({ open, title, subtitle, onClose, onCapture, mode = "verify" }) {
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const runRef = useRef(false);
  const st = useRef(freshState());
  const challengeRef = useRef("blink");
  const [challenge, setChallenge] = useState("blink");
  const steps = stepsFor(mode, challenge);
  const [ready, setReady] = useState(false);
  const [step, setStep] = useState(0);
  const [hint, setHint] = useState("Starting camera…");
  const [faceOn, setFaceOn] = useState(false);
  const [lowLight, setLowLight] = useState(false);
  const [stuck, setStuck] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const onCaptureRef = useRef(onCapture);
  onCaptureRef.current = onCapture;
  const advance = () => { st.current.step += 1; st.current.stable = 0; setStep(st.current.step); };

  const submit = useCallback(async () => {
    runRef.current = false;
    const s = st.current;
    setSubmitting(true); setError(null);
    try {
      await onCaptureRef.current({
        descriptors: s.descs, image_b64: s.photo,
        ...(mode === "verify" ? { liveness: { challenge: challengeRef.current, passed: true, duration_ms: Date.now() - s.started, low_light: s.lowSeen } } : {}),
      });
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || "Face check failed");
    } finally { setSubmitting(false); }
  }, [mode]);

  const tick = useCallback(async () => {
    if (!runRef.current) return;
    const v = videoRef.current, s = st.current;
    const again = () => runRef.current && setTimeout(tick, 90);
    if (!v || v.readyState < 2 || !v.videoWidth) return again();
    if (Date.now() - s.started > TIMEOUT_MS) { runRef.current = false; setStuck(true); return; }
    if (s.tick++ % 6 === 0) {
      s.gain = gainFor(frameLuminance(v));
      const low = s.gain > 1.05;
      s.lowSeen = s.lowSeen || low;
      setLowLight(low);
    }
    const src = enhancedFrame(v, s.gain);
    let det = null;
    try { det = await trackFace(src); } catch { /* skip frame */ }
    if (!det) {
      setFaceOn(false); s.stable = 0;
      setHint(s.gain > 1.05 ? "Too dark — turn towards a light" : "Centre your face in the ring");
      return again();
    }
    setFaceOn(true);
    const size = det.detection.box.width / (src.width || src.videoWidth);
    if (size < 0.2) { setHint("Move a little closer"); return again(); }
    if (size > 0.8) { setHint("Move the phone back a little"); return again(); }
    const yaw = headYaw(det.landmarks);
    const plan = stepsFor(mode, challengeRef.current);
    const id = plan[s.step]?.id;
    setHint("");
    const grab = async (photo) => {
      const d = await describeFace(src);
      if (!d) { s.stable = 0; return false; }
      s.descs.push(d);
      if (photo && !s.photo) s.photo = captureFrameAsJpeg(src);
      return true;
    };
    if (id === "center" || id === "center2") {
      if (!centred(yaw)) { s.stable = 0; setHint("Look straight at the camera"); }
      else if (++s.stable >= 3 && await grab(true)) advance();
    } else if (id === "blink") {
      const eo = eyeOpenness(det.landmarks);
      s.earMax = Math.max(s.earMax * 0.995, eo);
      if (!s.closed && s.earMax > 0.18 && eo < s.earMax * 0.72) s.closed = true;
      else if (s.closed && eo > s.earMax * 0.88) advance();
    } else if (id === "turn") {
      if (yaw < 0.36 || yaw > 0.64) advance();
    } else if (id === "sideA") {
      if (yaw < 0.4 || yaw > 0.6) {
        if (++s.stable >= 2 && await grab(false)) { s.side = yaw < 0.5 ? "l" : "r"; advance(); }
      } else s.stable = 0;
    } else if (id === "sideB") {
      const ok = s.side === "l" ? yaw > 0.6 : yaw < 0.4;
      if (ok) { if (++s.stable >= 2 && await grab(false)) advance(); } else s.stable = 0;
    }
    if (st.current.step >= plan.length) return submit();
    again();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [submit, mode]);

  const [attempt, setAttempt] = useState(0);
  const restart = () => {
    if (!ready) { setError(null); setAttempt(a => a + 1); return; }
    st.current = freshState();
    setStep(0); setStuck(false); setError(null); setHint("");
    runRef.current = true; tick();
  };

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    st.current = freshState();
    challengeRef.current = Math.random() < 0.5 ? "blink" : "turn";
    setChallenge(challengeRef.current);
    (async () => {
      try {
        const [stream] = await Promise.all([
          navigator.mediaDevices.getUserMedia({ video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } }, audio: false }),
          loadFaceModels(),
        ]);
        if (cancelled) { stream.getTracks().forEach(t => t.stop()); return; }
        streamRef.current = stream;
        if (videoRef.current) { videoRef.current.srcObject = stream; await videoRef.current.play().catch(() => {}); }
        setReady(true);
        st.current.started = Date.now();
        runRef.current = true; tick();
      } catch (e) {
        const msg = e?.message || "";
        setError(e?.name === "NotAllowedError" ? "Camera permission was blocked. Allow camera access for this site in Settings."
          : /tensor|weights|fetch|Failed to load/i.test(msg) ? "The face files didn't download properly. Check your internet, then tap Try again."
          : (msg || "Could not start the camera"));
      }
    })();
    return () => {
      cancelled = true; runRef.current = false;
      if (streamRef.current) streamRef.current.getTracks().forEach(t => t.stop());
      streamRef.current = null;
      setReady(false); setStep(0); setStuck(false); setSubmitting(false); setError(null); setFaceOn(false); setLowLight(false);
    };
  }, [open, tick, attempt]);

  if (!open) return null;
  const done = step >= steps.length;
  const instruction = !ready ? "Getting the camera ready…" : submitting ? "Checking your face…" : done ? "Done" : steps[step].say;

  return (
    <div className="fixed inset-0 z-[1000] bg-black/80 backdrop-blur-sm grid place-items-center p-4" data-testid="face-capture-modal">
      <div className="bg-card border border-border w-full max-w-md">
        <div className="p-4 border-b border-border flex items-center justify-between">
          <div>
            <div className="label-overline">{mode === "enroll" ? "Face Enrolment" : "Face Verification"}</div>
            <div className="font-semibold tracking-tight mt-0.5">{title}</div>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-secondary" data-testid="face-close-btn"><X size={18} weight="bold"/></button>
        </div>
        <div className="p-4">
          {subtitle && <p className="text-sm text-muted-foreground mb-3">{subtitle}</p>}
          <div className={`transition-colors duration-300 ${lowLight ? "bg-white p-3" : "p-0"}`} data-testid="face-light-frame">
            <div className="relative bg-black aspect-[4/3] overflow-hidden">
              <video ref={videoRef} className="w-full h-full object-cover" style={{ transform: "scaleX(-1)" }} playsInline muted/>
              <div className="absolute inset-0 grid place-items-center pointer-events-none">
                <div className={`w-44 h-56 border-[3px] rounded-[50%] transition-colors ${done ? "border-[#00E676]" : faceOn ? "border-[#FFC107]" : "border-white/50"}`}/>
              </div>
              <div className="absolute top-3 left-3 flex gap-1.5" data-testid="face-steps">
                {steps.map((s, i) => (
                  <span key={s.id} className={`h-1.5 w-8 transition-colors ${i < step ? "bg-[#00E676]" : i === step ? "bg-white" : "bg-white/30"}`}/>
                ))}
              </div>
              {lowLight && (
                <div className="absolute top-3 right-3 bg-black/70 text-white text-[11px] px-2 py-1 inline-flex items-center gap-1" data-testid="face-low-light">
                  <Lightbulb size={12} weight="fill" className="text-[#FFC107]"/> Low light — brightening
                </div>
              )}
              <div className="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/85 to-transparent p-3 pt-8 text-white">
                <div className="text-base font-semibold inline-flex items-center gap-2" data-testid="face-instruction">
                  {done && <CheckCircle size={18} weight="fill" className="text-[#00E676]"/>}{instruction}
                </div>
                {hint && !done && <div className="text-xs text-white/80 mt-0.5" data-testid="face-hint">{hint}</div>}
              </div>
            </div>
          </div>
          {submitting && <div className="loading-bar mt-3"/>}
          {(error || stuck) && (
            <div className="mt-3 border border-[#FF3B30]/30 bg-[#FF3B30]/10 p-3" data-testid="face-error">
              <div className="text-sm text-[#FF3B30]">{error || "We couldn't finish the face check."}</div>
              <Tips/>
              <button onClick={restart} data-testid="face-retry-btn"
                className="mt-3 w-full bg-foreground text-background px-4 py-2.5 inline-flex items-center justify-center gap-2 hover:bg-primary transition-colors text-sm">
                <ArrowsClockwise size={15} weight="bold"/> Try again
              </button>
            </div>
          )}
          <p className="mt-3 text-[11px] text-muted-foreground">
            {mode === "enroll"
              ? "We take 3 quick photos from slightly different angles so you're recognised reliably."
              : "A quick live check stops anyone using a photo. Your selfie is kept for 7 days as proof, then deleted."}
          </p>
        </div>
      </div>
    </div>
  );
}
