import * as faceapi from "face-api.js";

const MODEL_URL = "https://justadudewhohacks.github.io/face-api.js/models";

let loadingPromise = null;
let loaded = false;

export async function loadFaceModels() {
  if (loaded) return true;
  if (loadingPromise) return loadingPromise;
  loadingPromise = (async () => {
    await Promise.all([
      faceapi.nets.tinyFaceDetector.loadFromUri(MODEL_URL),
      faceapi.nets.faceLandmark68Net.loadFromUri(MODEL_URL),
      faceapi.nets.faceRecognitionNet.loadFromUri(MODEL_URL),
    ]);
    loaded = true;
    return true;
  })();
  return loadingPromise;
}

export async function detectFace(videoEl) {
  await loadFaceModels();
  const opts = new faceapi.TinyFaceDetectorOptions({ inputSize: 320, scoreThreshold: 0.5 });
  const result = await faceapi
    .detectSingleFace(videoEl, opts)
    .withFaceLandmarks()
    .withFaceDescriptor();
  return result || null;
}

export function captureFrameAsJpeg(videoEl, maxWidth = 480, quality = 0.85) {
  const w = Math.min(videoEl.videoWidth, maxWidth);
  const h = (videoEl.videoHeight / videoEl.videoWidth) * w;
  const canvas = document.createElement("canvas");
  canvas.width = w; canvas.height = h;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(videoEl, 0, 0, w, h);
  return canvas.toDataURL("image/jpeg", quality);
}
