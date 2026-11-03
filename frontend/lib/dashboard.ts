"use client";

import { useQuery } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/lib/api";
import type { AgeBucket, ReconStatus } from "@/lib/recon";

type Cell = { orders: number; at_risk_paise: number };

export type DashboardData =
  | { run: null }
  | {
      run: {
        run_id: number;
        as_of: string;
        finished_at: string;
        duration_ms: number;
        order_count: number;
        auto_matched_pct: number | null;
        unmatched_lines: Record<string, number>;
      };
      kpis: {
        money_at_risk_paise: number;
        orders_at_risk: number;
        orders: number;
        auto_matched_pct: number | null;
        open_claims: { claims: number; total_paise: number };
        filed_claims: { claims: number; total_paise: number };
        recovered_claims: { claims: number; total_paise: number };
        tcs_paise: number;
        tds_paise: number;
      };
      matrix: {
        partner_id: number;
        partner_name: string;
        partner_kind: string;
        buckets: Record<AgeBucket, Cell>;
        orders: number;
        at_risk_paise: number;
      }[];
      bucket_totals: Record<AgeBucket, Cell>;
      by_status: { status: ReconStatus; orders: number; at_risk_paise: number; diff_paise: number }[];
      tax_by_partner: { partner_name: string; tcs_paise: number; tds_paise: number }[];
    };

export function useDashboard() {
  return useQuery<DashboardData, ApiError>({ queryKey: ["dashboard"], queryFn: () => apiFetch<DashboardData>("/dashboard") });
}
