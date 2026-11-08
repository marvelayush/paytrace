"use client";

import { useSyncExternalStore } from "react";

/**
 * "The server is waking up" flag, shared by every request.
 *
 * The backend runs on a free plan that sleeps when idle. While a request is being retried through a cold
 * start (see apiFetch), the app shows a calm banner instead of an error.
 */
let waking = 0; // requests currently retrying a cold start
const listeners = new Set<() => void>();

function emit() {
  for (const listener of listeners) listener();
}

export function startWaking() {
  waking += 1;
  if (waking === 1) emit();
}

export function stopWaking() {
  waking = Math.max(0, waking - 1);
  if (waking === 0) emit();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useServerWaking(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => waking > 0,
    () => false,
  );
}
