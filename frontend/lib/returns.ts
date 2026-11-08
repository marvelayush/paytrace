"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { Tone } from "@/components/status-pill";
import { ApiError, apiFetch } from "@/lib/api";

export type ScanStatus = "overdue" | "waiting" | "received";

export const SCAN_STATUS_ORDER: ScanStatus[] = ["overdue", "waiting", "received"];

export const SCAN_STATUS_META: Record<ScanStatus, { label: string; tone: Tone; help: string }> = {
  overdue: { label: "Not received", tone: "loss", help: "No warehouse scan and the receipt window has passed" },
  waiting: { label: "Waiting", tone: "attention", help: "No scan yet, still inside the receipt window" },
  received: { label: "Received", tone: "settled", help: "Scanned in at the warehouse (or confirmed by hand)" },
};

export const RETURN_AGE_BUCKETS = ["0-7", "8-15", "16-30", "30+"] as const;
export type ReturnAgeBucket = (typeof RETURN_AGE_BUCKETS)[number];

export type ReturnRow = {
  order_id: string;
  delivery_status: "returned" | "rto";
  partner_name: string;
  courier_key: string;
  courier_name: string | null;
  awb: string | null;
  returned_date: string;
  due_date: string;
  days_since_return: number;
  age_bucket: ReturnAgeBucket;
  status: ScanStatus;
  received_on: string | null;
  received_how: "scan" | "manual" | null;
  manual_note: string | null;
  marked_by: string | null;
  marked_at: string | null;
  value_paise: number;
  at_risk_paise: number;
  claim_id: number | null;
};

export type ReturnsPage = {
  as_of: string;
  window_days: number;
  summary: Record<ScanStatus, { orders: number; value_paise: number }>;
  couriers: { key: string; name: string }[];
  counts: { status: Record<ScanStatus, number>; courier: Record<string, number>; age: Record<ReturnAgeBucket, number> };
  total: number;
  at_risk_paise: number;
  rows: ReturnRow[];
};

export type ReturnFilters = { status?: ScanStatus; courier?: string; age?: ReturnAgeBucket; q?: string };

export function useReturns(filters: ReturnFilters, limit: number) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
  params.set("limit", String(limit));
  return useQuery<ReturnsPage, ApiError>({
    queryKey: ["returns", filters, limit],
    queryFn: () => apiFetch<ReturnsPage>(`/returns?${params}`),
    placeholderData: keepPreviousData,
  });
}

export function useMarkReturnReceived() {
  const queryClient = useQueryClient();
  return useMutation<{ order_id: string; received_on: string }, ApiError, { orderId: string; note: string }>({
    mutationFn: ({ orderId, note }) =>
      apiFetch(`/returns/${encodeURIComponent(orderId)}/manual-receipt`, { method: "POST", body: JSON.stringify({ note }) }),
    onSuccess: () => {
      // The order was re-matched and claims refreshed: everything that shows it may have changed.
      for (const key of ["returns", "dashboard", "recon", "claims"]) queryClient.invalidateQueries({ queryKey: [key] });
    },
  });
}
