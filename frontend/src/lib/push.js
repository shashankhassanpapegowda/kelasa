import { api } from "@/lib/api";

const toBytes = (v) => {
  const pad = "=".repeat((4 - (v.length % 4)) % 4);
  const raw = atob((v + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
};

export const pushSupported = () =>
  "serviceWorker" in navigator && "PushManager" in window && "Notification" in window && window.isSecureContext;

export const isIOS = () => /iphone|ipad|ipod/i.test(navigator.userAgent);
export const isStandalone = () =>
  window.matchMedia?.("(display-mode: standalone)").matches || window.navigator.standalone === true;

export async function currentSubscription() {
  if (!pushSupported()) return null;
  const reg = await navigator.serviceWorker.getRegistration("/");
  return reg ? reg.pushManager.getSubscription() : null;
}

export async function enablePush() {
  const permission = await Notification.requestPermission();
  if (permission !== "granted") throw new Error("Notifications are blocked. Allow them in your browser settings.");
  const reg = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
  await navigator.serviceWorker.ready;
  const old = await reg.pushManager.getSubscription();
  if (old) await old.unsubscribe();
  const { data } = await api.get("/push/public-key");
  const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: toBytes(data.public_key) });
  await api.post("/push/subscribe", sub.toJSON());
  return sub;
}

export async function updateDevice(settings) {
  const sub = await currentSubscription();
  if (!sub) throw new Error("This phone isn't subscribed");
  await api.patch("/push/subscribe", { endpoint: sub.endpoint, ...settings });
}

export async function disablePush() {
  const sub = await currentSubscription();
  if (!sub) return;
  await api.delete("/push/subscribe", { params: { endpoint: sub.endpoint } }).catch(() => {});
  await sub.unsubscribe();
}
