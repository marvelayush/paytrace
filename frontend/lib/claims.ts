"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { Tone } from "@/components/status-pill";
import { ApiError, apiFetch } from "@/lib/api";
import type { ReconStatus } from "@/lib/recon";

export type ClaimStatus = "open" | "filed" | "recovered" | "rejected";

export const CLAIM_STATUS_META: Record<ClaimStatus, { label: string; tone: Tone; help: string }> = {
  open: { label: "Open", tone: "attention", help: "Ready to file with the partner" },
  filed: { label: "Filed", tone: "info", help: "Sent to the partner, waiting for an answer" },
  recovered: { label: "Recovered", tone: "settled", help: "The partner paid" },
  rejected: { label: "Rejected", tone: "neutral", help: "The partner disputed it" },
};

export const NEXT_STATUSES: Record<ClaimStatus, ClaimStatus[]> = {
  open: ["filed"],
  filed: ["recovered", "rejected"],
  recovered: [],
  rejected: [],
};

export type ClaimSummary = {
  id: number;
  partner_id: number;
  partner_name: string;
  status: ClaimStatus;
  total_paise: number;
  reference: string | null;
  created_at: string;
  updated_at: string | null;
  item_count: number;
  by_reason: Partial<Record<ReconStatus, { count: number; amount_paise: number }>>;
  oldest_age_days: number | null;
};

export type ClaimItem = {
  order_id: string;
  channel: string;
  order_date: string;
  value_paise: number;
  reason_status: ReconStatus;
  amount_paise: number;
  expected_paise: number;
  received_paise: number;
  diff_paise: number;
  due_date: string | null;
  age_days: number | null;
  current_status: ReconStatus | null;
};

export type ClaimDetail = ClaimSummary & { items: ClaimItem[] };

export function useClaims() {
  return useQuery<ClaimSummary[], ApiError>({ queryKey: ["claims"], queryFn: () => apiFetch<ClaimSummary[]>("/claims") });
}

export function useClaim(claimId: number) {
  return useQuery<ClaimDetail, ApiError>({
    queryKey: ["claims", claimId],
    queryFn: () => apiFetch<ClaimDetail>(`/claims/${claimId}`),
  });
}

export function useChangeClaimStatus(claimId: number) {
  const queryClient = useQueryClient();
  return useMutation<ClaimDetail, ApiError, { status: ClaimStatus; reference?: string }>({
    mutationFn: (body) => apiFetch<ClaimDetail>(`/claims/${claimId}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: (detail) => {
      queryClient.setQueryData(["claims", claimId], detail);
      queryClient.invalidateQueries({ queryKey: ["claims"], exact: true });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}
