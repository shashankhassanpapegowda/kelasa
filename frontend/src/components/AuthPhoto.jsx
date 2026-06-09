import { useEffect, useState } from "react";
import { api, API } from "@/lib/api";

/**
 * Auth-aware <img> that fetches an object-storage file via the backend
 * with credentials and displays it as a blob URL.
 */
export default function AuthPhoto({ path, className, alt = "", fallback = null }) {
  const [src, setSrc] = useState(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    if (!path) { setSrc(null); return; }
    let cancelled = false;
    let objUrl = null;
    (async () => {
      try {
        const res = await api.get(`/files/${path}`, { responseType: "blob" });
        if (cancelled) return;
        objUrl = URL.createObjectURL(res.data);
        setSrc(objUrl);
      } catch {
        if (!cancelled) setErr(true);
      }
    })();
    return () => {
      cancelled = true;
      if (objUrl) URL.revokeObjectURL(objUrl);
    };
  }, [path]);

  if (!path || err) return fallback;
  if (!src) return <div className={`${className} bg-secondary animate-pulse`}/>;
  return <img src={src} alt={alt} className={className}/>;
}
