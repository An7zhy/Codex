"use client";

import { useEffect, useState, type Dispatch, type SetStateAction } from "react";
import { useAccess } from "@/components/access";

/** Per-account/per-instance TAB storage, not tokens or shared organization data. */
function compatible(value: unknown, initial: unknown): boolean {
  if (value === null || typeof value !== typeof initial || Array.isArray(value) !== Array.isArray(initial)) return false;
  if (typeof value === "number") return Number.isFinite(value);
  if (initial && typeof initial === "object" && !Array.isArray(initial)) {
    return Object.entries(initial).every(([key, template]) => compatible((value as Record<string, unknown>)[key], template));
  }
  return true;
}
export function useSessionDraft<T>(name: string, initial: T, validate?: (value: unknown) => boolean): [T, Dispatch<SetStateAction<T>>, boolean, boolean] {
  const user = useAccess();
  const key = `logistics-draft:${user?.instance_id}:${user?.username}:${name}`;
  const [value, setValue] = useState(initial);
  const [loadedKey, setLoadedKey] = useState("");
  const [restored, setRestored] = useState(false);
  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(key);
      if (raw && raw.length < 512_000) {
        const parsed = JSON.parse(raw);
        if (compatible(parsed, initial) && (!validate || validate(parsed))) {
          setValue(parsed); setRestored(true);
        }
      }
    } catch { /* Unavailable/corrupted storage leaves the in-memory draft usable. */ }
    setLoadedKey(key);
  }, [key]); // initial is a fallback, not a dependency that resets active input
  useEffect(() => {
    if (loadedKey !== key) return;
    try {
      const encoded = JSON.stringify(value);
      if (encoded.length < 512_000) sessionStorage.setItem(key, encoded);
    } catch { /* Never prevent a calculation if tab storage is unavailable. */ }
  }, [key, loadedKey, value]);
  return [value, setValue, loadedKey === key, restored];
}
