"use client";

import { ChevronRight, FileCheck2 } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { EmptyState, ErrorState, PageHeader } from "@/components/page-header";
import { StatusPill } from "@/components/status-pill";
import { Skeleton } from "@/components/ui/skeleton";
import { CLAIM_STATUS_META, type ClaimStatus, type ClaimSummary, useClaims } from "@/lib/claims";
import { formatCount, formatINR, formatINRCompact } from "@/lib/format";
import { STATUS_META } from "@/lib/recon";
import { cn } from "@/lib/utils";

const ORDER: ClaimStatus[] = ["open", "filed", "recovered", "rejected"];

function StatusTabs({
  claims,
  active,
  onChange,
}: {
  claims: ClaimSummary[];
  active: ClaimStatus | "all";
  onChange: (status: ClaimStatus | "all") => void;
}) {
  return (
    <div role="tablist" aria-label="Claim status" className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {ORDER.map((status) => {
        const matching = claims.filter((claim) => claim.status === status);
        const total = matching.reduce((sum, claim) => sum + claim.total_paise, 0);
        const selected = active === status;
        return (
          <button
            key={status}
            role="tab"
            type="button"
            aria-selected={selected}
            onClick={() => onChange(selected ? "all" : status)}
            className={cn(
              "rounded-xl border bg-card px-4 py-3 text-left outline-none transition-colors focus-visible:ring-3 focus-visible:ring-ring/50",
              selected ? "border-primary/50 bg-sidebar-accent" : "hover:bg-accent/50",
            )}
          >
            <span className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium">{CLAIM_STATUS_META[status].label}</span>
              <span className="text-xs text-muted-foreground">{formatCount(matching.length)}</span>
            </span>
            <span className={cn("money mt-1 block text-lg font-semibold", status === "open" && total > 0 && "text-loss")}>
              {formatINRCompact(total)}
            </span>
            <span className="block text-xs text-muted-foreground">{CLAIM_STATUS_META[status].help}</span>
          </button>
        );
      })}
    </div>
  );
}

function ClaimRow({ claim }: { claim: ClaimSummary }) {
  const reasons = Object.entries(claim.by_reason).sort((a, b) => (b[1]?.amount_paise ?? 0) - (a[1]?.amount_paise ?? 0));
  return (
    <li>
      <Link
        href={`/claims/${claim.id}`}
        className="flex flex-col gap-3 px-4 py-4 outline-none hover:bg-accent/40 focus-visible:bg-sidebar-accent sm:flex-row sm:items-center sm:gap-6"
      >
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold">{claim.partner_name}</span>
            <StatusPill {...CLAIM_STATUS_META[claim.status]} />
            <span className="text-xs text-muted-foreground">
              Claim #{claim.id}
              {claim.reference && ` · ref ${claim.reference}`}
            </span>
          </div>
          <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="By reason">
            {reasons.map(([reason, info]) => (
              <li key={reason} className="rounded-md bg-secondary px-2 py-0.5 text-xs">
                {STATUS_META[reason as keyof typeof STATUS_META].label} · {info?.count} ·{" "}
                <span className="money">{formatINR(info?.amount_paise ?? 0)}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="flex items-center justify-between gap-6 sm:justify-end">
          <div className="text-left sm:text-right">
            <p className={cn("money text-base font-semibold", claim.status === "open" && "text-loss")}>{formatINR(claim.total_paise)}</p>
            <p className="text-xs text-muted-foreground">
              {formatCount(claim.item_count)} orders
              {claim.oldest_age_days ? ` · oldest ${claim.oldest_age_days} d overdue` : ""}
            </p>
          </div>
          <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden />
        </div>
      </Link>
    </li>
  );
}

export function ClaimsView() {
  const claims = useClaims();
  const [active, setActive] = useState<ClaimStatus | "all">("all");
  const visible = useMemo(
    () => (claims.data ?? []).filter((claim) => active === "all" || claim.status === active),
    [claims.data, active],
  );

  return (
    <>
      <PageHeader
        title="Claims"
        description="Short, late and overcharged amounts, grouped by the partner who owes them, with evidence ready to send."
      />
      {claims.isPending ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {ORDER.map((status) => (
              <Skeleton key={status} className="h-24 rounded-xl" />
            ))}
          </div>
          <Skeleton className="h-64 w-full rounded-xl" />
        </div>
      ) : claims.error ? (
        <ErrorState title="Couldn't load claims" message={claims.error.message} onRetry={() => claims.refetch()} />
      ) : claims.data.length === 0 ? (
        <EmptyState icon={FileCheck2} title="No claims">
          Claims open automatically when reconciliation finds orders that were short paid, unpaid past due, overcharged on
          freight or returned but never received.
        </EmptyState>
      ) : (
        <div className="space-y-6">
          <StatusTabs claims={claims.data} active={active} onChange={setActive} />
          {visible.length === 0 ? (
            <p className="rounded-xl border border-dashed bg-card px-4 py-8 text-center text-sm text-muted-foreground">
              No {active === "all" ? "" : CLAIM_STATUS_META[active].label.toLowerCase()} claims.
            </p>
          ) : (
            <ul className="divide-y overflow-hidden rounded-xl border bg-card">
              {visible.map((claim) => (
                <ClaimRow key={claim.id} claim={claim} />
              ))}
            </ul>
          )}
        </div>
      )}
    </>
  );
}
