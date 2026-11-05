"use client";

import { keepPreviousData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { Tone } from "@/components/status-pill";
import { ApiError, apiFetch } from "@/lib/api";

export type ReconStatus =
  | "settled"
  | "short_paid"
  | "unpaid_past_due"
  | "freight_overcharged"
  | "return_not_received"
  | "pending";

export const FLAGGED: ReconStatus[] = ["short_paid", "unpaid_past_due", "freight_overcharged", "return_not_received"];

export const STATUS_META: Record<ReconStatus, { label: string; tone: Tone; help: string }> = {
  settled: { label: "Settled", tone: "settled", help: "Paid within ₹10 of the expected amount" },
  short_paid: { label: "Short paid", tone: "loss", help: "Received more than ₹10 less than expected" },
  unpaid_past_due: { label: "Unpaid, past due", tone: "loss", help: "Nothing received and the due date has passed" },
  freight_overcharged: { label: "Freight overcharged", tone: "loss", help: "Courier charged more than ₹10 above the weight slab" },
  return_not_received: { label: "Return not received", tone: "loss", help: "Returned by the courier but never scanned in at the warehouse" },
  pending: { label: "Not yet due", tone: "neutral", help: "In transit, or money not due yet: not at risk" },
};

export const AGE_BUCKETS = ["0-15", "16-30", "31-60", "60+"] as const;
export type AgeBucket = (typeof AGE_BUCKETS)[number];

export type OrderRow = {
  order_id: string;
  channel: string;
  partner_id: number;
  partner_name: string;
  order_date: string;
  value_paise: number;
  payment_mode: "cod" | "prepaid";
  delivery_status: string;
  expected_paise: number;
  received_paise: number;
  diff_paise: number;
  at_risk_paise: number;
  status: ReconStatus;
  overpaid: boolean;
  age_days: number | null;
  age_bucket: AgeBucket | null;
};

export type OrdersPage = {
  items: OrderRow[];
  total: number;
  totals: { expected_paise: number; received_paise: number; diff_paise: number; at_risk_paise: number };
  /** Orders per status under the other filters (ignoring the status filter). First page only. */
  status_counts: Partial<Record<ReconStatus, number>> | null;
  offset: number;
  limit: number;
};

export type OrderFilters = {
  partner?: string;
  status?: string;
  age?: string;
  q?: string;
  sort?: string;
};

export type EvidenceSource = { file: string; row: number };

export type OrderDetail = {
  order: {
    order_id: string;
    channel: string;
    courier: string | null;
    awb: string | null;
    order_date: string;
    delivered_date: string | null;
    returned_date: string | null;
    value_paise: number;
    payment_mode: "cod" | "prepaid";
    delivery_status: string;
    dead_weight_g: number | null;
    volumetric_weight_g: number | null;
    customer_name: string | null;
    customer_phone: string | null;
    pincode: string | null;
  };
  result: {
    status: ReconStatus;
    overpaid: boolean;
    partner_id: number;
    partner_name: string;
    expected_paise: number;
    received_paise: number;
    diff_paise: number;
    at_risk_paise: number;
    expected_freight_paise: number;
    charged_freight_paise: number;
    tcs_paise: number;
    tds_paise: number;
    breakdown: {
      value: number;
      commission: number;
      fixed_fee: number;
      gateway_fee: number;
      cod_fee: number;
      forward_freight: number;
      return_freight: number;
      tcs: number;
      tds: number;
      chargeable_weight_g: number;
    };
    evidence_summary: {
      settlement_lines: number;
      cod_lines: number;
      freight_lines: number;
      settled_net: number;
      cod_remitted: number;
      charged_cod_fee: number;
      receipt_date: string | null;
    };
    due_date: string | null;
    age_days: number | null;
    run_id: number;
  };
  evidence: {
    settlement_lines: (EvidenceSource & {
      partner: string;
      date: string | null;
      gross_paise: number;
      commission_paise: number;
      fees_paise: number;
      tcs_paise: number;
      tds_paise: number;
      net_paise: number;
      reference: string | null;
    })[];
    cod_remittances: (EvidenceSource & { partner: string; date: string | null; amount_paise: number; utr: string | null; matched_by: string })[];
    freight_lines: (EvidenceSource & {
      partner: string;
      leg: "forward" | "return";
      invoice_no: string | null;
      charged_weight_g: number | null;
      freight_paise: number;
      cod_fee_paise: number;
      matched_by: string;
    })[];
    warehouse_receipts: (EvidenceSource & { received_at: string })[];
  };
};

export type RunSummary = {
  run_id: number;
  as_of: string;
  order_count: number;
  duration_ms: number;
  stage_ms: Record<string, number>;
  status_counts: Partial<Record<ReconStatus, number>>;
  money_at_risk_paise: number;
  auto_matched_pct: number;
  unmatched_lines: Record<string, number>;
  finished_at: string | null;
};

// Large pages keep deep scrolling through 30,000 orders to a few dozen requests.
const PAGE_SIZE = 500;

function ordersQuery(filters: OrderFilters, offset: number): string {
  const params = new URLSearchParams({ offset: String(offset), limit: String(PAGE_SIZE) });
  if (filters.partner) params.set("partner_id", filters.partner);
  if (filters.status) params.set("status", filters.status);
  if (filters.age) params.set("age_bucket", filters.age);
  if (filters.q) params.set("q", filters.q);
  if (filters.sort) params.set("sort", filters.sort);
  return `/recon/orders?${params}`;
}

export function useOrders(filters: OrderFilters) {
  return useInfiniteQuery<OrdersPage, ApiError>({
    queryKey: ["recon", "orders", filters],
    queryFn: ({ pageParam }) => apiFetch<OrdersPage>(ordersQuery(filters, pageParam as number)),
    initialPageParam: 0,
    getNextPageParam: (last) => (last.offset + last.items.length < last.total ? last.offset + last.items.length : undefined),
    placeholderData: keepPreviousData,
  });
}

export function useOrderDetail(orderId: string | null) {
  return useQuery<OrderDetail, ApiError>({
    queryKey: ["recon", "order", orderId],
    queryFn: () => apiFetch<OrderDetail>(`/recon/orders/${encodeURIComponent(orderId ?? "")}`),
    enabled: orderId !== null,
  });
}

export function useLatestRun() {
  return useQuery<RunSummary | null, ApiError>({
    queryKey: ["recon", "latest-run"],
    queryFn: () => apiFetch<RunSummary | null>("/recon/runs/latest"),
  });
}

export function useRunReconciliation() {
  const queryClient = useQueryClient();
  return useMutation<RunSummary, ApiError>({
    mutationFn: () => apiFetch<RunSummary>("/recon/runs", { method: "POST" }),
    onSuccess: () => {
      for (const key of ["recon", "dashboard", "claims"]) queryClient.invalidateQueries({ queryKey: [key] });
    },
  });
}

/** One sentence saying what is wrong with an order, in the finance team's words. */
export function explainStatus(detail: OrderDetail, format: (paise: number) => string, formatDay: (iso: string | null) => string): string {
  const { result, order } = detail;
  const owedBy = result.partner_name;
  const overdue = result.age_days ? `, ${result.age_days} days past due (due ${formatDay(result.due_date)})` : "";
  switch (result.status) {
    case "unpaid_past_due":
      return order.payment_mode === "cod"
        ? `${owedBy} has not remitted the ${format(order.value_paise)} COD it collected${overdue}.`
        : `${owedBy} has not settled this order${overdue}.`;
    case "short_paid":
      return `${owedBy} paid ${format(-result.diff_paise)} less than the rate card allows${overdue}.`;
    case "freight_overcharged":
      return `${owedBy} charged ${format(result.charged_freight_paise)} freight against ${format(result.expected_freight_paise)} for the parcel's weight slab${overdue}.`;
    case "return_not_received":
      return `${owedBy} marked this order returned on ${formatDay(order.returned_date)} but the warehouse never scanned it in${overdue}.`;
    case "pending":
      return order.delivery_status === "in_transit"
        ? "Still in transit: nothing is due yet."
        : `Not due yet${result.due_date ? `: ${owedBy} has until ${formatDay(result.due_date)}` : ""}.`;
    default:
      return result.overpaid
        ? `Settled, but ${format(result.diff_paise)} more than expected was received. Worth a look before the partner claws it back.`
        : "Paid within ₹10 of the expected amount.";
  }
}
