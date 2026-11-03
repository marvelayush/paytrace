"use client";

import { CircleAlert, RefreshCw } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { AppShell } from "@/components/app-shell";
import { BrandMark } from "@/components/brand";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useCurrentUser } from "@/lib/auth";

/**
 * Every signed-in screen lives under this layout. It asks the API who is signed in;
 * when nobody is, it sends the visitor to /login and brings them back afterwards.
 * (The real security check is on the API: this only decides what to render.)
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { data: user, error, isPending, refetch, isRefetching } = useCurrentUser();

  const signedOut = error?.isUnauthorized === true;

  useEffect(() => {
    if (signedOut) {
      const next = pathname === "/" ? "" : `?next=${encodeURIComponent(pathname)}`;
      router.replace(`/login${next}`);
    }
  }, [signedOut, pathname, router]);

  if (user) return <AppShell user={user}>{children}</AppShell>;

  if (error && !signedOut) {
    return (
      <main className="flex min-h-dvh items-center justify-center px-4">
        <div role="alert" className="w-full max-w-sm text-center">
          <span className="mx-auto flex size-10 items-center justify-center rounded-full bg-loss-soft text-loss">
            <CircleAlert className="size-5" aria-hidden />
          </span>
          <h1 className="mt-4 text-base font-semibold">PayTrace is not responding</h1>
          <p className="mt-1.5 text-sm text-muted-foreground">{error.message}</p>
          <Button variant="outline" className="mt-5" onClick={() => refetch()} disabled={isRefetching}>
            <RefreshCw className={isRefetching ? "animate-spin" : undefined} aria-hidden />
            Try again
          </Button>
        </div>
      </main>
    );
  }

  // Loading (or redirecting to login): a calm skeleton of the shell, no layout jump.
  return (
    <div className="min-h-dvh lg:pl-60" aria-busy={isPending || signedOut} aria-label="Loading">
      <aside className="fixed inset-y-0 left-0 hidden w-60 border-r bg-sidebar p-4 lg:block">
        <BrandMark />
        <div className="mt-8 space-y-2">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-4/5" />
          <Skeleton className="h-8 w-3/5" />
        </div>
      </aside>
      <div className="flex h-14 items-center border-b bg-card px-4 lg:hidden">
        <BrandMark />
      </div>
      <div className="mx-auto max-w-7xl space-y-4 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
        <Skeleton className="h-7 w-48" />
        <Skeleton className="h-4 w-72 max-w-full" />
        <Skeleton className="mt-6 h-64 w-full" />
      </div>
    </div>
  );
}
