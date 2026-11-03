"use client";

import { CircleAlert, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";

export default function ErrorPage({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main className="flex min-h-dvh items-center justify-center px-4">
      <div role="alert" className="max-w-sm text-center">
        <span className="mx-auto flex size-10 items-center justify-center rounded-full bg-loss-soft text-loss">
          <CircleAlert className="size-5" aria-hidden />
        </span>
        <h1 className="mt-4 text-base font-semibold">Something went wrong</h1>
        <p className="mt-1.5 text-sm text-muted-foreground">
          The page hit an unexpected error. Your data is safe; try loading it again.
        </p>
        <Button variant="outline" className="mt-5" onClick={reset}>
          <RefreshCw aria-hidden />
          Try again
        </Button>
      </div>
    </main>
  );
}
