import { cn } from "@/lib/utils";

export type Tone = "settled" | "loss" | "attention" | "neutral" | "info";

const TONES: Record<Tone, string> = {
  settled: "bg-settled-soft text-settled ring-settled/20",
  loss: "bg-loss-soft text-loss ring-loss/20",
  attention: "bg-attention-soft text-attention ring-attention/25",
  neutral: "bg-secondary text-secondary-foreground ring-border",
  info: "bg-sidebar-accent text-sidebar-accent-foreground ring-primary/15",
};

/** A small coloured label. Colour carries meaning only (red = money lost, amber = needs a look, green = settled). */
export function StatusPill({ label, tone, className }: { label: string; tone: Tone; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ring-1 ring-inset",
        TONES[tone],
        className,
      )}
    >
      <span aria-hidden className="size-1.5 rounded-full bg-current" />
      {label}
    </span>
  );
}
