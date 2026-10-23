import { useEffect, useState } from "react";
import { api } from "@/lib/api";

const cache = new Map();

const loadBlobUrl = (path) => {
  if (!cache.has(path)) {
    const p = api.get(`/files/${path}`, { responseType: "blob" })
      .then(res => URL.createObjectURL(res.data))
      .catch(err => { cache.delete(path); throw err; });
    cache.set(path, p);
  }
  return cache.get(path);
};

/** Auth-aware <img> for object-storage files; blob URLs are cached per path. */
export default function AuthPhoto({ path, className, alt = "", fallback = null }) {
  const [src, setSrc] = useState(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    setSrc(null); setErr(false);
    if (!path) return;
    let cancelled = false;
    loadBlobUrl(path).then(u => { if (!cancelled) setSrc(u); }).catch(() => { if (!cancelled) setErr(true); });
    return () => { cancelled = true; };
  }, [path]);

  if (!path || err) return fallback;
  if (!src) return <div className={`${className} bg-secondary animate-pulse`}/>;
  return <img src={src} alt={alt} className={className}/>;
}
