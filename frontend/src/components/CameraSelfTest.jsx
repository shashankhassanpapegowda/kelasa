import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import FaceCapture from "@/components/FaceCapture";
import { ScanSmiley, CheckCircle, Warning, Lightbulb } from "@phosphor-icons/react";

const RESULT = {
  strong: { text: "Strong match — you're all set.", tone: "good" },
  good: { text: "Good match — check-ins will work.", tone: "good" },
  borderline: { text: "Borderline match. Check-ins may get flagged — try better light, or ask your manager to reset your face and enrol again.", tone: "warn" },
};

export const CameraSelfTest = ({ enrolled }) => {
  const [open, setOpen] = useState(false);
  const [result, setResult] = useState(null);

  const onCapture = async ({ descriptors, liveness }) => {
    try {
      const r = (await api.post("/face/test", { descriptors, liveness })).data;
      setResult({ ...RESULT[r.quality], low: r.low_light });
      setOpen(false);
    } catch (e) {
      if (e?.response?.status === 403) {
        setResult({ text: e.response.data.detail, tone: "bad" });
        setOpen(false);
        return;
      }
      throw e;
    }
  };

  const tone = result?.tone === "good" ? "border-[#00E676]/40 bg-[#00E676]/10 text-[#00A152]"
    : result?.tone === "warn" ? "border-[#FFC107]/40 bg-[#FFC107]/10 text-[#8A6200]" : "border-[#FF3B30]/30 bg-[#FF3B30]/10 text-[#FF3B30]";

  return (
    <section className="border border-border bg-card p-5" data-testid="camera-self-test">
      <div className="flex items-center gap-2">
        <ScanSmiley size={16} weight="bold" className="text-primary"/>
        <span className="label-overline">Test my camera</span>
      </div>
      <p className="text-sm text-muted-foreground mt-2">
        Try the face check before your shift. Nothing is saved and no attendance is recorded.
      </p>
      {enrolled ? (
        <button onClick={() => { setResult(null); setOpen(true); }} data-testid="camera-test-btn"
          className="mt-4 bg-foreground text-background px-4 py-2.5 text-sm hover:bg-primary transition-colors">
          Test my camera
        </button>
      ) : (
        <Link to="/enroll" className="mt-4 inline-block text-sm underline" data-testid="camera-test-enroll-link">Enrol your face first</Link>
      )}
      {result && (
        <div className={`mt-4 border p-3 text-sm flex gap-2 ${tone}`} data-testid="camera-test-result">
          {result.tone === "good" ? <CheckCircle size={18} weight="fill" className="shrink-0"/> : <Warning size={18} weight="fill" className="shrink-0"/>}
          <div>
            {result.text}
            {result.low && <div className="text-xs mt-1 inline-flex items-center gap-1 text-muted-foreground"><Lightbulb size={12}/> Your light was low — facing a window or lamp helps.</div>}
          </div>
        </div>
      )}
      <FaceCapture open={open} title="Camera test" subtitle="Follow the prompts — this is just a practice run."
        onClose={() => setOpen(false)} onCapture={onCapture}
        note="Practice run — no photo is saved and no attendance is recorded."/>
    </section>
  );
};
