"use client";

import { useSyncExternalStore } from "react";

/** Live result of a CSS media query (false on the server and before hydration). */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (listener) => {
      const list = window.matchMedia(query);
      list.addEventListener("change", listener);
      return () => list.removeEventListener("change", listener);
    },
    () => window.matchMedia(query).matches,
    () => false,
  );
}

/** Phones and small tablets: card lists, bottom sheets. Matches Tailwind's `md` breakpoint. */
export function useIsMobile(): boolean {
  return useMediaQuery("(max-width: 767px)");
}
