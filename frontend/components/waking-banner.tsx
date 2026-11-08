"use client";

import { LoaderCircle } from "lucide-react";

import { useServerWaking } from "@/lib/server-status";

/**
 * Shown while a request is retrying through a backend cold start (free plan: the server sleeps when idle).
 * Informational, not an error: the request continues by itself and the screen loads when the server is up.
 */
export function WakingBanner() {
  const waking = useServerWaking();
  if (!waking) return null;
  return (
    <div className="pointer-events-none fixed inset-x-0 top-3 z-50 flex justify-center px-4">
      <div
        role="status"
        aria-live="polite"
        className="pointer-events-auto flex max-w-md items-center gap-2.5 rounded-xl border bg-card px-4 py-2.5 text-sm shadow-md"
      >
        <LoaderCircle className="size-4 shrink-0 animate-spin text-primary" aria-hidden />
        <span>Waking up the server — this can take up to a minute on the free tier.</span>
      </div>
    </div>
  );
}
