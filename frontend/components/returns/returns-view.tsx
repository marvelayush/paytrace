"use client";

import { CircleAlert, LoaderCircle, PackageCheck, PackageOpen, Search, Upload, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { EmptyState, ErrorState, PageHeader } from "@/components/page-header";
import { StatusPill } from "@/components/status-pill";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { canEdit, useCurrentUser } from "@/lib/auth";
import { formatCount, formatDate, formatINR, formatINRCompact, plural } from "@/lib/format";
import {
  RETURN_AGE_BUCKETS,
  type ReturnAgeBucket,
  type ReturnFilters,
  type ReturnRow,
  type ReturnsPage,
  SCAN_STATUS_META,
  SCAN_STATUS_ORDER,
  type ScanStatus,
  useMarkReturnReceived,
  useReturns,
} from "@/lib/returns";
import { cn } from "@/lib/utils";

const PAGE = 100;
const CHIP =
  "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full border px-3 text-sm whitespace-nowrap transition-colors duration-150 outline-none focus-visible:ring-3 focus-visible:ring-ring/50";
const CHIP_ON = "border-primary/40 bg-sidebar-accent font-medium text-sidebar-accent-foreground";
const CHIP_OFF = "bg-card text-foreground hover:border-input hover:bg-accent";
const DOT: Record<ScanStatus, string> = { overdue: "bg-loss", waiting: "bg-attention", received: "bg-settled" };

function SummaryCards({ data, active, onChange }: { data: ReturnsPage; active?: ScanStatus; onChange: (status?: ScanStatus) => void }) {
  return (
    <div role="group" aria-label="Filter by scan status" className="grid gap-3 sm:grid-cols-3">
      {SCAN_STATUS_ORDER.map((status) => {
        const selected = active === status;
        const summary = data.summary[status];
        return (
          <button
            key={status}
            type="button"
            aria-pressed={selected}
            onClick={() => onChange(selected ? undefined : status)}
            className={cn(
              "rounded-xl border bg-card px-4 py-3 text-left outline-none transition-colors focus-visible:ring-3 focus-visible:ring-ring/50",
              selected ? "border-primary/50 bg-sidebar-accent" : "hover:bg-accent/50",
            )}
          >
            <span className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-2 text-sm font-medium">
                <span aria-hidden className={cn("size-2 rounded-full", DOT[status])} />
                {SCAN_STATUS_META[status].label}
              </span>
              <span className="money text-xs text-muted-foreground">
                {formatCount(summary.orders)} {plural(summary.orders, "return")}
              </span>
            </span>
            <span className={cn("money mt-1 block text-lg font-semibold", status === "overdue" && summary.orders > 0 && "text-loss")}>
              {formatINRCompact(summary.value_paise)}
            </span>
            <span className="block text-xs text-muted-foreground">
              {status === "overdue" ? "Goods value at risk, claimed from the courier" : SCAN_STATUS_META[status].help}
            </span>
          </button>
        );
      })}
    </div>
  );
}

function ChipGroup<T extends string>({
  label,
  options,
  active,
  onChange,
}: {
  label: string;
  options: { value: T; label: string; count: number }[];
  active?: T;
  onChange: (value?: T) => void;
}) {
  return (
    <div role="group" aria-label={label} className="relative -mx-4 flex items-center gap-1.5 overflow-x-auto px-4 pb-1 [scrollbar-width:none] sm:mx-0 sm:flex-wrap sm:px-0">
      <span className="mr-1 shrink-0 text-xs font-medium text-muted-foreground">{label}</span>
      {options.map((option) => {
        const selected = active === option.value;
        return (
          <button key={option.value} type="button" aria-pressed={selected} onClick={() => onChange(selected ? undefined : option.value)} className={cn(CHIP, selected ? CHIP_ON : CHIP_OFF)}>
            {option.label}
            <span className={cn("money text-xs", selected ? "text-sidebar-accent-foreground/80" : "text-muted-foreground")}>{formatCount(option.count)}</span>
          </button>
        );
      })}
    </div>
  );
}

function MarkReceived({ row }: { row: ReturnRow }) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const mark = useMarkReturnReceived();
  const tooShort = note.trim().length < 3;
  return (
    <>
      <Button
        size="sm"
        variant="outline"
        onClick={() => {
          mark.reset();
          setNote("");
          setOpen(true);
        }}
      >
        Mark received
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Mark {row.order_id} received</DialogTitle>
            <DialogDescription>
              Use this when the parcel is in the warehouse but was never scanned. The order is re-matched at once
              {row.claim_id ? ` and leaves claim #${row.claim_id}` : ""}. This is recorded in the audit log with your name.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor={`note-${row.order_id}`}>Why it counts as received</Label>
            <Textarea
              id={`note-${row.order_id}`}
              value={note}
              maxLength={500}
              rows={3}
              placeholder="e.g. Found in bay 4 without a label; checked against the packing slip"
              onChange={(event) => setNote(event.target.value)}
            />
          </div>
          {mark.error && (
            <Alert variant="destructive" className="border-loss/20 bg-loss-soft">
              <CircleAlert />
              <AlertDescription className="text-loss">{mark.error.message}</AlertDescription>
            </Alert>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)} disabled={mark.isPending}>
              Cancel
            </Button>
            <Button
              disabled={tooShort || mark.isPending}
              onClick={() =>
                mark.mutate(
                  { orderId: row.order_id, note: note.trim() },
                  {
                    onSuccess: () => {
                      setOpen(false);
                      toast.success(`${row.order_id} marked received`);
                    },
                  },
                )
              }
            >
              {mark.isPending && <LoaderCircle className="animate-spin" aria-hidden />}
              Mark received
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function ReceivedNote({ row }: { row: ReturnRow }) {
  if (row.status !== "received") {
    return (
      <span className="text-xs text-muted-foreground">
        {row.status === "overdue" ? "Due" : "Scan due by"} {formatDate(row.due_date)}
      </span>
    );
  }
  if (row.received_how === "manual") {
    return (
      <span className="text-xs text-muted-foreground" title={row.manual_note ?? undefined}>
        Confirmed by {row.marked_by ?? "finance"} · {formatDate(row.received_on)}
        {row.manual_note && <span className="block max-w-64 truncate italic">“{row.manual_note}”</span>}
      </span>
    );
  }
  return <span className="text-xs text-muted-foreground">Scanned {formatDate(row.received_on)}</span>;
}

function OrderLink({ orderId }: { orderId: string }) {
  return (
    <Link
      href={`/orders?q=${encodeURIComponent(orderId)}&open=${encodeURIComponent(orderId)}`}
      className="money font-medium underline-offset-4 outline-none hover:underline focus-visible:underline"
    >
      {orderId}
    </Link>
  );
}

function ReturnsTable({ rows, editable }: { rows: ReturnRow[]; editable: boolean }) {
  return (
    <div className="hidden overflow-x-auto rounded-xl border bg-card md:block">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-card text-xs text-muted-foreground">
          <tr className="border-b">
            <th scope="col" className="px-4 py-2.5 text-left font-medium">Order</th>
            <th scope="col" className="px-3 py-2.5 text-left font-medium">Courier</th>
            <th scope="col" className="px-3 py-2.5 text-left font-medium">Returned</th>
            <th scope="col" className="px-3 py-2.5 text-right font-medium">Days</th>
            <th scope="col" className="px-3 py-2.5 text-left font-medium">Scan</th>
            <th scope="col" className="px-3 py-2.5 text-right font-medium">Value at risk</th>
            {editable && <th scope="col" className="px-4 py-2.5 text-right font-medium"><span className="sr-only">Action</span></th>}
          </tr>
        </thead>
        <tbody className="divide-y">
          {rows.map((row) => (
            <tr key={row.order_id} className={cn("transition-colors hover:bg-accent/40", row.status === "overdue" && "bg-loss-soft/40")}>
              <td className={cn("px-4 py-2.5", row.status === "overdue" && "border-l-2 border-l-loss")}>
                <OrderLink orderId={row.order_id} />
                <span className="block text-xs text-muted-foreground">
                  {row.partner_name} · {row.delivery_status === "rto" ? "RTO" : "Customer return"}
                </span>
              </td>
              <td className="px-3 py-2.5">
                {row.courier_name ?? <span className="text-muted-foreground">Channel&apos;s own</span>}
                {row.awb && <span className="money block text-xs text-muted-foreground">{row.awb}</span>}
              </td>
              <td className="px-3 py-2.5 whitespace-nowrap">{formatDate(row.returned_date)}</td>
              <td className={cn("money px-3 py-2.5 text-right", row.status === "overdue" && "font-medium text-loss")}>{row.days_since_return}</td>
              <td className="px-3 py-2.5">
                <StatusPill {...SCAN_STATUS_META[row.status]} />
                <span className="mt-0.5 block">
                  <ReceivedNote row={row} />
                </span>
              </td>
              <td className="money px-3 py-2.5 text-right">
                {row.at_risk_paise > 0 ? (
                  <span className="font-semibold text-loss">{formatINR(row.at_risk_paise)}</span>
                ) : (
                  <span className="text-muted-foreground">{row.status === "waiting" ? formatINR(row.value_paise) : "—"}</span>
                )}
                {row.claim_id && (
                  <Link href={`/claims/${row.claim_id}`} className="block text-xs text-muted-foreground underline-offset-4 hover:underline">
                    Claim #{row.claim_id}
                  </Link>
                )}
              </td>
              {editable && <td className="px-4 py-2.5 text-right">{row.status !== "received" && <MarkReceived row={row} />}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ReturnCards({ rows, editable }: { rows: ReturnRow[]; editable: boolean }) {
  return (
    <ul className="divide-y overflow-hidden rounded-xl border bg-card md:hidden">
      {rows.map((row) => (
        <li key={row.order_id} className={cn("space-y-2 px-4 py-3", row.status === "overdue" && "border-l-2 border-l-loss bg-loss-soft/40")}>
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <OrderLink orderId={row.order_id} />
              <p className="text-xs text-muted-foreground">
                {row.partner_name} · {row.courier_name ?? "Channel's own"} · returned {formatDate(row.returned_date)}
              </p>
            </div>
            <StatusPill {...SCAN_STATUS_META[row.status]} />
          </div>
          <div className="flex items-end justify-between gap-3">
            <div>
              <ReceivedNote row={row} />
              <p className={cn("text-xs", row.status === "overdue" ? "font-medium text-loss" : "text-muted-foreground")}>
                {row.days_since_return} {plural(row.days_since_return, "day")} since return
              </p>
            </div>
            <div className="text-right">
              {row.at_risk_paise > 0 ? (
                <p className="money font-semibold text-loss">{formatINR(row.at_risk_paise)}</p>
              ) : (
                <p className="money text-sm text-muted-foreground">{row.status === "waiting" ? formatINR(row.value_paise) : "—"}</p>
              )}
              {row.claim_id && (
                <Link href={`/claims/${row.claim_id}`} className="text-xs text-muted-foreground underline-offset-4 hover:underline">
                  Claim #{row.claim_id}
                </Link>
              )}
            </div>
          </div>
          {editable && row.status !== "received" && <MarkReceived row={row} />}
        </li>
      ))}
    </ul>
  );
}

function LoadingState() {
  return (
    <div className="space-y-6" role="status" aria-busy aria-label="Loading returns">
      <div className="grid gap-3 sm:grid-cols-3">
        {SCAN_STATUS_ORDER.map((status) => (
          <div key={status} className="space-y-2 rounded-xl border bg-card px-4 py-3">
            <Skeleton className="h-3.5 w-24" />
            <Skeleton className="h-6 w-20" />
            <Skeleton className="h-3 w-40" />
          </div>
        ))}
      </div>
      <Skeleton className="h-8 w-80 max-w-full rounded-full" />
      <div className="divide-y rounded-xl border bg-card">
        {Array.from({ length: 6 }, (_, index) => (
          <div key={index} className="flex items-center gap-6 px-4 py-3">
            <div className="flex-1 space-y-1.5">
              <Skeleton className="h-4 w-32" />
              <Skeleton className="h-3 w-48" />
            </div>
            <Skeleton className="h-5 w-24 rounded-full" />
            <Skeleton className="h-4 w-20" />
          </div>
        ))}
      </div>
    </div>
  );
}

export function ReturnsView() {
  const { data: user } = useCurrentUser();
  const editable = canEdit(user);
  const [filters, setFilters] = useState<ReturnFilters>({});
  const [search, setSearch] = useState("");
  const [limit, setLimit] = useState(PAGE);
  const returns = useReturns(filters, limit);
  const data = returns.data;
  const filtered = Boolean(filters.status || filters.courier || filters.age || filters.q);

  function update(patch: Partial<ReturnFilters>) {
    setFilters((current) => ({ ...current, ...patch }));
    setLimit(PAGE);
  }

  return (
    <>
      <PageHeader
        title="Returns"
        description={
          data
            ? `Every order the courier marked returned or RTO, checked against warehouse receipt scans. A return not scanned within ${data.window_days} days is claimed. As of ${formatDate(data.as_of)}.`
            : "Every order the courier marked returned or RTO, checked against warehouse receipt scans."
        }
      />
      {returns.isPending ? (
        <LoadingState />
      ) : returns.error ? (
        <ErrorState title="Couldn't load returns" message={returns.error.message} onRetry={() => returns.refetch()} />
      ) : data && data.summary.overdue.orders + data.summary.waiting.orders + data.summary.received.orders === 0 ? (
        <EmptyState
          icon={PackageOpen}
          title="No returns yet"
          action={
            editable ? (
              <Button asChild size="sm">
                <Link href="/uploads">
                  <Upload aria-hidden />
                  Upload partner reports
                </Link>
              </Button>
            ) : undefined
          }
        >
          Returns appear when an orders report marks an order returned or RTO. Warehouse receipt scans then mark them received.
        </EmptyState>
      ) : data ? (
        <div className="space-y-5">
          <SummaryCards data={data} active={filters.status} onChange={(status) => update({ status })} />
          <div className="space-y-2.5">
            <form
              className="flex gap-2"
              role="search"
              onSubmit={(event) => {
                event.preventDefault();
                update({ q: search.trim() || undefined });
              }}
            >
              <div className="relative w-full max-w-xs">
                <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
                <Input
                  aria-label="Search order ID or AWB"
                  placeholder="Search order ID or AWB"
                  value={search}
                  onChange={(event) => {
                    setSearch(event.target.value);
                    if (!event.target.value) update({ q: undefined });
                  }}
                  className="pl-8"
                />
              </div>
              <Button type="submit" variant="outline">
                Search
              </Button>
            </form>
            <ChipGroup
              label="Courier"
              active={filters.courier}
              onChange={(courier) => update({ courier })}
              options={data.couriers.map((courier) => ({ value: courier.key, label: courier.name, count: data.counts.courier[courier.key] ?? 0 }))}
            />
            <ChipGroup<ReturnAgeBucket>
              label="Days since return"
              active={filters.age}
              onChange={(age) => update({ age })}
              options={RETURN_AGE_BUCKETS.map((bucket) => ({ value: bucket, label: `${bucket} d`, count: data.counts.age[bucket] ?? 0 }))}
            />
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <p aria-live="polite">
              <span className="money font-medium">{formatCount(data.total)}</span> {plural(data.total, "return")}
              {data.at_risk_paise > 0 && (
                <>
                  {" · "}
                  <span className="money font-medium text-loss">{formatINR(data.at_risk_paise)}</span> at risk
                </>
              )}
              {returns.isFetching && <LoaderCircle className="ml-2 inline size-3.5 animate-spin text-muted-foreground" aria-label="Updating" />}
            </p>
            {filtered && (
              <button
                type="button"
                onClick={() => {
                  setFilters({});
                  setSearch("");
                  setLimit(PAGE);
                }}
                className="inline-flex items-center gap-1 rounded-md text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                <X className="size-3.5" aria-hidden />
                Clear filters
              </button>
            )}
          </div>
          {data.rows.length === 0 ? (
            <EmptyState icon={PackageCheck} title="No returns match these filters">
              Try another courier or age, or clear the filters.
            </EmptyState>
          ) : (
            <>
              <ReturnsTable rows={data.rows} editable={editable} />
              <ReturnCards rows={data.rows} editable={editable} />
              {data.rows.length < data.total && limit >= 500 && (
                <p className="text-center text-sm text-muted-foreground">
                  Showing the first 500 of {formatCount(data.total)}. Narrow the list with the filters above.
                </p>
              )}
              {data.rows.length < data.total && limit < 500 && (
                <div className="flex justify-center">
                  <Button variant="outline" disabled={returns.isFetching} onClick={() => setLimit((current) => Math.min(current + PAGE, 500))}>
                    {returns.isFetching && <LoaderCircle className="animate-spin" aria-hidden />}
                    Show more ({formatCount(data.total - data.rows.length)} left)
                  </Button>
                </div>
              )}
            </>
          )}
        </div>
      ) : null}
    </>
  );
}
