import { Gauge } from "lucide-react";
import type { Metadata } from "next";

import { EmptyState, PageHeader } from "@/components/page-header";

export const metadata: Metadata = { title: "Money at risk" };

// Signed-in pages render only after the browser confirms the session (see AuthGate),
// so they opt out of instant-navigation prerender validation.
export const instant = false;

// Milestone 8 replaces this with the partner × age money-at-risk matrix.
// Until a reconciliation has run there is genuinely nothing to show, so the honest state is empty.
export default function MoneyAtRiskPage() {
  return (
    <>
      <PageHeader
        title="Money at risk"
        description="Amounts not yet received or short-paid, by partner and by how long they have been due."
      />
      <EmptyState icon={Gauge} title="No reconciliation has run yet">
        After partner reports are uploaded and matched, this page shows what each partner still owes and how
        overdue it is.
      </EmptyState>
    </>
  );
}
