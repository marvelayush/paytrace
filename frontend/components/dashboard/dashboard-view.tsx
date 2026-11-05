"use client";

import { Gauge, LoaderCircle, RefreshCw, Upload } from "lucide-react";
import { m } from "motion/react";
import Link from "next/link";
import { toast } from "sonner";

import { CountUp } from "@/components/count-up";
import { EASE_OUT } from "@/components/motion";
import { EmptyState, ErrorState, PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { canEdit, useCurrentUser } from "@/lib/auth";
import { type DashboardData, useDashboard } from "@/lib/dashboard";
import { formatCount, formatDate, formatDateTime, formatDuration, formatINR, formatINRCompact, plural } from "@/lib/format";
import { AGE_BUCKETS, FLAGGED, STATUS_META, useRunReconciliation } from "@/lib/recon";
import { cn } from "@/lib/utils";

type Loaded = Extract<DashboardData, { kpis: unknown }>;

const AUTO_MATCH_TARGET = 98;
const formatPercent = (value: number) => `${value.toFixed(1)}%`;

function Kpi({
  label,
  value,
  format,
  detail,
  tone,
  badge,
}: {
  label: string;
  value: number;
  format: (value: number) => string;
  detail: string;
  tone?: "loss";
  badge?: string;
}) {
  return (
    <div className="rounded-xl border bg-card px-4 py-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">{label}</p>
        {badge && (
          <Badge variant="secondary" className="font-normal">
            {badge}
          </Badge>
        )}
      </div>
      <p className={cn("money mt-1.5 text-2xl font-semibold tracking-tight sm:text-3xl", tone === "loss" && "text-loss")}>
        <CountUp value={value} format={format} />
      </p>
      <p className="mt-1 text-xs text-muted-foreground">{detail}</p>
    </div>
  );
}

/** Heat tint for a cell: one hue (loss red), stronger for more money. Text keeps its normal ink. */
function tint(amount: number, max: number): React.CSSProperties | undefined {
  if (!amount || !max) return undefined;
  const strength = 6 + Math.round(34 * Math.sqrt(amount / max)); // square root keeps small cells visible
  return { backgroundColor: `color-mix(in oklch, var(--loss) ${strength}%, var(--card))` };
}

function ordersLink(params: Record<string, string>): string {
  return `/orders?${new URLSearchParams({ ...params, from: "risk" })}`;
}

function Matrix({ data }: { data: Loaded }) {
  const max = Math.max(0, ...data.matrix.flatMap((row) => AGE_BUCKETS.map((bucket) => row.buckets[bucket].at_risk_paise)));
  return (
    <section aria-labelledby="matrix-heading" className="rounded-xl border bg-card">
      <div className="flex flex-col gap-1 border-b px-5 py-4 sm:flex-row sm:items-baseline sm:justify-between">
        <h2 id="matrix-heading" className="text-base font-semibold">
          Who owes what, and for how long
        </h2>
        <p className="text-xs text-muted-foreground">Days since the money became due · click a cell to see its orders</p>
      </div>
      <div className="relative overflow-x-auto">
        <table className="w-full min-w-[40rem] text-sm">
          <thead>
            <tr className="text-xs text-muted-foreground">
              <th scope="col" className="px-5 py-2.5 text-left font-medium">Partner</th>
              {AGE_BUCKETS.map((bucket) => (
                <th key={bucket} scope="col" className="px-2 py-2.5 text-right font-medium">
                  {bucket} days
                </th>
              ))}
              <th scope="col" className="px-5 py-2.5 text-right font-medium">Total at risk</th>
            </tr>
          </thead>
          <tbody>
            {data.matrix.map((row, rowIndex) => (
              <tr key={row.partner_id} className="border-t">
                <th scope="row" className="px-5 py-1.5 text-left font-medium">
                  {row.partner_name}
                </th>
                {AGE_BUCKETS.map((bucket, bucketIndex) => {
                  const cell = row.buckets[bucket];
                  const label = `${row.partner_name}, ${bucket} days overdue: ${formatINR(cell.at_risk_paise)} across ${cell.orders} ${plural(cell.orders, "order")}`;
                  return (
                    <m.td
                      key={bucket}
                      className="p-1"
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      transition={{ duration: 0.22, ease: EASE_OUT, delay: 0.06 + (rowIndex + bucketIndex) * 0.025 }}
                    >
                      {cell.orders ? (
                        <Link
                          href={ordersLink({ partner: String(row.partner_id), age: bucket, status: "flagged" })}
                          prefetch={false}
                          title={label}
                          style={tint(cell.at_risk_paise, max)}
                          className="money block rounded-md px-2 py-2 text-right outline-none transition-shadow duration-150 hover:ring-2 hover:ring-loss/40 focus-visible:ring-3 focus-visible:ring-ring/60"
                        >
                          <span className="sr-only">
                            {row.partner_name}, {bucket} days overdue:{" "}
                          </span>
                          <span className="block font-medium">{formatINRCompact(cell.at_risk_paise)}</span>
                          {/* Not the muted grey: on the heat tint it would fall below AA contrast. */}
                          <span className="block text-xs text-foreground/75">{formatCount(cell.orders)} {plural(cell.orders, "order")}</span>
                        </Link>
                      ) : (
                        <span className="block px-2 py-2 text-right text-muted-foreground/60">
                          <span aria-hidden>—</span>
                          <span className="sr-only">Nothing at risk</span>
                        </span>
                      )}
                    </m.td>
                  );
                })}
                <td className="px-5 py-1.5 text-right">
                  <Link
                    href={ordersLink({ partner: String(row.partner_id), status: "flagged" })}
                    prefetch={false}
                    className="money rounded font-semibold text-loss underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
                  >
                    {formatINR(row.at_risk_paise)}
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t bg-muted/40 text-sm">
              <th scope="row" className="px-5 py-2.5 text-left font-medium">All partners</th>
              {AGE_BUCKETS.map((bucket) => (
                <td key={bucket} className="money px-3 py-2.5 text-right font-medium">
                  {data.bucket_totals[bucket].at_risk_paise ? (
                    formatINRCompact(data.bucket_totals[bucket].at_risk_paise)
                  ) : (
                    <span className="text-muted-foreground/60">—</span>
                  )}
                </td>
              ))}
              <td className="money px-5 py-2.5 text-right font-semibold text-loss">{formatINR(data.kpis.money_at_risk_paise)}</td>
            </tr>
          </tfoot>
        </table>
      </div>
    </section>
  );
}

function Reasons({ data }: { data: Loaded }) {
  const flagged = data.by_status.filter((row) => FLAGGED.includes(row.status));
  const max = Math.max(1, ...flagged.map((row) => row.at_risk_paise));
  return (
    <section aria-labelledby="reasons-heading" className="rounded-xl border bg-card p-5">
      <h2 id="reasons-heading" className="text-base font-semibold">
        Why money is at risk
      </h2>
      <ul className="mt-4 space-y-4">
        {flagged.map((row) => (
          <li key={row.status}>
            <Link
              href={ordersLink({ status: row.status })}
              prefetch={false}
              className="group block rounded-md outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
              title={`${STATUS_META[row.status].label}: ${formatINR(row.at_risk_paise)} across ${row.orders} ${plural(row.orders, "order")}`}
            >
              <span className="flex items-baseline justify-between gap-3 text-sm">
                <span className="group-hover:underline">{STATUS_META[row.status].label}</span>
                <span className="money font-medium">{formatINRCompact(row.at_risk_paise)}</span>
              </span>
              <span className="mt-1.5 block h-2 rounded-full bg-secondary" aria-hidden>
                <m.span
                  className="block h-2 origin-left rounded-full bg-loss/80"
                  style={{ width: `${Math.max(2, (100 * row.at_risk_paise) / max)}%` }}
                  initial={{ scaleX: 0 }}
                  animate={{ scaleX: 1 }}
                  transition={{ duration: 0.25, ease: EASE_OUT, delay: 0.1 }}
                />
              </span>
              <span className="mt-1 block text-xs text-muted-foreground">
                {formatCount(row.orders)} {plural(row.orders, "order")} · {STATUS_META[row.status].help.toLowerCase()}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

function TaxSummary({ data }: { data: Loaded }) {
  return (
    <section aria-labelledby="tax-heading" className="rounded-xl border bg-card p-5">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="tax-heading" className="text-base font-semibold">
          Tax withheld by partners
        </h2>
        <Badge variant="secondary" className="font-normal">Tax, not leakage</Badge>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">GST TCS and income-tax TDS are claimable credits. They are never counted as money at risk.</p>
      <table className="mt-3 w-full text-sm">
        <thead>
          <tr className="text-xs text-muted-foreground">
            <th scope="col" className="py-1.5 text-left font-medium">Partner</th>
            <th scope="col" className="py-1.5 text-right font-medium">TCS</th>
            <th scope="col" className="py-1.5 text-right font-medium">TDS</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {data.tax_by_partner.map((row) => (
            <tr key={row.partner_name}>
              <th scope="row" className="py-1.5 text-left font-normal">{row.partner_name}</th>
              <td className="money py-1.5 text-right">{formatINR(row.tcs_paise)}</td>
              <td className="money py-1.5 text-right">{formatINR(row.tds_paise)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function DashboardSkeleton() {
  return (
    <div role="status" aria-busy aria-label="Loading money at risk">
      <PageHeader title="Money at risk" />
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }, (_, index) => (
          <div key={index} className="space-y-3 rounded-xl border bg-card px-4 py-4">
            <Skeleton className="h-3.5 w-24" />
            <Skeleton className="h-8 w-32" />
            <Skeleton className="h-3 w-full max-w-48" />
          </div>
        ))}
      </div>
      <div className="relative mt-6 overflow-hidden rounded-xl border bg-card">
        <div className="border-b px-5 py-4">
          <Skeleton className="h-4 w-56" />
        </div>
        <div className="space-y-1 overflow-hidden p-3">
          {Array.from({ length: 6 }, (_, index) => (
            <div key={index} className="grid min-w-[36rem] grid-cols-[8rem_repeat(4,1fr)_7rem] items-center gap-2 px-2">
              <Skeleton className="h-3.5 w-24" />
              {Array.from({ length: 4 }, (__, cell) => (
                <Skeleton key={cell} className="h-11 rounded-md" />
              ))}
              <Skeleton className="ml-auto h-3.5 w-20" />
            </div>
          ))}
        </div>
      </div>
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Skeleton className="h-56 rounded-xl" />
        <Skeleton className="h-56 rounded-xl" />
      </div>
    </div>
  );
}

export function DashboardView() {
  const { data: user } = useCurrentUser();
  const dashboard = useDashboard();
  const run = useRunReconciliation();
  const editor = canEdit(user);

  function runReconciliation() {
    const pending = toast.loading("Reconciling every order…");
    run.mutate(undefined, {
      onSuccess: (summary) =>
        toast.success(`Reconciled ${formatCount(summary.order_count)} orders in ${formatDuration(summary.duration_ms)}`, { id: pending }),
      onError: (error) => toast.error(error.message, { id: pending }),
    });
  }

  const runButton = editor && (
    <Button variant="outline" onClick={runReconciliation} disabled={run.isPending}>
      {run.isPending ? <LoaderCircle className="animate-spin" aria-hidden /> : <RefreshCw aria-hidden />}
      Run reconciliation
    </Button>
  );

  if (dashboard.isPending) return <DashboardSkeleton />;
  if (dashboard.error) {
    return (
      <>
        <PageHeader title="Money at risk" />
        <ErrorState title="Couldn't load the dashboard" message={dashboard.error.message} onRetry={() => dashboard.refetch()} />
      </>
    );
  }
  const data = dashboard.data;
  if (!("kpis" in data)) {
    return (
      <>
        <PageHeader title="Money at risk" />
        <EmptyState
          icon={Gauge}
          title="No reconciliation has run yet"
          action={
            editor ? (
              <Button asChild size="sm">
                <Link href="/uploads">
                  <Upload aria-hidden /> Upload partner reports
                </Link>
              </Button>
            ) : undefined
          }
        >
          {editor
            ? "Reconciliation runs as soon as a partner report is processed."
            : "Once the finance team uploads partner reports, what each partner still owes appears here."}
        </EmptyState>
      </>
    );
  }

  const { kpis } = data;
  const autoMatch = kpis.auto_matched_pct ?? 0;
  return (
    <>
      <PageHeader
        title="Money at risk"
        description={`As of ${formatDate(data.run.as_of)} · last reconciled ${formatDateTime(data.run.finished_at)}: ${formatCount(data.run.order_count)} orders in ${formatDuration(data.run.duration_ms)}`}
        actions={runButton}
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi
          label="Money at risk"
          value={kpis.money_at_risk_paise}
          format={formatINRCompact}
          detail={`${formatCount(kpis.orders_at_risk)} ${plural(kpis.orders_at_risk, "order")} short, unpaid, overcharged or lost`}
          tone="loss"
        />
        <Kpi
          label="Auto-matched"
          value={autoMatch}
          format={formatPercent}
          detail={`Orders linked to partner lines without manual work · target ${AUTO_MATCH_TARGET}%`}
          badge={autoMatch >= AUTO_MATCH_TARGET ? "On target" : "Below target"}
        />
        <Kpi
          label="Open claims"
          value={kpis.open_claims.total_paise}
          format={formatINRCompact}
          detail={`${formatCount(kpis.open_claims.claims)} ready to file · ${formatINRCompact(kpis.filed_claims.total_paise)} filed · ${formatINRCompact(kpis.recovered_claims.total_paise)} recovered`}
        />
        <Kpi
          label="TCS + TDS withheld"
          value={kpis.tcs_paise + kpis.tds_paise}
          format={formatINRCompact}
          detail={`TCS ${formatINRCompact(kpis.tcs_paise)} · TDS ${formatINRCompact(kpis.tds_paise)} · claimable, not lost`}
          badge="Tax, not leakage"
        />
      </div>

      <div className="mt-6">
        {data.matrix.length ? (
          <Matrix data={data} />
        ) : (
          <EmptyState icon={Gauge} title="Nothing at risk">
            Every order that is due has been paid correctly.
          </EmptyState>
        )}
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Reasons data={data} />
        <TaxSummary data={data} />
      </div>
    </>
  );
}
