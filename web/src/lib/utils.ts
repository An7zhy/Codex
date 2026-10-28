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

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, { cache: "no-store", ...init });
  if (!response.ok) {
    if (response.status === 401 && path !== "/auth/login" && path !== "/auth/session") {
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
    throw new Error(message);
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
