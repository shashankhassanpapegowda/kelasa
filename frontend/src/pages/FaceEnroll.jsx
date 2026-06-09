import { useState } from "react";
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

  const handleCapture = async ({ descriptor, image_b64 }) => {
    try {
      await api.post("/face/enroll", { descriptor, image_b64 });
      await checkAuth();
      toast.success("Face enrolled successfully.");
      setOpen(false);
      navigate(user?.role === "admin" ? "/admin" : "/dashboard", { replace: true });
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Enrollment failed");
      throw e;
    }
  };

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
            Before you can check in, we need a clear reference photo of your face. This is used to verify your identity at every check-in and check-out.
          </p>
          <ul className="mt-6 space-y-2.5 text-sm">
            <li className="flex items-start gap-2"><ShieldCheck size={16} weight="bold" className="text-primary mt-0.5"/> Face data is stored as a math vector (128 numbers) — not searchable as a photo.</li>
            <li className="flex items-start gap-2"><Camera size={16} weight="bold" className="text-primary mt-0.5"/> Look directly at the camera in good lighting. Remove glasses or masks if possible.</li>
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
        subtitle="Center your face in the ring. We'll capture a single reference image."
        cta="Enrol Face"
        onClose={() => setOpen(false)}
        onCapture={handleCapture}
      />
    </div>
  );
}
