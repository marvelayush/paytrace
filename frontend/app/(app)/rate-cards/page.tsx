import type { Metadata } from "next";
import { Suspense } from "react";

import { RateCardsView } from "@/components/rate-cards/rate-cards-view";

export const metadata: Metadata = { title: "Rate cards" };
export const instant = false;

export default function RateCardsPage() {
  return (
    <Suspense>
      <RateCardsView />
    </Suspense>
  );
}
