"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

import { MotionProvider } from "@/components/motion";
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
        // Retry network blips, but never auth or validation errors.
        retry: (failureCount, error) =>
          failureCount < 2 && !(error instanceof ApiError && error.status >= 400 && error.status < 500),
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
          <Toaster position="bottom-right" theme={theme} closeButton />
        </TooltipProvider>
      </MotionProvider>
    </QueryClientProvider>
  );
}
