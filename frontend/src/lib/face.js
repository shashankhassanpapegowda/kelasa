import * as faceapi from "face-api.js";

const MODEL_URL = "/models";
let loadingPromise = null;

export function loadFaceModels() {
  if (!loadingPromise) {
    loadingPromise = Promise.all([
      faceapi.nets.tinyFaceDetector.loadFromUri(MODEL_URL),
      faceapi.nets.faceLandmark68Net.loadFromUri(MODEL_URL),
      faceapi.nets.faceRecognitionNet.loadFromUri(MODEL_URL),
      faceapi.nets.ssdMobilenetv1.loadFromUri(MODEL_URL),
    ]).catch(async (e) => {
      loadingPromise = null;
      if (window.caches) for (const k of await caches.keys()) if (k.startsWith("kelasa-face-models-")) await caches.delete(k);
      throw e;
    });
  }
  return loadingPromise;
}

// Warm the models in the background so the camera opens instantly later.
export function preloadFaceModels() {
  const run = () => loadFaceModels().catch(() => {});
  if (window.requestIdleCallback) window.requestIdleCallback(run, { timeout: 4000 });
  else setTimeout(run, 1500);
}

const tinyOpts = new faceapi.TinyFaceDetectorOptions({ inputSize: 320, scoreThreshold: 0.4 });
const ssdOpts = new faceapi.SsdMobilenetv1Options({ minConfidence: 0.5 });

const probe = document.createElement("canvas");
probe.width = 32; probe.height = 24;
export function frameLuminance(video) {
  const ctx = probe.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(video, 0, 0, 32, 24);
  const d = ctx.getImageData(0, 0, 32, 24).data;
  let sum = 0;
  for (let i = 0; i < d.length; i += 4) sum += 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
  return sum / (d.length / 4);
}

// Brightens dark frames so detection still works in low light.
const work = document.createElement("canvas");
export function enhancedFrame(video, gain) {
  if (!gain || gain <= 1.05) return video;
  const w = video.videoWidth, h = video.videoHeight;
  if (work.width !== w) { work.width = w; work.height = h; }
  const ctx = work.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(video, 0, 0, w, h);
  const img = ctx.getImageData(0, 0, w, h);
  const d = img.data;
  const add = (gain - 1) * 60;
  for (let i = 0; i < d.length; i += 4) {
    d[i] = (d[i] - 128) * 1.15 + 128 + add;
    d[i + 1] = (d[i + 1] - 128) * 1.15 + 128 + add;
    d[i + 2] = (d[i + 2] - 128) * 1.15 + 128 + add;
  }
  ctx.putImageData(img, 0, 0);
  return work;
}

export const gainFor = (lum) => (lum < 85 ? Math.min(2.4, 105 / Math.max(lum, 25)) : 1);

export async function trackFace(src) {
  return (await faceapi.detectSingleFace(src, tinyOpts).withFaceLandmarks()) || null;
}

export async function describeFace(src) {
  const r = (await faceapi.detectSingleFace(src, ssdOpts).withFaceLandmarks().withFaceDescriptor())
    || (await faceapi.detectSingleFace(src, tinyOpts).withFaceLandmarks().withFaceDescriptor());
  return r ? Array.from(r.descriptor) : null;
}

const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
const ear = (p) => (dist(p[1], p[5]) + dist(p[2], p[4])) / (2 * dist(p[0], p[3]));
export const eyeOpenness = (lm) => (ear(lm.getLeftEye()) + ear(lm.getRightEye())) / 2;

// ~0.5 when facing the camera; a flat photo stays near 0.5 even when tilted.
export function headYaw(lm) {
  const p = lm.positions;
  return (p[30].x - p[36].x) / Math.max(1, p[45].x - p[36].x);
}

export function captureFrameAsJpeg(src, maxWidth = 480, quality = 0.85) {
  const vw = src.videoWidth || src.width, vh = src.videoHeight || src.height;
  const w = Math.min(vw, maxWidth);
  const h = (vh / vw) * w;
  const canvas = document.createElement("canvas");
  canvas.width = w; canvas.height = h;
  canvas.getContext("2d").drawImage(src, 0, 0, w, h);
  return canvas.toDataURL("image/jpeg", quality);
}
