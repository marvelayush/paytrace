import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ClaimDetailView } from "@/components/claims/claim-detail";

export const metadata: Metadata = { title: "Claim" };
export const instant = false;

export default async function ClaimPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const claimId = Number(id);
  if (!Number.isInteger(claimId) || claimId <= 0) notFound();
  return <ClaimDetailView claimId={claimId} />;
}
