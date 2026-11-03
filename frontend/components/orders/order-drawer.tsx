"use client";

import { FileText } from "lucide-react";

import { ErrorState } from "@/components/page-header";
import { StatusPill } from "@/components/status-pill";
import { Badge } from "@/components/ui/badge";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDate, formatDateTime, formatINR, formatSignedINR, formatWeight } from "@/lib/format";
import { explainStatus, FLAGGED, type OrderDetail, STATUS_META, useOrderDetail } from "@/lib/recon";
import { cn } from "@/lib/utils";

const DELIVERY_LABEL: Record<string, string> = {
  delivered: "Delivered",
  returned: "Returned",
  rto: "RTO",
  in_transit: "In transit",
  cancelled: "Cancelled",
};

function Line({ label, amount, sign, muted, strong }: { label: string; amount: number; sign?: "+" | "−"; muted?: boolean; strong?: boolean }) {
  return (
    <div className={cn("flex items-baseline justify-between gap-4 py-1 text-sm", muted && "text-muted-foreground", strong && "font-semibold")}>
      <dt>{label}</dt>
      <dd className="money whitespace-nowrap">
        {sign && amount !== 0 ? `${sign} ` : ""}
        {formatINR(Math.abs(amount))}
      </dd>
    </div>
  );
}

function Breakdown({ detail }: { detail: OrderDetail }) {
  const { breakdown, evidence_summary: received, charged_freight_paise, tcs_paise, tds_paise } = detail.result;
  const weight = breakdown.chargeable_weight_g ? ` (${formatWeight(breakdown.chargeable_weight_g)})` : "";
  return (
    <section aria-labelledby="breakdown-heading" className="space-y-3">
      <h3 id="breakdown-heading" className="text-sm font-semibold">
        Where every rupee went
      </h3>
      <div className="grid gap-4 sm:grid-cols-2">
        <dl className="rounded-lg border p-3">
          <p className="mb-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">Expected (rate card)</p>
          <Line label="Order value" amount={breakdown.value} />
          {breakdown.commission > 0 && <Line label="Commission" amount={breakdown.commission} sign="−" />}
          {breakdown.fixed_fee > 0 && <Line label="Fixed fee" amount={breakdown.fixed_fee} sign="−" />}
          {breakdown.gateway_fee > 0 && <Line label="Gateway fee" amount={breakdown.gateway_fee} sign="−" />}
          {breakdown.cod_fee > 0 && <Line label="COD fee" amount={breakdown.cod_fee} sign="−" />}
          {breakdown.forward_freight > 0 && <Line label={`Forward freight${weight}`} amount={breakdown.forward_freight} sign="−" />}
          {breakdown.return_freight > 0 && <Line label="Return freight" amount={breakdown.return_freight} sign="−" />}
          <div className="mt-1 border-t pt-1">
            <Line label="Expected" amount={detail.result.expected_paise} sign={detail.result.expected_paise < 0 ? "−" : undefined} strong />
          </div>
        </dl>
        <dl className="rounded-lg border p-3">
          <p className="mb-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">Received (partner files)</p>
          <Line label="Settlement paid" amount={received.settled_net} sign={received.settled_net < 0 ? "−" : undefined} />
          {tcs_paise > 0 && <Line label="TCS withheld, added back" amount={tcs_paise} sign="+" muted />}
          {tds_paise > 0 && <Line label="TDS withheld, added back" amount={tds_paise} sign="+" muted />}
          {received.cod_remitted > 0 && <Line label="COD remitted" amount={received.cod_remitted} sign="+" />}
          {charged_freight_paise > 0 && <Line label="Freight charged" amount={charged_freight_paise} sign="−" />}
          {received.charged_cod_fee > 0 && <Line label="COD fee charged" amount={received.charged_cod_fee} sign="−" />}
          <div className="mt-1 border-t pt-1">
            <Line label="Received" amount={detail.result.received_paise} sign={detail.result.received_paise < 0 ? "−" : undefined} strong />
          </div>
        </dl>
      </div>
      {(tcs_paise > 0 || tds_paise > 0) && (
        <p className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <Badge variant="secondary" className="font-normal">Tax, not leakage</Badge>
          GST TCS {formatINR(tcs_paise)} and income-tax TDS {formatINR(tds_paise)} were withheld at source. They are claimable credits, so they are added
          back and never count as a difference.
        </p>
      )}
    </section>
  );
}

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

export function OrderDrawer({ orderId, onClose }: { orderId: string | null; onClose: () => void }) {
  const detail = useOrderDetail(orderId);
  const data = detail.data;
  const flagged = data ? FLAGGED.includes(data.result.status) : false;

  return (
    <Sheet open={orderId !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" className="gap-0 overflow-y-auto p-0 data-[side=right]:w-full data-[side=right]:sm:max-w-xl">
        <SheetHeader className="border-b px-5 py-4">
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

        <div className="space-y-6 px-5 py-5">
          {detail.isPending && (
            <div className="space-y-3" aria-busy>
              <Skeleton className="h-20 w-full" />
              <Skeleton className="h-48 w-full" />
              <Skeleton className="h-32 w-full" />
            </div>
          )}
          {detail.error && <ErrorState title="Couldn't load this order" message={detail.error.message} onRetry={() => detail.refetch()} />}
          {data && (
            <>
              <div className="grid grid-cols-3 gap-2">
                {[
                  ["Expected", formatINR(data.result.expected_paise), ""],
                  ["Received", formatINR(data.result.received_paise), ""],
                  ["Difference", formatSignedINR(data.result.diff_paise), data.result.diff_paise < -1000 ? "text-loss" : ""],
                ].map(([label, value, tone]) => (
                  <div key={label} className="rounded-lg border px-3 py-2">
                    <p className="text-xs text-muted-foreground">{label}</p>
                    <p className={cn("money text-sm font-semibold sm:text-base", tone)}>{value}</p>
                  </div>
                ))}
              </div>

              <div
                className={cn(
                  "rounded-lg px-3 py-2.5 text-sm",
                  flagged ? "bg-loss-soft text-foreground" : "bg-secondary text-foreground",
                )}
              >
                {flagged && (
                  <p className="money mb-0.5 font-semibold text-loss">At risk: {formatINR(data.result.at_risk_paise)} · owed by {data.result.partner_name}</p>
                )}
                <p>{explainStatus(data, formatINR, formatDate)}</p>
              </div>

              <Breakdown detail={data} />
              <Evidence detail={data} />
              <Facts detail={data} />
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
