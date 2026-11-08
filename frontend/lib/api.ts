/**
 * Thin fetch wrapper for the PayTrace API.
 *
 * The session lives in an httpOnly cookie set by the backend, so every request sends
 * credentials and no token is ever handled in JavaScript.
 */

import { startWaking, stopWaking } from "@/lib/server-status";

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

/** Proxy mode: the API is reached through this site's /api route (see deployment.md). */
export const IS_PROXY_MODE = API_URL.startsWith("/");

/**
 * Largest upload the browser will send. Through the Vercel proxy, request bodies are capped at about
 * 4.5 MB, so proxy mode defaults to 4 MB; direct mode matches the API's own 50 MB limit.
 */
export const MAX_UPLOAD_MB = Number(process.env.NEXT_PUBLIC_MAX_UPLOAD_MB) || (IS_PROXY_MODE ? 4 : 50);

export class ApiError extends Error {
  /** HTTP status, or 0 when the server could not be reached at all. */
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }

  get isUnauthorized(): boolean {
    return this.status === 401;
  }
}

/** FastAPI returns `{detail: string}` or, for validation errors, `{detail: [{msg}]}`. */
function readErrorDetail(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg);
  }
  return fallback;
}

/** How long to keep retrying while the free-plan backend wakes up (it takes about a minute). */
const COLD_START_BUDGET_MS = 90_000;
const COLD_START_STATUSES = new Set([502, 503, 504]);
const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export type ApiInit = RequestInit & {
  /**
   * Retry through a backend cold start. On by default for reads (GET/HEAD). Writes are not retried unless
   * they opt in, because a 504 can arrive after the server already acted; sign-in opts in, since repeating
   * it is harmless.
   */
  coldStartRetry?: boolean;
};

/**
 * One request, retried with backoff while the backend is waking up: a 502/503/504 from the hosting edge,
 * or no connection at all. While retrying, the app shows "Waking up the server…" instead of an error.
 */
async function fetchThroughColdStart(url: string, init: RequestInit, retry: boolean): Promise<Response> {
  const started = Date.now();
  let attempt = 0;
  let waking = false;
  try {
    for (;;) {
      let response: Response | null = null;
      try {
        response = await fetch(url, init);
      } catch {
        response = null; // network error: the server may still be booting
      }
      const coldStart = response === null || COLD_START_STATUSES.has(response.status);
      if (!coldStart || !retry || Date.now() - started > COLD_START_BUDGET_MS) {
        if (response === null) throw new ApiError(0, "Can't reach the PayTrace server. Check your connection and try again.");
        return response;
      }
      if (!waking) {
        waking = true;
        startWaking();
      }
      attempt += 1;
      await wait(Math.min(1000 * 2 ** (attempt - 1), 10_000)); // 1, 2, 4, 8, 10, 10… seconds
    }
  } finally {
    if (waking) stopWaking();
  }
}

export async function apiFetch<T>(path: string, init: ApiInit = {}): Promise<T> {
  const { coldStartRetry, ...requestInit } = init;
  const headers = new Headers(requestInit.headers);
  if (requestInit.body && !(requestInit.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const method = (requestInit.method ?? "GET").toUpperCase();
  const retry = coldStartRetry ?? (method === "GET" || method === "HEAD");

  const response = await fetchThroughColdStart(`${API_URL}${path}`, { ...requestInit, headers, credentials: "include" }, retry);

  if (response.status === 204) return undefined as T;

  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    if (COLD_START_STATUSES.has(response.status)) {
      throw new ApiError(response.status, "The PayTrace server is still waking up or unavailable. Wait a minute, then try again.");
    }
    throw new ApiError(response.status, readErrorDetail(body, `Request failed (${response.status}).`));
  }
  return body as T;
}

/**
 * POST a form with upload progress (fetch cannot report it). Same credentials and errors as apiFetch.
 * `onProgress` receives 0–1 while the file is sent; the promise resolves once the API has answered.
 */
export function apiUpload<T>(path: string, form: FormData, onProgress?: (fraction: number) => void): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", `${API_URL}${path}`);
    request.withCredentials = true;
    request.responseType = "json";
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.(event.loaded / event.total);
    };
    request.upload.onload = () => onProgress?.(1);
    request.onerror = () => reject(new ApiError(0, "Can't reach the PayTrace server. Check your connection and try again."));
    request.onload = () => {
      const body: unknown = request.response;
      if (request.status >= 200 && request.status < 300) resolve(body as T);
      else if (request.status === 413) reject(new ApiError(413, `The file is too large for this deployment (limit ${MAX_UPLOAD_MB} MB).`));
      else reject(new ApiError(request.status, readErrorDetail(body, `Upload failed (${request.status}).`)));
    };
    request.send(form);
  });
}

/** Fetch a file from the API (with the session cookie) and hand it to the browser as a download. */
export async function downloadFile(path: string, fallbackName: string): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, { credentials: "include" });
  } catch {
    throw new ApiError(0, "Can't reach the PayTrace server. Check your connection and try again.");
  }
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    throw new ApiError(response.status, readErrorDetail(body, `Download failed (${response.status}).`));
  }
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const name = /filename="?([^"]+)"?/.exec(disposition)?.[1] ?? fallbackName;
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
