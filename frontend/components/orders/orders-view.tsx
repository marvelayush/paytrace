"use client";

import { type ColumnDef, flexRender, getCoreRowModel, useReactTable } from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { LoaderCircle, Search, SearchX, X } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { OrderDrawer } from "@/components/orders/order-drawer";
import { EmptyState, ErrorState, PageHeader } from "@/components/page-header";
import { StatusPill } from "@/components/status-pill";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectSeparator, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCount, formatDate, formatINR, formatINRCompact, formatSignedINR } from "@/lib/format";
import { usePartners } from "@/lib/rate-cards";
import { AGE_BUCKETS, type OrderFilters, type OrderRow, type ReconStatus, STATUS_META, useOrders } from "@/lib/recon";
import { cn } from "@/lib/utils";

const ALL = "__all__";
const ROW_HEIGHT = 56;
const GRID = "grid grid-cols-[minmax(11rem,1.4fr)_minmax(9rem,1fr)_repeat(4,minmax(7rem,0.8fr))_minmax(4.5rem,0.5fr)_minmax(8rem,0.9fr)]";

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
      <span className={cn(row.original.diff_paise < -1000 && "font-medium text-loss")}>{formatSignedINR(row.original.diff_paise)}</span>
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

function useFilters(): [OrderFilters, (patch: Partial<OrderFilters>) => void] {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const filters: OrderFilters = {
    partner: params.get("partner") ?? undefined,
    status: params.get("status") ?? undefined,
    age: params.get("age") ?? undefined,
    q: params.get("q") ?? undefined,
    sort: params.get("sort") ?? undefined,
  };
  function update(patch: Partial<OrderFilters>) {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(patch)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    router.replace(`${pathname}${next.size ? `?${next}` : ""}`, { scroll: false });
  }
  return [filters, update];
}

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

export function OrdersView() {
  const [filters, setFilters] = useFilters();
  const [search, setSearch] = useState(filters.q ?? "");
  const [openOrder, setOpenOrder] = useState<string | null>(null);
  const partners = usePartners();
  const orders = useOrders(filters);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Debounced search into the URL.
  useEffect(() => {
    const timer = setTimeout(() => {
      if ((filters.q ?? "") !== search.trim()) setFilters({ q: search.trim() || undefined });
    }, 300);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only react to typing
  }, [search]);

  const rows = useMemo(() => orders.data?.pages.flatMap((page) => page.items) ?? [], [orders.data]);
  const first = orders.data?.pages[0];
  // TanStack Table and Virtual return functions the React Compiler cannot memoise; it skips this component, as intended.
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({ data: rows, columns, getCoreRowModel: getCoreRowModel() });

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
  });
  const virtualRows = virtualizer.getVirtualItems();
  const lastIndex = virtualRows.at(-1)?.index ?? 0;

  useEffect(() => {
    if (lastIndex >= rows.length - 40 && orders.hasNextPage && !orders.isFetchingNextPage) orders.fetchNextPage();
  }, [lastIndex, rows.length, orders]);

  const hasFilters = Boolean(filters.partner || filters.status || filters.age || filters.q);
  const statusOptions: { value: string; label: string }[] = [
    { value: "flagged", label: "All flagged (money at risk)" },
    ...(Object.keys(STATUS_META) as ReconStatus[]).map((status) => ({ value: status, label: STATUS_META[status].label })),
  ];

  return (
    <>
      <PageHeader title="Orders" description="Every order with what was expected, what each partner paid, and why it is flagged." />

      <div className="mb-4 flex flex-col gap-2 lg:flex-row lg:flex-wrap lg:items-center">
        <div className="relative lg:w-64">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search order ID or AWB"
            aria-label="Search order ID or AWB"
            className="h-9 pl-8"
          />
        </div>
        <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap">
          <FilterSelect label="Partner" value={filters.partner} onChange={(partner) => setFilters({ partner })} className="sm:w-44">
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
          <FilterSelect label="Status" value={filters.status} onChange={(status) => setFilters({ status })} className="sm:w-52">
            <SelectItem value={ALL}>All statuses</SelectItem>
            <SelectSeparator />
            {statusOptions.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </FilterSelect>
          <FilterSelect label="Age since due" value={filters.age} onChange={(age) => setFilters({ age })} className="sm:w-40">
            <SelectItem value={ALL}>Any age</SelectItem>
            <SelectSeparator />
            {AGE_BUCKETS.map((bucket) => (
              <SelectItem key={bucket} value={bucket}>
                {bucket} days
              </SelectItem>
            ))}
          </FilterSelect>
          <FilterSelect label="Sort" value={filters.sort} onChange={(sort) => setFilters({ sort })} className="sm:w-44">
            <SelectItem value={ALL}>Most at risk first</SelectItem>
            <SelectItem value="difference">Largest shortfall</SelectItem>
            <SelectItem value="age">Oldest first</SelectItem>
            <SelectItem value="order_date">Newest orders</SelectItem>
            <SelectItem value="order_id">Order ID</SelectItem>
          </FilterSelect>
        </div>
        {hasFilters && (
          <Button
            variant="ghost"
            size="sm"
            className="self-start lg:self-auto"
            onClick={() => {
              setSearch("");
              setFilters({ partner: undefined, status: undefined, age: undefined, q: undefined });
            }}
          >
            <X aria-hidden /> Clear filters
          </Button>
        )}
      </div>

      {first && (
        <p className="mb-3 text-sm text-muted-foreground" aria-live="polite">
          <span className="money font-medium text-foreground">{formatCount(first.total)}</span> orders
          {first.totals.at_risk_paise > 0 && (
            <>
              {" "}· <span className="money font-medium text-loss">{formatINRCompact(first.totals.at_risk_paise)}</span> at risk
            </>
          )}
          {orders.isFetching && !orders.isFetchingNextPage && <LoaderCircle className="ml-2 inline size-3.5 animate-spin" aria-label="Updating" />}
        </p>
      )}

      {orders.isPending ? (
        <div className="space-y-2 rounded-xl border bg-card p-3">
          {Array.from({ length: 10 }, (_, index) => (
            <Skeleton key={index} className="h-10 w-full" />
          ))}
        </div>
      ) : orders.error ? (
        <ErrorState title="Couldn't load orders" message={orders.error.message} onRetry={() => orders.refetch()} />
      ) : rows.length === 0 ? (
        hasFilters ? (
          <EmptyState icon={SearchX} title="No orders match these filters">
            Try another partner or status, or clear the filters.
          </EmptyState>
        ) : (
          <EmptyState icon={SearchX} title="No reconciled orders yet">
            Upload order and partner reports; every order appears here once reconciliation has run.
          </EmptyState>
        )
      ) : (
        <div className="overflow-hidden rounded-xl border bg-card">
          <div ref={scrollRef} className="h-[calc(100dvh-20rem)] min-h-96 overflow-auto" role="table" aria-label="Reconciled orders" aria-rowcount={first?.total}>
            <div className="min-w-[64rem]">
              <div role="rowgroup" className="sticky top-0 z-10 border-b bg-muted/95 backdrop-blur">
                {table.getHeaderGroups().map((group) => (
                  <div key={group.id} role="row" className={cn(GRID, "px-4")}>
                    {group.headers.map((header) => (
                      <div
                        key={header.id}
                        role="columnheader"
                        className={cn(
                          "py-2.5 pr-3 text-xs font-medium text-muted-foreground",
                          (header.column.columnDef.meta as { numeric?: boolean } | undefined)?.numeric && "text-right",
                        )}
                      >
                        {flexRender(header.column.columnDef.header, header.getContext())}
                      </div>
                    ))}
                  </div>
                ))}
              </div>
              <div role="rowgroup" className="relative" style={{ height: virtualizer.getTotalSize() }}>
                {virtualRows.map((virtualRow) => {
                  const row = table.getRowModel().rows[virtualRow.index];
                  return (
                    <div
                      key={row.id}
                      role="row"
                      tabIndex={0}
                      aria-rowindex={virtualRow.index + 2}
                      onClick={() => setOpenOrder(row.original.order_id)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          setOpenOrder(row.original.order_id);
                        }
                      }}
                      className={cn(
                        GRID,
                        "absolute inset-x-0 cursor-pointer items-center border-b px-4 text-sm outline-none hover:bg-accent/60 focus-visible:bg-sidebar-accent",
                      )}
                      style={{ height: ROW_HEIGHT, transform: `translateY(${virtualRow.start}px)` }}
                    >
                      {row.getVisibleCells().map((cell) => (
                        <div
                          key={cell.id}
                          role="cell"
                          className={cn(
                            "min-w-0 pr-3",
                            (cell.column.columnDef.meta as { numeric?: boolean } | undefined)?.numeric && "money text-right",
                          )}
                        >
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </div>
                      ))}
                    </div>
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

      <OrderDrawer orderId={openOrder} onClose={() => setOpenOrder(null)} />
    </>
  );
}
