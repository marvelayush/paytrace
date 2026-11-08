"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/lib/api";
import type { ReconStatus } from "@/lib/recon";

export type QueueStatus = "open" | "accepted" | "rejected";

export type QueueCounts = {
  open: number;
  accepted: number;
  rejected: number;
  open_value_paise: number;
  high_confidence: number;
  ai_pending: number;
  bulk_accept_min_confidence: number;
};

export type Candidate = {
  order_id: string;
  rule_score: number;
  amount_diff_paise: number;
  due_date: string | null;
  days_from_due: number;
  awb_match: boolean;
  ai_pick?: boolean;
  partner_name: string | null;
  order_date: string | null;
  delivered_date: string | null;
  value_paise: number | null;
  expected_net_paise: number | null;
  awb: string | null;
  payment_mode: "cod" | "prepaid" | null;
  recon_status: ReconStatus | null;
};

export type QueueLine = {
  id: number;
  kind: "settlement" | "cod_remittance";
  partner_id: number;
  partner_name: string;
  line_date: string | null;
  gross_paise: number;
  commission_paise: number;
  fees_paise: number;
  tcs_paise: number;
  tds_paise: number;
  amount_paise: number;
  awb: string | null;
  reference: string | null;
  filename: string | null;
  row_number: number;
  status: QueueStatus;
  suggested_order_id: string | null;
  confidence: number | null;
  reason: string | null;
  engine: "rules" | "llm";
  ai_note: string | null;
  candidates: Candidate[];
  resolved_order_id: string | null;
  resolved_by: string | null;
  resolved_at: string | null;
  note: string | null;
};

export type QueueData = { counts: QueueCounts; lines: QueueLine[] };

/** Lines at or above this confidence may be accepted together (still one click by a person). */
export const BULK_MIN = 0.9;

export function useReviewQueue(status: QueueStatus) {
  return useQuery<QueueData, ApiError>({
    queryKey: ["review", status],
    queryFn: () => apiFetch<QueueData>(`/review-queue?status=${status}`),
    // While the AI ranks freshly uploaded lines in the background, check back every few seconds.
    refetchInterval: (query) => ((query.state.data?.counts.ai_pending ?? 0) > 0 ? 4000 : false),
  });
}

export function useReviewCounts({ enabled = true }: { enabled?: boolean } = {}) {
  return useQuery<QueueCounts, ApiError>({
    queryKey: ["review", "summary"],
    queryFn: () => apiFetch<QueueCounts>("/review-queue/summary"),
    enabled,
    staleTime: 30_000,
  });
}

function invalidateAfterDecision(queryClient: ReturnType<typeof useQueryClient>) {
  // Accepting re-matches the order and refreshes claims, so the money views change too.
  for (const key of ["review", "dashboard", "recon", "claims"]) queryClient.invalidateQueries({ queryKey: [key] });
}

export function useAcceptLine() {
  const queryClient = useQueryClient();
  return useMutation<{ order_id: string }, ApiError, { lineId: number; orderId: string; note?: string }>({
    mutationFn: ({ lineId, orderId, note }) =>
      apiFetch(`/review-queue/${lineId}/accept`, { method: "POST", body: JSON.stringify({ order_id: orderId, note: note || null }) }),
    onSuccess: () => invalidateAfterDecision(queryClient),
  });
}

export function useRejectLine() {
  const queryClient = useQueryClient();
  return useMutation<unknown, ApiError, { lineId: number; note?: string }>({
    mutationFn: ({ lineId, note }) => apiFetch(`/review-queue/${lineId}/reject`, { method: "POST", body: JSON.stringify({ note: note || null }) }),
    onSuccess: () => invalidateAfterDecision(queryClient),
  });
}

export type BulkResult = { accepted: { line_id: number; order_id: string }[]; skipped: { line_id: number; reason: string }[] };

export function useBulkAccept() {
  const queryClient = useQueryClient();
  return useMutation<BulkResult, ApiError, number[]>({
    mutationFn: (lineIds) => apiFetch<BulkResult>("/review-queue/bulk-accept", { method: "POST", body: JSON.stringify({ line_ids: lineIds }) }),
    onSuccess: () => invalidateAfterDecision(queryClient),
  });
}

export const KIND_LABEL: Record<QueueLine["kind"], string> = { settlement: "Settlement", cod_remittance: "COD remittance" };
