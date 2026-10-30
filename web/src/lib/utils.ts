import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
export function money(value: number | null | undefined, digits = 0) {
  return value == null
    ? "N/A"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: digits,
      }).format(value);
}
export function percent(value: number | null | undefined) {
  return value == null ? "N/A" : `${(value * 100).toFixed(1)}%`;
}
export function num(value: number | null | undefined, digits = 1) {
  return value == null
    ? "N/A"
    : value.toLocaleString("en-US", { maximumFractionDigits: digits });
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(`${message} [HTTP ${status}]`);
  }
}
// A page loads session, workspace and auxiliary data. Serialize client reads so a single
// visitor cannot exceed the sealed demo's unchanged two-operation server boundary.
// Writes retain their original behavior; this does not retry or hide server errors.
let readTail: Promise<void> = Promise.resolve();
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  if ((init?.method ?? "GET").toUpperCase() !== "GET")
    return request<T>(path, init);
  const previous = readTail;
  let release!: () => void;
  readTail = new Promise<void>((resolve) => {
    release = resolve;
  });
  await previous;
  try {
    if (init?.signal?.aborted)
      throw new DOMException("The operation was aborted.", "AbortError");
    return await request<T>(path, init);
  } finally {
    release();
  }
}
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, { cache: "no-store", ...init });
  if (!response.ok) {
    if (
      response.status === 401 &&
      path !== "/auth/login" &&
      path !== "/auth/session"
    ) {
      window.dispatchEvent(new Event("logistics-auth-expired"));
    }
    let message = `Request failed (${response.status}). Check that the Python API is running.`;
    try {
      const body = await response.json();
      message =
        typeof body.detail === "string"
          ? body.detail
          : Array.isArray(body.detail)
            ? body.detail.map((item: { msg: string }) => item.msg).join("; ")
            : message;
    } catch {
      /* A stopped backend can return an HTML proxy error. */
    }
    throw new ApiError(message, response.status);
  }
  return response.json();
}
export function jsonBody(value: unknown): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(value),
  };
}
