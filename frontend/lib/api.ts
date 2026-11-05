/**
 * Thin fetch wrapper for the PayTrace API.
 *
 * The session lives in an httpOnly cookie set by the backend, so every request sends
 * credentials and no token is ever handled in JavaScript.
 */

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

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, { ...init, headers, credentials: "include" });
  } catch {
    throw new ApiError(0, "Can't reach the PayTrace server. Check your connection and try again.");
  }

  if (response.status === 204) return undefined as T;

  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
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
