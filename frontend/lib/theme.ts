"use client";

import { useSyncExternalStore } from "react";

/**
 * Light / dark theme, chosen per viewer and remembered in this browser only.
 * The class on <html> is set before first paint by THEME_SCRIPT (app/layout.tsx), so there is no flash;
 * this module keeps React in sync with it.
 */

export type Theme = "light" | "dark";

const STORAGE_KEY = "paytrace-theme";
const listeners = new Set<() => void>();

/** Runs inline in <head> before the page paints. Light is the default; a saved choice wins. */
export const THEME_SCRIPT = `try{if(localStorage.getItem("${STORAGE_KEY}")==="dark")document.documentElement.classList.add("dark")}catch(e){}`;

function currentTheme(): Theme {
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function setTheme(theme: Theme): void {
  const root = document.documentElement;
  // Switch every colour at once rather than letting each element run its own transition.
  root.classList.add("theme-switching");
  root.classList.toggle("dark", theme === "dark");
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // Private mode or blocked storage: the theme still applies for this visit.
  }
  window.requestAnimationFrame(() => window.requestAnimationFrame(() => root.classList.remove("theme-switching")));
  for (const listener of listeners) listener();
}

export function toggleTheme(): void {
  setTheme(currentTheme() === "dark" ? "light" : "dark");
}

export function useTheme(): Theme {
  return useSyncExternalStore(subscribe, currentTheme, () => "light");
}
