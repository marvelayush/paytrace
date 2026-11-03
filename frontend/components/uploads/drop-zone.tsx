"use client";

import { FileSpreadsheet, UploadCloud } from "lucide-react";
import { type DragEvent, useId, useRef, useState } from "react";

import { cn } from "@/lib/utils";

const MAX_MB = 50;
const ACCEPTED = [".csv", ".xlsx"];

/** Checks done in the browser for a quick answer; the API enforces the same limits. */
export function checkFile(file: File): string | null {
  const name = file.name.toLowerCase();
  if (!ACCEPTED.some((extension) => name.endsWith(extension))) return "Upload a .csv or .xlsx file.";
  if (file.size === 0) return "The file is empty.";
  if (file.size > MAX_MB * 1024 * 1024) return `The file is larger than ${MAX_MB} MB.`;
  return null;
}

export function DropZone({
  disabled,
  onFile,
  hint,
}: {
  disabled?: boolean;
  onFile: (file: File) => void;
  hint?: string;
}) {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  function handleDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDragging(false);
    if (disabled) return;
    const file = event.dataTransfer.files[0];
    if (file) onFile(file);
  }

  return (
    <label
      htmlFor={inputId}
      onDragOver={(event) => {
        event.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      className={cn(
        "flex cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed bg-card px-6 py-10 text-center transition-colors",
        "focus-within:ring-3 focus-within:ring-ring/50",
        dragging ? "border-primary bg-sidebar-accent" : "hover:border-foreground/30 hover:bg-accent/40",
        disabled && "pointer-events-none opacity-60",
      )}
    >
      <span className="flex size-10 items-center justify-center rounded-full bg-secondary text-muted-foreground">
        {dragging ? <FileSpreadsheet className="size-5" aria-hidden /> : <UploadCloud className="size-5" aria-hidden />}
      </span>
      <span className="mt-3 text-sm font-medium">
        {dragging ? "Drop to upload" : (
          <>
            Drag a report here, or <span className="text-primary underline underline-offset-4">choose a file</span>
          </>
        )}
      </span>
      <span className="mt-1 text-xs text-muted-foreground">{hint ?? `CSV or Excel (.xlsx), up to ${MAX_MB} MB`}</span>
      <input
        ref={inputRef}
        id={inputId}
        type="file"
        accept={ACCEPTED.join(",")}
        className="sr-only"
        disabled={disabled}
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) onFile(file);
          event.target.value = ""; // allow choosing the same file again
        }}
      />
    </label>
  );
}
