"use client";

import { useEffect } from "react";

import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { closeOverlay, isTyping, openOverlay, useModKey, useOverlay } from "@/lib/ui-store";

function Keys({ keys }: { keys: string[] }) {
  return (
    <span className="flex shrink-0 items-center gap-1">
      {keys.map((key) => (
        <kbd
          key={key}
          className="inline-flex h-6 min-w-6 items-center justify-center rounded-md border bg-secondary px-1.5 font-sans text-xs font-medium text-secondary-foreground"
        >
          {key}
        </kbd>
      ))}
    </span>
  );
}

export function ShortcutsSheet() {
  const open = useOverlay() === "shortcuts";
  const mod = useModKey();

  // "?" opens this sheet from anywhere, except while typing in a field.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "?" && !isTyping(event) && !event.metaKey && !event.ctrlKey) {
        event.preventDefault();
        openOverlay("shortcuts");
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const groups: { title: string; items: [string, string[]][] }[] = [
    {
      title: "Anywhere",
      items: [
        ["Command palette: jump, search orders, run actions", [mod, "K"]],
        ["Show these shortcuts", ["?"]],
      ],
    },
    {
      title: "Orders table",
      items: [
        ["Focus the search box", ["/"]],
        ["Move between orders", ["↑", "↓"]],
        ["Open the selected order", ["Enter"]],
        ["Close the order drawer", ["Esc"]],
      ],
    },
  ];

  return (
    <Dialog open={open} onOpenChange={(next) => !next && closeOverlay()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Keyboard shortcuts</DialogTitle>
          <DialogDescription>Work through orders without reaching for the mouse.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          {groups.map((group) => (
            <section key={group.title} aria-label={group.title}>
              <h3 className="mb-1 text-xs font-medium text-muted-foreground">{group.title}</h3>
              <ul className="divide-y">
                {group.items.map(([label, keys]) => (
                  <li key={label} className="flex items-center justify-between gap-4 py-2 text-sm">
                    {label}
                    <Keys keys={keys} />
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
