"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

import { MotionProvider } from "@/components/motion";
import { WakingBanner } from "@/components/waking-banner";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ApiError } from "@/lib/api";
import { useTheme } from "@/lib/theme";

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        // Retry network blips, but never auth or validation errors. apiFetch has already retried a cold start
        // (no connection or 502/503/504) for up to 90 s, so those are not retried again here.
        retry: (failureCount, error) =>
          failureCount < 2 &&
          !(error instanceof ApiError && (error.status === 0 || (error.status >= 400 && error.status < 600))),
      },
    },
  });
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(makeQueryClient);
  const theme = useTheme();
  return (
    <QueryClientProvider client={queryClient}>
      <MotionProvider>
        <TooltipProvider delayDuration={300}>
          {children}
          <WakingBanner />
          <Toaster position="bottom-right" theme={theme} closeButton />
        </TooltipProvider>
      </MotionProvider>
    </QueryClientProvider>
  );
}
