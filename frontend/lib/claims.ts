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

export function useClaims({ enabled = true }: { enabled?: boolean } = {}) {
  return useQuery<ClaimSummary[], ApiError>({ queryKey: ["claims"], queryFn: () => apiFetch<ClaimSummary[]>("/claims"), enabled });
}

export function useClaim(claimId: number) {
  return useQuery<ClaimDetail, ApiError>({
    queryKey: ["claims", claimId],
    queryFn: () => apiFetch<ClaimDetail>(`/claims/${claimId}`),
  });
}

type StatusChange = { status: ClaimStatus; reference?: string };
type Snapshot = { detail?: ClaimDetail; list?: ClaimSummary[] };

/**
 * Optimistic: the new status shows at once in the detail and the list. If the API refuses
 * (e.g. someone else already moved the claim), both are put back and the error is shown.
 */
export function useChangeClaimStatus(claimId: number) {
  const queryClient = useQueryClient();
  return useMutation<ClaimDetail, ApiError, StatusChange, Snapshot>({
    mutationFn: (body) => apiFetch<ClaimDetail>(`/claims/${claimId}`, { method: "PATCH", body: JSON.stringify(body) }),
    onMutate: async ({ status, reference }) => {
      await queryClient.cancelQueries({ queryKey: ["claims"] });
      const snapshot: Snapshot = {
        detail: queryClient.getQueryData<ClaimDetail>(["claims", claimId]),
        list: queryClient.getQueryData<ClaimSummary[]>(["claims"]),
      };
      const patch = (claim: ClaimSummary) => ({
        ...claim,
        status,
        reference: status === "filed" ? reference || claim.reference : claim.reference,
        updated_at: new Date().toISOString(),
      });
      if (snapshot.detail) queryClient.setQueryData<ClaimDetail>(["claims", claimId], { ...snapshot.detail, ...patch(snapshot.detail) });
      if (snapshot.list) {
        queryClient.setQueryData<ClaimSummary[]>(
          ["claims"],
          snapshot.list.map((claim) => (claim.id === claimId ? patch(claim) : claim)),
        );
      }
      return snapshot;
    },
    onError: (_error, _body, snapshot) => {
      if (snapshot?.detail) queryClient.setQueryData(["claims", claimId], snapshot.detail);
      if (snapshot?.list) queryClient.setQueryData(["claims"], snapshot.list);
    },
    onSuccess: (detail) => queryClient.setQueryData(["claims", claimId], detail),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["claims"], exact: true });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}
