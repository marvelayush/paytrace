"use client";

import { useQueryClient } from "@tanstack/react-query";
import { type ColumnDef, flexRender, getCoreRowModel, type Row, useReactTable } from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ChevronRight, LoaderCircle, Search, SearchX, Upload, X } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { EmptyState, ErrorState, PageHeader } from "@/components/page-header";
import { StatusPill } from "@/components/status-pill";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectSeparator, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import { canEdit, useCurrentUser } from "@/lib/auth";
import { formatCount, formatDate, formatINR, formatINRCompact, formatSignedINR, plural } from "@/lib/format";
import { usePartners } from "@/lib/rate-cards";
import {
  AGE_BUCKETS,
  filtersFromParams,
  FLAGGED,
  type OrderDetail,
  type OrderRow,
  type ReconStatus,
  STATUS_META,
  useOrders,
} from "@/lib/recon";
import { isTyping } from "@/lib/ui-store";
import { useIsMobile } from "@/lib/use-media-query";
import { cn } from "@/lib/utils";

// The drawer's code loads after the table, so it never delays the first screen.
const OrderDrawer = dynamic(() => import("@/components/orders/order-drawer").then((module) => module.OrderDrawer), { ssr: false });

const ALL = "__all__";
const ROW_HEIGHT = 56;
const CARD_HEIGHT = 96;
const GRID = "grid grid-cols-[minmax(11rem,1.4fr)_minmax(9rem,1fr)_repeat(4,minmax(7rem,0.8fr))_minmax(4.5rem,0.5fr)_minmax(8rem,0.9fr)]";
const SHORTFALL_PAISE = -1000; // the brief's ₹10 tolerance: differences beyond it are shown in red

type ColumnMeta = { numeric?: boolean };

const columns: ColumnDef<OrderRow>[] = [
  {
    id: "order",
    header: "Order",
    cell: ({ row }) => (
      <div className="min-w-0">
        <span className="money block truncate font-medium">{row.original.order_id}</span>
        <span className="block truncate text-xs text-muted-foreground">
          {row.original.channel} · {formatDate(row.original.order_date)}
        </span>
      </div>
    ),
  },
  {
    id: "status",
    header: "Status",
    cell: ({ row }) => (
      <div className="flex flex-wrap items-center gap-1">
        <StatusPill {...STATUS_META[row.original.status]} />
        {row.original.overpaid && <StatusPill label="Overpaid" tone="info" />}
      </div>
    ),
  },
  { id: "expected", header: "Expected", meta: { numeric: true }, cell: ({ row }) => formatINR(row.original.expected_paise) },
  { id: "received", header: "Received", meta: { numeric: true }, cell: ({ row }) => formatINR(row.original.received_paise) },
  {
    id: "difference",
    header: "Difference",
    meta: { numeric: true },
    cell: ({ row }) => (
      <span className={cn(row.original.diff_paise < SHORTFALL_PAISE && "font-medium text-loss")}>{formatSignedINR(row.original.diff_paise)}</span>
    ),
  },
  {
    id: "at_risk",
    header: "At risk",
    meta: { numeric: true },
    cell: ({ row }) =>
      row.original.at_risk_paise ? (
        <span className="font-semibold text-loss">{formatINR(row.original.at_risk_paise)}</span>
      ) : (
        <span className="text-muted-foreground">—</span>
      ),
  },
  {
    id: "age",
    header: "Age",
    meta: { numeric: true },
    cell: ({ row }) => (row.original.age_days === null ? <span className="text-muted-foreground">—</span> : `${row.original.age_days} d`),
  },
  { id: "partner", header: "Owed by", cell: ({ row }) => <span className="truncate">{row.original.partner_name}</span> },
];

// ---------- URL state: filters, the open order and where the user came from ----------

function useOrdersUrl() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const filters = filtersFromParams(params);
  const open = params.get("open");
  const from = params.get("from");

  const update = useCallback(
    (patch: Record<string, string | undefined>) => {
      const next = new URLSearchParams(window.location.search);
      for (const [key, value] of Object.entries(patch)) {
        if (value) next.set(key, value);
        else next.delete(key);
      }
      router.replace(`${pathname}${next.size ? `?${next}` : ""}`, { scroll: false });
    },
    [router, pathname],
  );
  return { filters, open, from, update };
}

// ---------- filters ----------

function FilterSelect({
  label,
  value,
  onChange,
  children,
  className,
}: {
  label: string;
  value: string | undefined;
  onChange: (value: string | undefined) => void;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <Select value={value ?? ALL} onValueChange={(next) => onChange(next === ALL ? undefined : next)}>
      <SelectTrigger aria-label={label} className={cn("h-9 w-full bg-card", value && "border-primary/40 bg-sidebar-accent", className)}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>{children}</SelectContent>
    </Select>
  );
}

const CHIP_ORDER: ReconStatus[] = ["short_paid", "unpaid_past_due", "freight_overcharged", "return_not_received", "settled", "pending"];

function StatusChips({
  counts,
  active,
  onChange,
}: {
  counts: Partial<Record<ReconStatus, number>> | null | undefined;
  active: string | undefined;
  onChange: (status: string | undefined) => void;
}) {
  const count = (status: ReconStatus) => counts?.[status] ?? 0;
  const chips: { value: string | undefined; label: string; count: number | null; dot?: string }[] = [
    { value: undefined, label: "All", count: counts ? CHIP_ORDER.reduce((sum, status) => sum + count(status), 0) : null },
    { value: "flagged", label: "Flagged", count: counts ? FLAGGED.reduce((sum, status) => sum + count(status), 0) : null, dot: "bg-loss" },
    ...CHIP_ORDER.map((status) => ({
      value: status,
      label: STATUS_META[status].label,
      count: counts ? count(status) : null,
      dot: STATUS_META[status].tone === "loss" ? "bg-loss" : STATUS_META[status].tone === "settled" ? "bg-settled" : "bg-muted-foreground/50",
    })),
  ];
  return (
    <div
      role="group"
      aria-label="Filter by status"
      className="relative -mx-4 flex gap-1.5 overflow-x-auto px-4 pb-1 [scrollbar-width:none] sm:mx-0 sm:flex-wrap sm:px-0"
    >
      {chips.map((chip) => {
        const selected = (active ?? undefined) === chip.value;
        return (
          <button
            key={chip.label}
            type="button"
            aria-pressed={selected}
            onClick={() => onChange(selected ? undefined : chip.value)}
            className={cn(
              "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full border px-3 text-sm whitespace-nowrap transition-colors duration-150 outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
              selected
                ? "border-primary/40 bg-sidebar-accent font-medium text-sidebar-accent-foreground"
                : "bg-card text-foreground hover:border-input hover:bg-accent",
            )}
          >
            {chip.dot && <span aria-hidden className={cn("size-1.5 rounded-full", chip.dot)} />}
            {chip.label}
            <span className={cn("money text-xs", selected ? "text-sidebar-accent-foreground/80" : "text-muted-foreground")}>
              {chip.count === null ? "…" : formatCount(chip.count)}
            </span>
          </button>
        );
      })}
    </div>
  );
}

function Breadcrumb({ trail }: { trail: string }) {
  return (
    <nav aria-label="Breadcrumb" className="mb-2">
      <ol className="flex flex-wrap items-center gap-1 text-sm text-muted-foreground">
        <li>
          <Link href="/" className="rounded underline-offset-4 outline-none hover:text-foreground hover:underline focus-visible:ring-3 focus-visible:ring-ring/50">
            Money at risk
          </Link>
        </li>
        <li aria-hidden>
          <ChevronRight className="size-3.5" />
        </li>
        <li aria-current="page" className="font-medium text-foreground">
          {trail}
        </li>
      </ol>
    </nav>
  );
}

// ---------- rows ----------

function MobileCard({ order }: { order: OrderRow }) {
  const shortfall = order.diff_paise < SHORTFALL_PAISE;
  return (
    <div className="flex h-full min-w-0 flex-col justify-center gap-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <span className="money truncate font-medium">{order.order_id}</span>
        {order.at_risk_paise ? (
          <span className="money shrink-0 font-semibold text-loss">{formatINR(order.at_risk_paise)}</span>
        ) : (
          <span className={cn("money shrink-0 text-sm", shortfall ? "text-loss" : "text-muted-foreground")}>{formatSignedINR(order.diff_paise)}</span>
        )}
      </div>
      <div className="flex min-w-0 items-center gap-2">
        <StatusPill {...STATUS_META[order.status]} />
        <span className="truncate text-xs text-muted-foreground">
          {order.partner_name}
          {order.age_days !== null && ` · ${order.age_days} d overdue`}
        </span>
      </div>
      <span className="money truncate text-xs text-muted-foreground">
        {order.channel} · {formatDate(order.order_date)} · expected {formatINR(order.expected_paise)} · got {formatINR(order.received_paise)}
      </span>
    </div>
  );
}

/** One virtual row. Memoised: scrolling and moving the selection only re-render the rows that change. */
const OrderLine = memo(function OrderLine({
  row,
  index,
  start,
  height,
  active,
  mobile,
  onOpen,
  onActivate,
}: {
  row: Row<OrderRow>;
  index: number;
  start: number;
  height: number;
  active: boolean;
  mobile: boolean;
  onOpen: (index: number) => void;
  onActivate: (index: number) => void;
}) {
  return (
    <div
      id={`order-row-${index}`}
      role="row"
      tabIndex={active ? 0 : -1}
      aria-rowindex={index + 2}
      aria-selected={active}
      onClick={() => onOpen(index)}
      onFocus={() => onActivate(index)}
      className={cn(
        "absolute inset-x-0 top-0 cursor-pointer border-b px-4 text-sm outline-none transition-colors duration-100",
        mobile ? "py-2" : cn(GRID, "items-center"),
        "hover:bg-accent/60 focus-visible:bg-sidebar-accent",
        active && "bg-accent/40",
      )}
      style={{ height, transform: `translateY(${start}px)` }}
    >
      {mobile ? (
        <div role="cell" className="h-full">
          <MobileCard order={row.original} />
        </div>
      ) : (
        row.getVisibleCells().map((cell) => (
          <div
            key={cell.id}
            role="cell"
            className={cn("min-w-0 pr-3", (cell.column.columnDef.meta as ColumnMeta | undefined)?.numeric && "money text-right")}
          >
            {flexRender(cell.column.columnDef.cell, cell.getContext())}
          </div>
        ))
      )}
    </div>
  );
});

function TableSkeleton({ mobile }: { mobile: boolean }) {
  if (mobile) {
    return (
      <div className="divide-y rounded-xl border bg-card" role="status" aria-busy aria-label="Loading orders">
        {Array.from({ length: 7 }, (_, index) => (
          <div key={index} className="space-y-2 px-4 py-3">
            <div className="flex justify-between">
              <Skeleton className="h-4 w-32" />
              <Skeleton className="h-4 w-16" />
            </div>
            <Skeleton className="h-5 w-40 rounded-full" />
            <Skeleton className="h-3 w-56" />
          </div>
        ))}
      </div>
    );
  }
  return (
    <div className="overflow-hidden rounded-xl border bg-card" role="status" aria-busy aria-label="Loading orders">
      <div className={cn(GRID, "border-b bg-muted/60 px-4 py-3")}>
        {columns.map((column) => (
          <Skeleton key={column.id} className={cn("h-3 w-16", (column.meta as ColumnMeta | undefined)?.numeric && "ml-auto mr-3")} />
        ))}
      </div>
      {Array.from({ length: 10 }, (_, index) => (
        <div key={index} className={cn(GRID, "h-14 items-center border-b px-4 last:border-b-0")}>
          <div className="space-y-1.5">
            <Skeleton className="h-3.5 w-28" />
            <Skeleton className="h-3 w-36" />
          </div>
          <Skeleton className="h-5 w-24 rounded-full" />
          {Array.from({ length: 4 }, (__, cell) => (
            <Skeleton key={cell} className="mr-3 ml-auto h-3.5 w-16" />
          ))}
          <Skeleton className="mr-3 ml-auto h-3.5 w-8" />
          <Skeleton className="h-3.5 w-24" />
        </div>
      ))}
    </div>
  );
}

// ---------- screen ----------

export function OrdersView() {
  const { filters, open, from, update } = useOrdersUrl();
  const { data: user } = useCurrentUser();
  const mobile = useIsMobile();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState(filters.q ?? "");
  const [active, setActive] = useState(0);
  const partners = usePartners();
  const orders = useOrders(filters);
  const scrollRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const keyboardMove = useRef(false);

  // Debounced search into the URL.
  useEffect(() => {
    const timer = setTimeout(() => {
      if ((filters.q ?? "") !== search.trim()) update({ q: search.trim() || undefined });
    }, 250);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only react to typing
  }, [search]);

  const rows = useMemo(() => orders.data?.pages.flatMap((page) => page.items) ?? [], [orders.data]);
  const first = orders.data?.pages[0];
  // TanStack Table and Virtual return functions the React Compiler cannot memoise; it skips this component, as intended.
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({ data: rows, columns, getCoreRowModel: getCoreRowModel() });
  const tableRows = table.getRowModel().rows;
  const rowHeight = mobile ? CARD_HEIGHT : ROW_HEIGHT;

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => rowHeight,
    overscan: 10,
  });
  useEffect(() => virtualizer.measure(), [rowHeight, virtualizer]);
  const virtualRows = virtualizer.getVirtualItems();
  const lastIndex = virtualRows.at(-1)?.index ?? 0;

  useEffect(() => {
    if (lastIndex >= rows.length - 60 && orders.hasNextPage && !orders.isFetchingNextPage) orders.fetchNextPage();
  }, [lastIndex, rows.length, orders]);

  // A new filter starts the selection at the top again.
  const filterKey = JSON.stringify(filters);
  const [lastFilterKey, setLastFilterKey] = useState(filterKey);
  if (filterKey !== lastFilterKey) {
    setLastFilterKey(filterKey);
    setActive(0);
  }

  // Keyboard moves keep the selected row in view and focused.
  useEffect(() => {
    if (!keyboardMove.current) return;
    keyboardMove.current = false;
    virtualizer.scrollToIndex(active, { align: "auto" });
    // Focus at once when the row is already rendered, so fast key repeats keep landing on the table.
    const rendered = document.getElementById(`order-row-${active}`);
    if (rendered) {
      rendered.focus({ preventScroll: true });
      return;
    }
    const frame = requestAnimationFrame(() => document.getElementById(`order-row-${active}`)?.focus({ preventScroll: true }));
    return () => cancelAnimationFrame(frame);
  }, [active, virtualizer]);

  const prefetch = useCallback(
    (orderId: string) =>
      queryClient.prefetchQuery({
        queryKey: ["recon", "order", orderId],
        queryFn: () => apiFetch<OrderDetail>(`/recon/orders/${encodeURIComponent(orderId)}`),
        staleTime: 30_000,
      }),
    [queryClient],
  );

  const openAt = useCallback(
    (index: number) => {
      const order = rows[index];
      if (!order) return;
      setActive(index);
      update({ open: order.order_id });
    },
    [rows, update],
  );
  const activate = useCallback(
    (index: number) => {
      setActive(index);
      const order = rows[index];
      if (order) prefetch(order.order_id);
    },
    [rows, prefetch],
  );

  function onTableKeyDown(event: React.KeyboardEvent) {
    const last = rows.length - 1;
    const moves: Record<string, number> = { ArrowDown: active + 1, ArrowUp: active - 1, Home: 0, End: last, PageDown: active + 10, PageUp: active - 10 };
    if (event.key in moves) {
      event.preventDefault();
      keyboardMove.current = true;
      setActive(Math.max(0, Math.min(last, moves[event.key])));
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openAt(active);
    }
  }

  // Page shortcuts: "/" focuses search; ↓ from outside the table jumps into it.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (open || isTyping(event) || event.metaKey || event.ctrlKey || event.altKey) return;
      if (document.querySelector("[role=dialog]")) return;
      if (event.key === "/") {
        event.preventDefault();
        searchRef.current?.focus();
        searchRef.current?.select();
      } else if (event.key === "ArrowDown" && scrollRef.current && !scrollRef.current.contains(document.activeElement)) {
        event.preventDefault();
        virtualizer.scrollToIndex(active, { align: "auto" });
        const rendered = document.getElementById(`order-row-${active}`);
        if (rendered) rendered.focus({ preventScroll: true });
        else requestAnimationFrame(() => document.getElementById(`order-row-${active}`)?.focus({ preventScroll: true }));
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, active, virtualizer]);

  const hasFilters = Boolean(filters.partner || filters.status || filters.age || filters.q);
  function clearAll() {
    setSearch("");
    update({ partner: undefined, status: undefined, age: undefined, q: undefined, from: undefined });
  }

  const partnerName = partners.data?.find((partner) => String(partner.id) === filters.partner)?.name;
  const trail =
    from === "risk"
      ? [
          partnerName ?? (filters.partner ? "Partner" : "All partners"),
          filters.age ? `${filters.age} days overdue` : null,
          filters.status && filters.status !== "flagged" ? STATUS_META[filters.status as ReconStatus]?.label : null,
        ]
          .filter(Boolean)
          .join(" · ")
      : null;

  return (
    <>
      {trail && <Breadcrumb trail={trail} />}
      <PageHeader title="Orders" description="Every order with what was expected, what each partner paid, and why it is flagged." />

      <div className="mb-3 flex flex-col gap-2 lg:flex-row lg:items-center">
        <div className="relative lg:w-72">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input
            ref={searchRef}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") event.currentTarget.blur();
              if (event.key === "ArrowDown" && rows.length) {
                event.preventDefault();
                keyboardMove.current = true;
                setActive(0);
                requestAnimationFrame(() => document.getElementById("order-row-0")?.focus());
              }
            }}
            placeholder="Search order ID or AWB"
            aria-label="Search order ID or AWB"
            className="h-9 pr-9 pl-8"
          />
          <kbd className="pointer-events-none absolute top-1/2 right-2 hidden -translate-y-1/2 rounded border bg-secondary px-1.5 font-sans text-[11px] text-muted-foreground sm:block">
            /
          </kbd>
        </div>
        <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap">
          <FilterSelect label="Partner" value={filters.partner} onChange={(partner) => update({ partner })} className="sm:w-44">
            <SelectItem value={ALL}>All partners</SelectItem>
            <SelectSeparator />
            {partners.data
              ?.filter((partner) => partner.kind !== "warehouse")
              .map((partner) => (
                <SelectItem key={partner.id} value={String(partner.id)}>
                  {partner.name}
                </SelectItem>
              ))}
          </FilterSelect>
          <FilterSelect label="Age since due" value={filters.age} onChange={(age) => update({ age })} className="sm:w-40">
            <SelectItem value={ALL}>Any age</SelectItem>
            <SelectSeparator />
            {AGE_BUCKETS.map((bucket) => (
              <SelectItem key={bucket} value={bucket}>
                {bucket} days
              </SelectItem>
            ))}
          </FilterSelect>
          <FilterSelect label="Sort" value={filters.sort} onChange={(sort) => update({ sort })} className="col-span-2 sm:w-44">
            <SelectItem value={ALL}>Most at risk first</SelectItem>
            <SelectItem value="difference">Largest shortfall</SelectItem>
            <SelectItem value="age">Oldest first</SelectItem>
            <SelectItem value="order_date">Newest orders</SelectItem>
            <SelectItem value="order_id">Order ID</SelectItem>
          </FilterSelect>
        </div>
      </div>

      <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <StatusChips counts={first?.status_counts} active={filters.status} onChange={(status) => update({ status })} />
        {hasFilters && (
          <Button variant="ghost" size="sm" className="shrink-0 self-start" onClick={clearAll}>
            <X aria-hidden /> Clear all
          </Button>
        )}
      </div>

      <p className="mb-3 flex h-5 items-center text-sm text-muted-foreground" aria-live="polite">
        {first && (
          <>
            <span className="money font-medium text-foreground">{formatCount(first.total)}</span>&nbsp;{plural(first.total, "order")}
            {first.totals.at_risk_paise > 0 && (
              <>
                &nbsp;·&nbsp;<span className="money font-medium text-loss">{formatINRCompact(first.totals.at_risk_paise)}</span>&nbsp;at risk
              </>
            )}
            {orders.isFetching && !orders.isFetchingNextPage && <LoaderCircle className="ml-2 size-3.5 animate-spin" aria-label="Updating" />}
          </>
        )}
      </p>

      {orders.isPending ? (
        <TableSkeleton mobile={mobile} />
      ) : orders.error ? (
        <ErrorState title="Couldn't load orders" message={orders.error.message} onRetry={() => orders.refetch()} />
      ) : rows.length === 0 ? (
        hasFilters ? (
          <EmptyState icon={SearchX} title="No orders match these filters" action={<Button variant="outline" size="sm" onClick={clearAll}>Clear all filters</Button>}>
            Try another partner, status or age, or search a different ID.
          </EmptyState>
        ) : (
          <EmptyState
            icon={SearchX}
            title="No reconciled orders yet"
            action={
              canEdit(user) ? (
                <Button asChild size="sm">
                  <Link href="/uploads">
                    <Upload aria-hidden /> Upload partner reports
                  </Link>
                </Button>
              ) : undefined
            }
          >
            Every order appears here, with what each partner paid, once reports are uploaded and reconciled.
          </EmptyState>
        )
      ) : (
        <div className="overflow-hidden rounded-xl border bg-card">
          <div
            ref={scrollRef}
            onKeyDown={onTableKeyDown}
            className="h-[calc(100dvh-24rem)] min-h-[28rem] overflow-auto overscroll-contain [contain:strict] lg:h-[calc(100dvh-22rem)]"
            role="grid"
            aria-label="Reconciled orders"
            aria-rowcount={first ? first.total + 1 : undefined}
          >
            <div className={mobile ? undefined : "min-w-[64rem]"}>
              {!mobile && (
                <div role="rowgroup" className="sticky top-0 z-10 border-b bg-muted/95 backdrop-blur">
                  {table.getHeaderGroups().map((group) => (
                    <div key={group.id} role="row" aria-rowindex={1} className={cn(GRID, "px-4")}>
                      {group.headers.map((header) => (
                        <div
                          key={header.id}
                          role="columnheader"
                          className={cn(
                            "py-2.5 pr-3 text-xs font-medium text-muted-foreground",
                            (header.column.columnDef.meta as ColumnMeta | undefined)?.numeric && "text-right",
                          )}
                        >
                          {flexRender(header.column.columnDef.header, header.getContext())}
                        </div>
                      ))}
                    </div>
                  ))}
                </div>
              )}
              <div role="rowgroup" className="relative" style={{ height: virtualizer.getTotalSize() }}>
                {virtualRows.map((virtualRow) => {
                  const row = tableRows[virtualRow.index];
                  if (!row) return null;
                  return (
                    <OrderLine
                      key={row.id}
                      row={row}
                      index={virtualRow.index}
                      start={virtualRow.start}
                      height={rowHeight}
                      active={virtualRow.index === active}
                      mobile={mobile}
                      onOpen={openAt}
                      onActivate={activate}
                    />
                  );
                })}
              </div>
              {orders.isFetchingNextPage && (
                <p className="flex items-center justify-center gap-2 py-3 text-xs text-muted-foreground">
                  <LoaderCircle className="size-3.5 animate-spin" aria-hidden /> Loading more orders…
                </p>
              )}
            </div>
          </div>
        </div>
      )}

      <OrderDrawer orderId={open} onClose={() => update({ open: undefined })} />
    </>
  );
}
