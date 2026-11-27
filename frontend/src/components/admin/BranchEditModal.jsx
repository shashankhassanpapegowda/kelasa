import { useState } from "react";
import { createPortal } from "react-dom";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { getAccuratePosition } from "@/lib/geo";
import BranchMapPicker from "@/components/admin/BranchMapPicker";
import { Switch } from "@/components/ui/switch";
import { X, MagnifyingGlass, Crosshair } from "@phosphor-icons/react";

const inputCls = "w-full bg-background border border-border px-3 py-2 text-sm";

export default function BranchEditModal({ branch, others, onClose, onSaved }) {
  const [name, setName] = useState(branch.name);
  const [address, setAddress] = useState(branch.address || "");
  const [pin, setPin] = useState(branch.lat != null ? { lat: branch.lat, lng: branch.lng } : null);
  const [radius, setRadius] = useState(branch.radius_m || 100);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [sandwich, setSandwich] = useState(!!branch.leave_sandwich_lop);

  const search = async () => {
    if (!query.trim()) return;
    setBusy(true);
    try {
      const { data } = await api.get("/admin/geocode", { params: { q: query.trim() } });
      if (!data.result) return toast.error("Place not found — try a nearby landmark or click on the map");
      setPin({ lat: data.result.lat, lng: data.result.lng });
      if (!address) setAddress(data.result.label);
      if (data.result.approximate) toast.info("Showing the town centre — click the exact spot on the map");
    } catch { toast.error("Search failed — click on the map instead"); }
    finally { setBusy(false); }
  };

  const useMyLocation = async () => {
    setBusy(true);
    try {
      const g = await getAccuratePosition({ desiredAccuracy: 30, maxWait: 12000 });
      setPin({ lat: g.lat, lng: g.lng });
      toast.success(`Pinned your location (±${Math.round(g.accuracy)} m)`);
    } catch (e) { toast.error(e?.message || "Could not get your location"); }
    finally { setBusy(false); }
  };

  const save = async (clear = false) => {
    const r = Number(radius);
    if (!clear && pin && (r < 10 || r > 10000)) return toast.error("Radius must be 10 – 10000 metres");
    setBusy(true);
    try {
      const body = { name, address, leave_sandwich_lop: sandwich };
      if (clear) body.clear_geofence = true;
      else if (pin) Object.assign(body, { lat: pin.lat, lng: pin.lng, radius_m: Math.round(r) });
      await api.patch(`/admin/org/sites/${branch.unit_id}`, body);
      toast.success(clear ? "Geofence removed" : `${name} geofence saved · ${Math.round(r)} m`);
      onSaved();
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not save"); }
    finally { setBusy(false); }
  };

  return createPortal(
    <div className="fixed inset-0 z-[1000] bg-black/80 backdrop-blur-sm grid place-items-center p-4 overflow-y-auto" onClick={onClose} data-testid="branch-edit-modal">
      <div className="bg-card border border-border max-w-2xl w-full my-8" onClick={(e) => e.stopPropagation()}>
        <div className="p-4 border-b border-border flex items-center justify-between">
          <div>
            <div className="label-overline">Branch Geofence</div>
            <div className="font-semibold tracking-tight mt-0.5">{branch.name}</div>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-secondary" data-testid="branch-modal-close"><X size={18} weight="bold"/></button>
        </div>
        <div className="p-5 space-y-4">
          <div className="grid sm:grid-cols-2 gap-3">
            <div>
              <label className="label-overline mb-1.5 block">Branch Name</label>
              <input value={name} onChange={e => setName(e.target.value)} className={inputCls} data-testid="branch-name-input"/>
            </div>
            <div>
              <label className="label-overline mb-1.5 block">Address (optional)</label>
              <input value={address} onChange={e => setAddress(e.target.value)} className={inputCls} data-testid="branch-address-input"/>
            </div>
          </div>
          <div className="flex gap-2 flex-wrap">
            <div className="relative flex-1 min-w-[200px]">
              <MagnifyingGlass size={14} weight="bold" className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground"/>
              <input value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => e.key === "Enter" && search()}
                placeholder="Search a place or address" className={`${inputCls} pl-8`} data-testid="branch-search-input"/>
            </div>
            <button onClick={search} disabled={busy} className="border border-border px-3 py-2 text-sm hover:bg-secondary disabled:opacity-50" data-testid="branch-search-btn">Find</button>
            <button onClick={useMyLocation} disabled={busy} className="border border-border px-3 py-2 text-sm hover:bg-secondary inline-flex items-center gap-1.5 disabled:opacity-50" data-testid="branch-my-location-btn">
              <Crosshair size={14} weight="bold"/> My location
            </button>
          </div>
          <BranchMapPicker pin={pin} radius={Number(radius) || 0} onPick={setPin} others={others}/>
          <p className="text-[11px] text-muted-foreground -mt-2">Click anywhere on the map to drop the pin. Dashed circles are your other branches.</p>
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="label-overline">Radius</label>
              <div className="flex items-center gap-1">
                <input type="number" min="10" max="10000" value={radius} onChange={e => setRadius(e.target.value)}
                  className="w-24 bg-background border border-border px-2 py-1 text-sm font-mono text-right" data-testid="branch-radius-input"/>
                <span className="text-xs font-mono text-muted-foreground">m</span>
              </div>
            </div>
            <input type="range" min="10" max="2000" step="10" value={Math.min(Number(radius) || 10, 2000)} onChange={e => setRadius(e.target.value)}
              className="w-full accent-[#0047FF]" data-testid="branch-radius-slider"/>
            {pin && <div className="text-[10px] font-mono text-muted-foreground mt-1" data-testid="branch-pin-coords">{pin.lat.toFixed(6)}, {pin.lng.toFixed(6)}</div>}
          </div>
          <div className="flex items-center justify-between gap-3 border border-border px-3 py-3">
            <div>
              <label htmlFor="branch-sandwich-lop" className="text-sm font-medium">Holiday sandwich is loss of pay</label>
              <p className="text-[11px] text-muted-foreground mt-0.5">Saturdays, Mondays, and the day before, of and after a holiday are unpaid if the employee does not punch in. Other branches stay unchanged.</p>
            </div>
            <Switch id="branch-sandwich-lop" checked={sandwich} onCheckedChange={setSandwich} data-testid="branch-sandwich-lop"/>
          </div>
          <div className="flex items-center gap-2 pt-1 flex-wrap">
            <button onClick={() => save(false)} disabled={busy} data-testid="branch-save-btn"
              className="flex-1 bg-foreground text-background px-4 py-3 hover:bg-primary transition-colors font-medium disabled:opacity-50">Save Geofence</button>
            {branch.lat != null && (
              <button onClick={() => save(true)} disabled={busy} data-testid="branch-clear-btn"
                className="border border-border px-4 py-3 hover:border-[#FF3B30] hover:text-[#FF3B30]">Remove Geofence</button>
            )}
            <button onClick={onClose} className="border border-border px-4 py-3 hover:bg-secondary">Cancel</button>
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}
