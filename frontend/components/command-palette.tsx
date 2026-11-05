"use client";

import { useQuery } from "@tanstack/react-query";
import { Command } from "cmdk";
import { FileWarning, Keyboard, LoaderCircle, LogOut, Moon, RefreshCw, Search, Sun } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { StatusPill } from "@/components/status-pill";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { apiFetch } from "@/lib/api";
import { canEdit, type User, useLogout } from "@/lib/auth";
import { CLAIM_STATUS_META, useClaims } from "@/lib/claims";
import { formatCount, formatDuration, formatINRCompact, formatSignedINR } from "@/lib/format";
import { navItemsFor } from "@/lib/nav";
import { type OrdersPage, STATUS_META, useRunReconciliation } from "@/lib/recon";
import { toggleTheme, useTheme } from "@/lib/theme";
import { closeOverlay, openOverlay, useOverlay } from "@/lib/ui-store";

const ITEM =
  "flex min-h-10 cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-sm text-foreground outline-none select-none data-[selected=true]:bg-accent data-[disabled=true]:cursor-not-allowed data-[disabled=true]:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-muted-foreground";
const GROUP =
  "px-1.5 py-1 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground";

function matches(query: string, ...texts: string[]): boolean {
  const needle = query.trim().toLowerCase();
  return !needle || texts.some((text) => text.toLowerCase().includes(needle));
}

/** Orders whose ID or AWB contains the typed text, straight from the API (debounced). */
function useOrderSearch(query: string, enabled: boolean) {
  const [debounced, setDebounced] = useState(query);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(query.trim()), 200);
    return () => clearTimeout(timer);
  }, [query]);
  return useQuery({
    queryKey: ["palette", "orders", debounced],
    queryFn: () => apiFetch<OrdersPage>(`/recon/orders?q=${encodeURIComponent(debounced)}&limit=6`),
    enabled: enabled && debounced.length >= 3,
    staleTime: 30_000,
  });
}

export function CommandPalette({ user }: { user: User }) {
  const router = useRouter();
  const open = useOverlay() === "palette";
  const [query, setQuery] = useState("");
  const theme = useTheme();
  const editor = canEdit(user);
  const claims = useClaims({ enabled: open });
  const orders = useOrderSearch(query, open);
  const run = useRunReconciliation();
  const logout = useLogout();

  // Ctrl/Cmd+K anywhere toggles the palette (even while typing in a field).
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (open) closeOverlay();
        else openOverlay("palette");
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  function setOpen(next: boolean) {
    if (!next) {
      closeOverlay();
      setQuery("");
    }
  }

  function go(href: string) {
    setOpen(false);
    router.push(href);
  }

  const screens = navItemsFor(user.role).filter((item) => matches(query, item.label, "go to"));
  // The claim worth opening per partner: its open claim, else its latest one.
  const claimList = claims.data;
  const partnerClaims = useMemo(() => {
    const byPartner = new Map<string, NonNullable<typeof claimList>[number]>();
    for (const claim of claimList ?? []) {
      const current = byPartner.get(claim.partner_name);
      if (!current || (claim.status === "open" && current.status !== "open")) byPartner.set(claim.partner_name, claim);
    }
    return [...byPartner.values()]
      .filter((claim) => matches(query, claim.partner_name, "claims"))
      .sort((a, b) => b.total_paise - a.total_paise);
  }, [claimList, query]);

  const themeLabel = theme === "dark" ? "Switch to light theme" : "Switch to dark theme";
  const actions = [
    editor && matches(query, "run reconciliation", "recompute", "match") ? "run" : null,
    matches(query, themeLabel, "theme dark light mode") ? "theme" : null,
    matches(query, "keyboard shortcuts", "help") ? "shortcuts" : null,
    matches(query, "sign out", "log out") ? "logout" : null,
  ].filter(Boolean);

  const searching = query.trim().length >= 3;
  const foundOrders = searching ? (orders.data?.items ?? []) : [];

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent
        showCloseButton={false}
        className="top-[12vh] translate-y-0 gap-0 overflow-hidden p-0 sm:max-w-xl data-open:slide-in-from-top-2"
      >
        <DialogTitle className="sr-only">Command palette</DialogTitle>
        <DialogDescription className="sr-only">Jump to a screen, find an order, or run an action.</DialogDescription>
        <Command shouldFilter={false} loop label="Command palette">
          <div className="flex items-center gap-2 border-b px-4">
            <Search className="size-4 shrink-0 text-muted-foreground" aria-hidden />
            <Command.Input
              value={query}
              onValueChange={setQuery}
              placeholder="Jump to a screen, search an order ID or AWB…"
              className="h-12 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            />
            {orders.isFetching && <LoaderCircle className="size-4 shrink-0 animate-spin text-muted-foreground" aria-label="Searching" />}
          </div>
          <Command.List className="max-h-[min(60vh,26rem)] overflow-y-auto overscroll-contain py-1">
            <Command.Empty className="px-4 py-8 text-center text-sm text-muted-foreground">
              {searching && orders.isFetching ? "Searching orders…" : `Nothing matches “${query}”.`}
            </Command.Empty>

            {foundOrders.length > 0 && (
              <Command.Group heading="Orders" className={GROUP}>
                {foundOrders.map((order) => (
                  <Command.Item
                    key={order.order_id}
                    value={`order-${order.order_id}`}
                    onSelect={() => go(`/orders?q=${encodeURIComponent(order.order_id)}&open=${encodeURIComponent(order.order_id)}`)}
                    className={ITEM}
                  >
                    <span className="money min-w-0 flex-1 truncate font-medium">{order.order_id}</span>
                    <StatusPill {...STATUS_META[order.status]} />
                    <span className={`money w-24 text-right text-xs ${order.diff_paise < -1000 ? "text-loss" : "text-muted-foreground"}`}>
                      {formatSignedINR(order.diff_paise)}
                    </span>
                  </Command.Item>
                ))}
                {orders.data && orders.data.total > foundOrders.length && (
                  <Command.Item value="order-all" onSelect={() => go(`/orders?q=${encodeURIComponent(query.trim())}`)} className={ITEM}>
                    <Search aria-hidden />
                    See all {formatCount(orders.data.total)} matching orders
                  </Command.Item>
                )}
              </Command.Group>
            )}

            {screens.length > 0 && (
              <Command.Group heading="Go to" className={GROUP}>
                {screens.map((item) => (
                  <Command.Item key={item.href} value={`go-${item.href}`} onSelect={() => go(item.href)} className={ITEM}>
                    <item.icon aria-hidden />
                    {item.label}
                  </Command.Item>
                ))}
              </Command.Group>
            )}

            {partnerClaims.length > 0 && (
              <Command.Group heading="Partner claims" className={GROUP}>
                {partnerClaims.map((claim) => (
                  <Command.Item key={claim.id} value={`claim-${claim.id}`} onSelect={() => go(`/claims/${claim.id}`)} className={ITEM}>
                    <FileWarning aria-hidden />
                    <span className="min-w-0 flex-1 truncate">{claim.partner_name}</span>
                    <span className="text-xs text-muted-foreground">{CLAIM_STATUS_META[claim.status].label}</span>
                    <span className="money w-20 text-right text-xs font-medium">{formatINRCompact(claim.total_paise)}</span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}

            {actions.length > 0 && (
              <Command.Group heading="Actions" className={GROUP}>
                {actions.includes("run") && (
                  <Command.Item
                    value="action-run"
                    disabled={run.isPending}
                    onSelect={() => {
                      setOpen(false);
                      const pending = toast.loading("Reconciling every order…");
                      run.mutate(undefined, {
                        onSuccess: (summary) =>
                          toast.success(`Reconciled ${formatCount(summary.order_count)} orders in ${formatDuration(summary.duration_ms)}`, { id: pending }),
                        onError: (error) => toast.error(error.message, { id: pending }),
                      });
                    }}
                    className={ITEM}
                  >
                    <RefreshCw aria-hidden />
                    Run reconciliation
                  </Command.Item>
                )}
                {actions.includes("theme") && (
                  <Command.Item value="action-theme" onSelect={() => { toggleTheme(); setOpen(false); }} className={ITEM}>
                    {theme === "dark" ? <Sun aria-hidden /> : <Moon aria-hidden />}
                    {themeLabel}
                  </Command.Item>
                )}
                {actions.includes("shortcuts") && (
                  <Command.Item value="action-shortcuts" onSelect={() => openOverlay("shortcuts")} className={ITEM}>
                    <Keyboard aria-hidden />
                    Keyboard shortcuts
                    <kbd className="ml-auto rounded border px-1.5 text-xs text-muted-foreground">?</kbd>
                  </Command.Item>
                )}
                {actions.includes("logout") && (
                  <Command.Item
                    value="action-logout"
                    onSelect={() => {
                      setOpen(false);
                      logout.mutate(undefined, { onSettled: () => router.replace("/login") });
                    }}
                    className={ITEM}
                  >
                    <LogOut aria-hidden />
                    Sign out
                  </Command.Item>
                )}
              </Command.Group>
            )}
          </Command.List>
          <div className="flex items-center gap-4 border-t px-4 py-2 text-xs text-muted-foreground">
            <span><kbd className="font-sans">↑↓</kbd> to move</span>
            <span><kbd className="font-sans">Enter</kbd> to open</span>
            <span><kbd className="font-sans">Esc</kbd> to close</span>
          </div>
        </Command>
      </DialogContent>
    </Dialog>
  );
}
