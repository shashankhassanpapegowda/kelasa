import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;
const TOKEN_KEY = "gtg_session_token";

export const getToken = () => {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
};
export const setToken = (t) => {
  try {
    if (t) localStorage.setItem(TOKEN_KEY, t);
    else localStorage.removeItem(TOKEN_KEY);
  } catch (e) { /* storage unavailable */ }
};

export const api = axios.create({
  baseURL: API,
  withCredentials: true,
});

// Attach Bearer token as a fallback for browsers that drop the httpOnly cookie
api.interceptors.request.use((config) => {
  const t = getToken();
  if (t && !config.headers.Authorization) {
    config.headers.Authorization = `Bearer ${t}`;
  }
  return config;
});

// Global 401 handler: surface a clean re-login instead of silent failures
let onUnauthorized = null;
export const setUnauthorizedHandler = (fn) => { onUnauthorized = fn; };

api.interceptors.response.use(
  (res) => res,
  (err) => {
    const url = err?.config?.url || "";
    const isAuthAttempt = /\/auth\/(login|forgot-password|reset-password|change-password)/.test(url);
    if (err?.response?.status === 401 && !isAuthAttempt) {
      setToken(null);
      if (onUnauthorized) onUnauthorized();
    }
    return Promise.reject(err);
  }
);

export const apiErrorMessage = (err, fallback = "Something went wrong. Please try again.") => {
  const detail = err?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((e) => (e?.msg ? e.msg : JSON.stringify(e))).join(" ");
  if (detail?.msg) return detail.msg;
  return err?.message || fallback;
};
