import { useState } from "react";
import { createPortal } from "react-dom";

export default function RemoveEmployeeDialog({ emp, onCancel, onConfirm }) {
  const [typed, setTyped] = useState("");
  const ok = typed.trim().toLowerCase() === (emp.name || "").trim().toLowerCase();
  return createPortal(
    <div className="fixed inset-0 z-[1000] bg-black/80 grid place-items-center p-4" onClick={onCancel} data-testid="remove-employee-dialog">
      <div className="bg-card border border-border max-w-md w-full p-5 space-y-4" onClick={e => e.stopPropagation()}>
        <div className="text-lg font-semibold">Remove {emp.name}?</div>
        <p className="text-sm text-foreground/80">
          They will lose access to the app immediately. Their attendance and leave history is kept for reports.
        </p>
        <div>
          <label className="text-xs font-medium block mb-1.5">Type <strong>{emp.name}</strong> to confirm</label>
          <input value={typed} onChange={e => setTyped(e.target.value)} autoFocus
            className="w-full bg-background border border-border px-3 py-2 text-sm" data-testid="remove-employee-confirm-input"/>
        </div>
        <div className="flex gap-2 justify-end">
          <button onClick={onCancel} className="border border-border px-4 py-2 text-sm hover:bg-secondary" data-testid="remove-employee-cancel">Cancel</button>
          <button onClick={onConfirm} disabled={!ok} className="bg-[#FF3B30] text-white px-4 py-2 text-sm disabled:opacity-40" data-testid="remove-employee-confirm-btn">Remove</button>
        </div>
      </div>
    </div>,
    document.body
  );
}
