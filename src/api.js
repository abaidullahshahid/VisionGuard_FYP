import axios from "axios";

export const API_BASE = (process.env.REACT_APP_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

export const api = axios.create({
  baseURL: API_BASE,
  timeout: 20000,
});

api.interceptors.request.use((config) => {
  const token = sessionStorage.getItem("token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export function apiUrl(value) {
  if (!value) return "";
  if (/^https?:\/\//i.test(value)) return value;
  return `${API_BASE}${value.startsWith("/") ? "" : "/"}${value}`;
}

export function apiErrorMessage(error, fallback, navigate) {
  const status = error?.response?.status;
  if (status === 401) {
    sessionStorage.clear();
    if (navigate) navigate("/login", { replace: true });
    return "Your session has expired. Please sign in again.";
  }
  if (status === 403) {
    return "You do not have permission to perform this action.";
  }
  if (!error?.response) {
    return "Cannot reach the VisionGuard server. Check that the backend is running.";
  }
  return error.response?.data?.detail || fallback;
}
