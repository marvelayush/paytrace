import type { Metadata } from "next";

import { DashboardView } from "@/components/dashboard/dashboard-view";

export const metadata: Metadata = { title: "Money at risk" };

// Signed-in pages render only after the browser confirms the session (see AuthGate),
// so they opt out of instant-navigation prerender validation.
export const instant = false;

export default function MoneyAtRiskPage() {
  return <DashboardView />;
}
