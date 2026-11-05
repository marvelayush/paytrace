"use client";

import { useSyncExternalStore } from "react";

/** App-wide overlays that any screen or shortcut can open: the command palette and the shortcuts sheet. */

type Overlay = "palette" | "shortcuts" | null;

let open: Overlay = null;
const listeners = new Set<() => void>();

function emit() {
  for (const listener of listeners) listener();
}

export function openOverlay(overlay: Exclude<Overlay, null>): void {
  open = overlay;
  emit();
}

export function closeOverlay(): void {
  open = null;
  emit();
}

export function useOverlay(): Overlay {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => open,
    () => null,
  );
}

/** True when a key press is meant for a text field, so single-key shortcuts must not fire. */
export function isTyping(event: KeyboardEvent): boolean {
  const target = event.target as HTMLElement | null;
  if (!target) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
}

/** "⌘" on Apple devices, "Ctrl" elsewhere, for shortcut hints. */
export function modKeyLabel(): string {
  if (typeof navigator === "undefined") return "Ctrl";
  return /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent) ? "⌘" : "Ctrl";
}

const noSubscription = () => () => {};

/** The modifier key label, rendered as "Ctrl" on the server and corrected in the browser. */
export function useModKey(): string {
  return useSyncExternalStore(noSubscription, modKeyLabel, () => "Ctrl");
}
