"use client";

import { RefreshCw, X } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Shown after rates change: results on screen were worked out with the old rates
 * until reconciliation runs again.
 */
export function RecomputeHint({ className, onDismiss }: { className?: string; onDismiss: () => void }) {
  return (
    <div
      role="status"
      className={cn(
        "flex items-start gap-3 rounded-xl border border-attention/25 bg-attention-soft px-4 py-3 text-sm",
        className,
      )}
    >
      <RefreshCw className="mt-0.5 size-4 shrink-0 text-attention" aria-hidden />
      <p className="flex-1">
        <span className="font-medium">Rates saved.</span> Orders still show amounts from the last reconciliation run.
        Run reconciliation again to apply the new rates.
      </p>
      <button
        type="button"
        onClick={onDismiss}
        className="rounded-md p-0.5 text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
        aria-label="Dismiss"
      >
        <X className="size-4" />
      </button>
    </div>
  );
}
