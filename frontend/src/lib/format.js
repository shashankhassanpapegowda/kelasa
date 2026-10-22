export const fmtTime = (iso) => iso ? new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : "—";

export const fmtDate = (iso) => iso ? new Date(iso).toLocaleDateString([], { day: '2-digit', month: 'short' }) : "—";

export const fmtDay = (d) => d ? new Date(`${d}T00:00:00`).toLocaleDateString([], { day: '2-digit', month: 'short' }) : "—";

export const fmtDuration = (mins) => {
  if (mins == null) return "—";
  const h = Math.floor(mins / 60); const m = mins % 60;
  return `${h}h ${m}m`;
};

export const fmtAgo = (iso) => {
  if (!iso) return "no ping yet";
  const s = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
};

export const fmtAcc = (m) => {
  if (m == null) return "";
  if (m < 1000) return `±${Math.round(m)}m`;
  return `±${(m / 1000).toFixed(1)}km`;
};

export const accClass = (m) => {
  if (m == null) return "text-muted-foreground";
  if (m > 200) return "text-[#FF3B30]";
  if (m > 100) return "text-yellow-600";
  return "text-[#00E676]";
};

export const today = () => new Date().toISOString().slice(0, 10);
