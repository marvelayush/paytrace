"use client";

import { FileText } from "lucide-react";
import { m } from "motion/react";

import { EASE_OUT } from "@/components/motion";
import { ErrorState } from "@/components/page-header";
import { StatusPill } from "@/components/status-pill";
import { Badge } from "@/components/ui/badge";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDate, formatDateTime, formatINR, formatSignedINR, formatWeight } from "@/lib/format";
import { explainStatus, FLAGGED, type OrderDetail, STATUS_META, useOrderDetail } from "@/lib/recon";
import { useIsMobile } from "@/lib/use-media-query";
import { cn } from "@/lib/utils";

const DELIVERY_LABEL: Record<string, string> = {
  delivered: "Delivered",
  returned: "Returned",
  rto: "RTO",
  in_transit: "In transit",
  cancelled: "Cancelled",
};

const SHORTFALL_PAISE = -1000; // the brief's ₹10 tolerance

// ---------- waterfall ----------

type Step = {
  label: string;
  detail?: string;
  kind: "total" | "deduct" | "tax" | "received" | "difference";
  from: number;
  to: number;
  amount: number;
};

/**
 * Order value, minus each rate-card deduction, gives what the partner should pay (expected). TCS and TDS are
 * shown in sequence but, being tax credits, never lower the expected amount (the engine's rule, A6).
 */
function buildSteps(detail: OrderDetail): Step[] {
  const { breakdown, expected_paise, received_paise, diff_paise } = detail.result;
  const fees = breakdown.fixed_fee + breakdown.gateway_fee + breakdown.cod_fee;
  const feeParts = [
    breakdown.fixed_fee ? `fixed ${formatINR(breakdown.fixed_fee)}` : null,
    breakdown.gateway_fee ? `gateway ${formatINR(breakdown.gateway_fee)}` : null,
    breakdown.cod_fee ? `COD ${formatINR(breakdown.cod_fee)}` : null,
  ];
  const freight = breakdown.forward_freight + breakdown.return_freight;
  const freightParts = [
    breakdown.forward_freight ? `forward ${formatINR(breakdown.forward_freight)}` : null,
    breakdown.return_freight ? `return ${formatINR(breakdown.return_freight)}` : null,
    breakdown.chargeable_weight_g ? formatWeight(breakdown.chargeable_weight_g) : null,
  ];

  const steps: Step[] = [{ label: "Order value", kind: "total", from: 0, to: breakdown.value, amount: breakdown.value }];
  let running = breakdown.value;
  const deductions: [string, number, (string | null)[]][] = [
    ["Commission", breakdown.commission, []],
    ["Fees", fees, feeParts],
    ["Freight", freight, freightParts],
  ];
  for (const [label, amount, parts] of deductions) {
    if (!amount) continue;
    const detailText = parts.filter(Boolean).join(" · ");
    steps.push({ label, detail: detailText || undefined, kind: "deduct", from: running, to: running - amount, amount: -amount });
    running -= amount;
  }
  let taxEdge = running;
  const taxes: [string, number][] = [
    ["GST TCS", breakdown.tcs],
    ["Income-tax TDS", breakdown.tds],
  ];
  for (const [label, amount] of taxes) {
    if (!amount) continue;
    steps.push({ label, detail: "tax credit, not deducted", kind: "tax", from: taxEdge, to: taxEdge - amount, amount: -amount });
    taxEdge -= amount;
  }
  steps.push({ label: "Expected", detail: "from the rate card", kind: "total", from: 0, to: expected_paise, amount: expected_paise });
  steps.push({ label: "Received", detail: "from partner files", kind: "received", from: 0, to: received_paise, amount: received_paise });
  steps.push({ label: "Difference", kind: "difference", from: expected_paise, to: received_paise, amount: diff_paise });
  return steps;
}

const BAR_TONE: Record<Step["kind"], string> = {
  total: "bg-foreground/70",
  deduct: "bg-muted-foreground/40",
  tax: "border border-dashed border-muted-foreground/60 bg-transparent",
  received: "bg-primary",
  difference: "bg-loss",
};

function amountText(step: Step): string {
  if (step.kind === "deduct" || step.kind === "tax") return `− ${formatINR(-step.amount)}`;
  if (step.kind === "difference") return formatSignedINR(step.amount);
  return formatINR(step.amount);
}

/** "Where every rupee went": from order value to what should arrive, then what did. */
function Waterfall({ detail }: { detail: OrderDetail }) {
  const steps = buildSteps(detail);
  const low = Math.min(0, ...steps.flatMap((step) => [step.from, step.to]));
  const high = Math.max(1, ...steps.flatMap((step) => [step.from, step.to]));
  const range = high - low;
  const shortfall = detail.result.diff_paise < SHORTFALL_PAISE;
  const { evidence_summary: received, charged_freight_paise, tcs_paise, tds_paise } = detail.result;
  const nothingReceived = !received.settled_net && !received.cod_remitted && !charged_freight_paise;

  return (
    <section aria-labelledby="breakdown-heading" className="space-y-3">
      <h3 id="breakdown-heading" className="text-sm font-semibold">
        Where every rupee went
      </h3>
      <ol className="rounded-lg border px-3 py-2">
        {steps.map((step, index) => {
          const left = ((Math.min(step.from, step.to) - low) / range) * 100;
          const width = (Math.abs(step.to - step.from) / range) * 100;
          const isDifference = step.kind === "difference";
          const strong = step.kind === "total" || step.kind === "received" || isDifference;
          return (
            <li
              key={step.label}
              className={cn(
                "grid grid-cols-[minmax(0,8.5rem)_minmax(0,1fr)_auto] items-center gap-3 py-1.5",
                (step.label === "Expected" || isDifference) && "mt-1 border-t pt-2.5",
              )}
            >
              <div className="min-w-0">
                <p className={cn("truncate text-sm", strong ? "font-medium" : "text-muted-foreground")}>{step.label}</p>
                {step.detail && <p className="money truncate text-[11px] text-muted-foreground">{step.detail}</p>}
              </div>
              <div className="relative h-5" aria-hidden>
                <span className="absolute inset-y-0 w-px bg-border" style={{ left: `${((0 - low) / range) * 100}%` }} />
                <m.span
                  className={cn(
                    "absolute inset-y-0.5 origin-left rounded-[3px]",
                    isDifference && !shortfall ? "bg-muted-foreground/40" : BAR_TONE[step.kind],
                  )}
                  style={{ left: `${left}%`, width: `max(${width}%, 2px)` }}
                  initial={{ scaleX: 0, opacity: 0 }}
                  animate={{ scaleX: 1, opacity: 1 }}
                  transition={{ duration: 0.22, delay: index * 0.035, ease: EASE_OUT }}
                />
              </div>
              <p
                className={cn(
                  "money text-right text-sm whitespace-nowrap",
                  step.kind === "tax" && "text-muted-foreground",
                  strong && "font-medium",
                  isDifference && "font-semibold",
                  isDifference && shortfall && "text-loss",
                )}
              >
                {amountText(step)}
              </p>
            </li>
          );
        })}
      </ol>

      <dl className="rounded-lg bg-secondary/60 px-3 py-2 text-xs text-muted-foreground">
        <dt className="mb-1 font-medium text-foreground">Received is made of</dt>
        <dd className="money flex flex-wrap gap-x-3 gap-y-0.5">
          {received.settled_net !== 0 && <span>settlements {formatSignedINR(received.settled_net)}</span>}
          {received.cod_remitted > 0 && <span>COD remitted +{formatINR(received.cod_remitted)}</span>}
          {charged_freight_paise > 0 && <span>freight charged −{formatINR(charged_freight_paise)}</span>}
          {received.charged_cod_fee > 0 && <span>COD fee charged −{formatINR(received.charged_cod_fee)}</span>}
          {tcs_paise + tds_paise > 0 && <span>TCS + TDS added back +{formatINR(tcs_paise + tds_paise)}</span>}
          {nothingReceived && <span>nothing reported by any partner yet</span>}
        </dd>
      </dl>

      {(tcs_paise > 0 || tds_paise > 0) && (
        <p className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <Badge variant="secondary" className="font-normal">Tax, not leakage</Badge>
          GST TCS {formatINR(tcs_paise)} and income-tax TDS {formatINR(tds_paise)} were withheld at source. They are claimable credits, so they
          never count as a difference.
        </p>
      )}
    </section>
  );
}

// ---------- evidence and facts ----------

function SourceTag({ file, row }: { file: string; row: number }) {
  return (
    <span className="inline-flex max-w-full items-center gap-1 text-xs text-muted-foreground">
      <FileText className="size-3 shrink-0" aria-hidden />
      <span className="truncate">{file}</span>
      <span className="shrink-0">· row {row}</span>
    </span>
  );
}

function Evidence({ detail }: { detail: OrderDetail }) {
  const { settlement_lines, cod_remittances, freight_lines, warehouse_receipts } = detail.evidence;
  const nothing = !settlement_lines.length && !cod_remittances.length && !freight_lines.length && !warehouse_receipts.length;
  return (
    <section aria-labelledby="evidence-heading" className="space-y-3">
      <h3 id="evidence-heading" className="text-sm font-semibold">
        Evidence from partner files
      </h3>
      {nothing && (
        <p className="rounded-lg border border-dashed px-3 py-4 text-sm text-muted-foreground">
          No partner has reported a payment, charge or return scan for this order in any uploaded file.
        </p>
      )}
      <ul className="space-y-2">
        {settlement_lines.map((line) => (
          <li key={`s-${line.file}-${line.row}`} className="rounded-lg border p-3">
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-sm font-medium">{line.partner} settlement</span>
              <span className={cn("money text-sm font-medium", line.net_paise < 0 && "text-loss")}>{formatSignedINR(line.net_paise)}</span>
            </div>
            <p className="money mt-1 text-xs text-muted-foreground">
              {formatDate(line.date)} · gross {formatINR(line.gross_paise)} · commission {formatINR(line.commission_paise)} · fees{" "}
              {formatINR(line.fees_paise)}
              {line.tcs_paise || line.tds_paise ? ` · TCS ${formatINR(line.tcs_paise)} · TDS ${formatINR(line.tds_paise)}` : ""}
              {line.reference ? ` · ref ${line.reference}` : ""}
            </p>
            <SourceTag file={line.file} row={line.row} />
          </li>
        ))}
        {cod_remittances.map((line) => (
          <li key={`c-${line.file}-${line.row}`} className="rounded-lg border p-3">
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-sm font-medium">{line.partner} COD remittance</span>
              <span className="money text-sm font-medium">{formatINR(line.amount_paise)}</span>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              {formatDate(line.date)}
              {line.utr ? ` · UTR ${line.utr}` : ""} · matched by {line.matched_by}
            </p>
            <SourceTag file={line.file} row={line.row} />
          </li>
        ))}
        {freight_lines.map((line) => (
          <li key={`f-${line.file}-${line.row}`} className="rounded-lg border p-3">
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-sm font-medium">
                {line.partner} freight · {line.leg === "forward" ? "forward" : "return"}
              </span>
              <span className="money text-sm font-medium">{formatINR(line.freight_paise + line.cod_fee_paise)}</span>
            </div>
            <p className="money mt-1 text-xs text-muted-foreground">
              {line.charged_weight_g ? `billed on ${formatWeight(line.charged_weight_g)}` : "no weight given"} · freight {formatINR(line.freight_paise)}
              {line.cod_fee_paise ? ` · COD fee ${formatINR(line.cod_fee_paise)}` : ""}
              {line.invoice_no ? ` · ${line.invoice_no}` : ""} · matched by {line.matched_by}
            </p>
            <SourceTag file={line.file} row={line.row} />
          </li>
        ))}
        {warehouse_receipts.map((line) => (
          <li key={`w-${line.file}-${line.row}`} className="rounded-lg border p-3">
            <span className="text-sm font-medium">Warehouse return scan</span>
            <p className="mt-1 text-xs text-muted-foreground">Scanned in {formatDateTime(line.received_at)}</p>
            <SourceTag file={line.file} row={line.row} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function Facts({ detail }: { detail: OrderDetail }) {
  const { order } = detail;
  const facts: [string, string][] = [
    ["Channel", order.channel],
    ["Payment", order.payment_mode === "cod" ? "Cash on delivery" : "Prepaid"],
    ["Ordered", formatDate(order.order_date)],
    ["Delivered", formatDate(order.delivered_date)],
    ...(order.returned_date ? ([["Returned", formatDate(order.returned_date)]] as [string, string][]) : []),
    ...(order.courier ? ([["Courier", `${order.courier} · ${order.awb ?? "no AWB"}`]] as [string, string][]) : []),
    ...(order.dead_weight_g
      ? ([["Weight", `${formatWeight(order.dead_weight_g)} dead · ${formatWeight(order.volumetric_weight_g ?? 0)} volumetric`]] as [string, string][])
      : []),
    ["Customer", [order.customer_name, order.customer_phone, order.pincode].filter(Boolean).join(" · ") || "—"],
  ];
  return (
    <section aria-labelledby="facts-heading" className="space-y-2">
      <h3 id="facts-heading" className="text-sm font-semibold">
        Order
      </h3>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
        {facts.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="min-w-0 break-words">{value}</dd>
          </div>
        ))}
      </dl>
      <p className="text-xs text-muted-foreground">Customer details are masked at upload (DPDP Act 2023); the full values are never stored.</p>
    </section>
  );
}

function DrawerSkeleton() {
  return (
    <div className="space-y-6" aria-busy aria-label="Loading order">
      <div className="grid grid-cols-3 gap-2">
        {Array.from({ length: 3 }, (_, index) => (
          <Skeleton key={index} className="h-14 rounded-lg" />
        ))}
      </div>
      <Skeleton className="h-12 w-full rounded-lg" />
      <div className="space-y-2.5">
        <Skeleton className="h-4 w-40" />
        {Array.from({ length: 7 }, (_, index) => (
          <div key={index} className="grid grid-cols-[8.5rem_1fr_5rem] items-center gap-3">
            <Skeleton className="h-3.5 w-24" />
            <Skeleton className="h-4" style={{ width: `${90 - index * 9}%` }} />
            <Skeleton className="ml-auto h-3.5 w-16" />
          </div>
        ))}
      </div>
      <Skeleton className="h-28 w-full rounded-lg" />
    </div>
  );
}

// ---------- drawer ----------

export function OrderDrawer({ orderId, onClose }: { orderId: string | null; onClose: () => void }) {
  const detail = useOrderDetail(orderId);
  const data = detail.data;
  const mobile = useIsMobile();
  const flagged = data ? FLAGGED.includes(data.result.status) : false;

  return (
    <Sheet open={orderId !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent
        side={mobile ? "bottom" : "right"}
        className="gap-0 overflow-y-auto overscroll-contain p-0 data-[side=bottom]:max-h-[92dvh] data-[side=bottom]:rounded-t-2xl data-[side=right]:w-full data-[side=right]:sm:max-w-xl"
      >
        {mobile && <span aria-hidden className="mx-auto mt-2 block h-1 w-10 shrink-0 rounded-full bg-border" />}
        <SheetHeader className="sticky top-0 z-10 border-b bg-popover/95 px-5 py-4 backdrop-blur">
          <div className="flex flex-wrap items-center gap-2 pr-8">
            <SheetTitle className="money text-base">{orderId}</SheetTitle>
            {data && <StatusPill {...STATUS_META[data.result.status]} />}
            {data?.result.overpaid && <StatusPill label="Overpaid" tone="info" />}
          </div>
          <SheetDescription>
            {data
              ? `${data.order.channel} · ${data.order.payment_mode === "cod" ? "COD" : "Prepaid"} · ${DELIVERY_LABEL[data.order.delivery_status] ?? data.order.delivery_status} · ${formatINR(data.order.value_paise)}`
              : "Loading order"}
          </SheetDescription>
        </SheetHeader>

        <div className="space-y-6 px-5 py-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))]">
          {detail.isPending && orderId !== null && <DrawerSkeleton />}
          {detail.error && <ErrorState title="Couldn't load this order" message={detail.error.message} onRetry={() => detail.refetch()} />}
          {data && (
            <>
              <div className="grid grid-cols-3 gap-2">
                {[
                  ["Expected", formatINR(data.result.expected_paise), ""],
                  ["Received", formatINR(data.result.received_paise), ""],
                  ["Difference", formatSignedINR(data.result.diff_paise), data.result.diff_paise < SHORTFALL_PAISE ? "text-loss" : ""],
                ].map(([label, value, tone]) => (
                  <div key={label} className="rounded-lg border px-3 py-2">
                    <p className="text-xs text-muted-foreground">{label}</p>
                    <p className={cn("money text-sm font-semibold sm:text-base", tone)}>{value}</p>
                  </div>
                ))}
              </div>

              <div className={cn("rounded-lg px-3 py-2.5 text-sm", flagged ? "bg-loss-soft text-foreground" : "bg-secondary text-foreground")}>
                {flagged && (
                  <p className="money mb-0.5 font-semibold text-loss">
                    At risk: {formatINR(data.result.at_risk_paise)} · owed by {data.result.partner_name}
                  </p>
                )}
                <p>{explainStatus(data, formatINR, formatDate)}</p>
              </div>

              <Waterfall detail={data} />
              <Evidence detail={data} />
              <Facts detail={data} />
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
