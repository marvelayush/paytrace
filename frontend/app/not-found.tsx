import Link from "next/link";

import { BrandMark } from "@/components/brand";
import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <main className="flex min-h-dvh items-center justify-center px-4">
      <div className="max-w-sm text-center">
        <BrandMark className="mx-auto" />
        <p className="mt-6 text-sm font-medium text-muted-foreground">404</p>
        <h1 className="mt-1 text-lg font-semibold">This page doesn&apos;t exist</h1>
        <p className="mt-1.5 text-sm text-muted-foreground">The link may be old or mistyped.</p>
        <Button asChild variant="outline" className="mt-6">
          <Link href="/">Back to PayTrace</Link>
        </Button>
      </div>
    </main>
  );
}
