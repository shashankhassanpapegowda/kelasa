import { useEffect, useState } from "react";
import { preloadFaceModels } from "@/lib/face";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import FaceCapture from "@/components/FaceCapture";
import { UserCirclePlus, ShieldCheck, Camera } from "@phosphor-icons/react";

export default function FaceEnroll() {
  const { user, checkAuth } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);

  const handleCapture = async ({ descriptors, image_b64 }) => {
    await api.post("/face/enroll", { descriptors, image_b64 });
    await checkAuth();
    toast.success("Face enrolled successfully.");
    setOpen(false);
    navigate(user?.role === "admin" ? "/admin" : "/dashboard", { replace: true });
  };
  useEffect(() => { preloadFaceModels(); }, []);

  return (
    <div className="min-h-screen bg-background grid place-items-center p-6">
      <div className="w-full max-w-lg bg-card border border-border">
        <div className="p-8">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-foreground text-background grid place-items-center"><UserCirclePlus size={22} weight="bold"/></div>
            <div>
              <div className="label-overline">Step 1 of 1</div>
              <div className="font-semibold tracking-tight text-lg">Enroll your face</div>
            </div>
          </div>
          <p className="mt-5 text-sm text-muted-foreground leading-relaxed">
            Before you can check in, we take 3 quick photos of your face from slightly different angles. They are used to recognise you at every check-in and check-out, and the app keeps learning your face as you use it.
          </p>
          <ul className="mt-6 space-y-2.5 text-sm">
            <li className="flex items-start gap-2"><ShieldCheck size={16} weight="bold" className="text-primary mt-0.5"/> Face data is stored as a math vector (128 numbers) — not searchable as a photo.</li>
            <li className="flex items-start gap-2"><Camera size={16} weight="bold" className="text-primary mt-0.5"/> Face a light, take off any helmet, cap or mask. Glasses are fine.</li>
          </ul>
          <button
            onClick={() => setOpen(true)}
            data-testid="start-enrollment-btn"
            className="mt-7 w-full bg-foreground text-background px-4 py-4 inline-flex items-center justify-center gap-2 hover:bg-primary transition-colors"
          >
            <Camera size={18} weight="bold"/>
            <span className="font-medium">Start Face Enrollment</span>
          </button>
        </div>
      </div>
      <FaceCapture
        open={open}
        title="Enrol your face"
        subtitle="Follow the prompts — the photos are taken automatically."
        mode="enroll"
        onClose={() => setOpen(false)}
        onCapture={handleCapture}
      />
    </div>
  );
}
