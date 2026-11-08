"use client";

import { ChevronsUpDown, Ellipsis, Keyboard, LoaderCircle, LogOut, Moon, Search, Sun } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Brand } from "@/components/brand";
import { PageTransition } from "@/components/motion";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ROLE_LABELS, type User, useLogout } from "@/lib/auth";
import { formatCount } from "@/lib/format";
import { isActive, type NavItem, navItemsFor } from "@/lib/nav";
import { useReviewCounts } from "@/lib/review";
import { toggleTheme, useTheme } from "@/lib/theme";
import { closeOverlay, isTyping, openOverlay, useModKey, useOverlay } from "@/lib/ui-store";
import { cn } from "@/lib/utils";

const FOCUS = "outline-none focus-visible:ring-3 focus-visible:ring-ring/50";

// Loaded the first time they are opened, so they never weigh on the first screen.
const CommandPalette = dynamic(() => import("@/components/command-palette").then((module) => module.CommandPalette), { ssr: false });
const ShortcutsSheet = dynamic(() => import("@/components/shortcuts-sheet").then((module) => module.ShortcutsSheet), { ssr: false });

/** Ctrl/Cmd+K toggles the palette (even while typing); "?" opens the shortcuts, except in a text field. */
function useGlobalShortcuts(paletteOpen: boolean) {
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (paletteOpen) closeOverlay();
        else openOverlay("palette");
      } else if (event.key === "?" && !isTyping(event) && !event.metaKey && !event.ctrlKey) {
        event.preventDefault();
        openOverlay("shortcuts");
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [paletteOpen]);
}

function initials(name: string): string {
  const parts = name.replace(/\(.*\)/, "").trim().split(/\s+/);
  return parts
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

function Avatar({ user, className }: { user: User; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "flex size-8 shrink-0 items-center justify-center rounded-full bg-secondary text-xs font-semibold text-secondary-foreground",
        className,
      )}
    >
      {initials(user.name)}
    </span>
  );
}

/** Open lines in the review queue, shown next to its nav item. */
function useNavBadges(): Record<string, number | undefined> {
  const counts = useReviewCounts();
  return { "/review": counts.data?.open || undefined };
}

function Badge({ count, className }: { count: number | undefined; className?: string }) {
  if (!count) return null;
  return (
    <span className={cn("money rounded-full bg-attention-soft px-1.5 text-[11px] leading-5 font-medium text-attention ring-1 ring-attention/25 ring-inset", className)}>
      {formatCount(count)}
    </span>
  );
}

function SidebarNav({ user }: { user: User }) {
  const pathname = usePathname();
  const badges = useNavBadges();
  return (
    <nav aria-label="Main" className="flex flex-col gap-0.5">
      {navItemsFor(user.role).map((item) => {
        const active = isActive(pathname, item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex h-9 items-center gap-2.5 rounded-lg px-2.5 text-sm font-medium transition-colors duration-150",
              FOCUS,
              active
                ? "bg-sidebar-accent text-sidebar-accent-foreground"
                : "text-sidebar-foreground hover:bg-accent hover:text-foreground",
            )}
          >
            <item.icon className="size-4 shrink-0" aria-hidden />
            <span className="flex-1">{item.label}</span>
            <Badge count={badges[item.href]} />
            {badges[item.href] ? <span className="sr-only"> ({badges[item.href]} open)</span> : null}
          </Link>
        );
      })}
    </nav>
  );
}

const BOTTOM_ITEM = "relative flex h-14 w-full flex-col items-center justify-center gap-1 text-[11px] font-medium transition-colors duration-150";

/** Mobile: the main screens as a bottom bar, thumb-reachable, 56px tall plus the safe area. The rest open from "More". */
function BottomNav({ user }: { user: User }) {
  const pathname = usePathname();
  const badges = useNavBadges();
  const [moreOpen, setMoreOpen] = useState(false);
  const items = navItemsFor(user.role);
  const primary = items.filter((item) => item.primary);
  const more = items.filter((item) => !item.primary);
  const moreActive = more.some((item) => isActive(pathname, item.href));
  return (
    <nav
      aria-label="Main"
      className="fixed inset-x-0 bottom-0 z-30 border-t bg-card/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden"
    >
      <ul className="mx-auto flex max-w-lg">
        {primary.map((item) => {
          const active = isActive(pathname, item.href);
          return (
            <li key={item.href} className="flex-1">
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(BOTTOM_ITEM, FOCUS, active ? "text-primary" : "text-muted-foreground hover:text-foreground")}
              >
                <item.icon className="size-5" aria-hidden strokeWidth={active ? 2.25 : 2} />
                {item.short}
                <Badge count={badges[item.href]} className="absolute top-1.5 left-1/2 ml-2" />
              </Link>
            </li>
          );
        })}
        {more.length > 0 && (
          <li className="flex-1">
            <button
              type="button"
              onClick={() => setMoreOpen(true)}
              aria-haspopup="dialog"
              className={cn(BOTTOM_ITEM, FOCUS, moreActive ? "text-primary" : "text-muted-foreground hover:text-foreground")}
            >
              <Ellipsis className="size-5" aria-hidden />
              More
            </button>
          </li>
        )}
      </ul>
      <MoreSheet items={more} open={moreOpen} onOpenChange={setMoreOpen} pathname={pathname} />
    </nav>
  );
}

function MoreSheet({ items, open, onOpenChange, pathname }: { items: NavItem[]; open: boolean; onOpenChange: (open: boolean) => void; pathname: string }) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="bottom" className="gap-0 rounded-t-2xl pb-[env(safe-area-inset-bottom)]">
        <SheetHeader className="border-b px-5 py-4">
          <SheetTitle>More</SheetTitle>
          <SheetDescription className="sr-only">Other screens</SheetDescription>
        </SheetHeader>
        <ul className="p-2">
          {items.map((item) => {
            const active = isActive(pathname, item.href);
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  onClick={() => onOpenChange(false)}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex h-12 items-center gap-3 rounded-lg px-3 text-sm font-medium",
                    FOCUS,
                    active ? "bg-sidebar-accent text-sidebar-accent-foreground" : "hover:bg-accent",
                  )}
                >
                  <item.icon className="size-5 text-muted-foreground" aria-hidden />
                  {item.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </SheetContent>
    </Sheet>
  );
}

function UserMenu({ user, compact }: { user: User; compact?: boolean }) {
  const router = useRouter();
  const logout = useLogout();
  const theme = useTheme();

  function signOut() {
    logout.mutate(undefined, { onSettled: () => router.replace("/login") });
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        {compact ? (
          <button type="button" aria-label={`Account: ${user.name}`} className={cn("rounded-full p-1.5", FOCUS)}>
            <Avatar user={user} />
          </button>
        ) : (
          <button
            type="button"
            className={cn(
              "flex w-full items-center gap-2.5 rounded-lg p-2 text-left transition-colors duration-150 hover:bg-accent aria-expanded:bg-accent",
              FOCUS,
            )}
          >
            <Avatar user={user} />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium">{user.name}</span>
              <span className="block truncate text-xs text-muted-foreground">{ROLE_LABELS[user.role]}</span>
            </span>
            <ChevronsUpDown className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          </button>
        )}
      </DropdownMenuTrigger>
      <DropdownMenuContent
        side={compact ? "bottom" : "top"}
        align={compact ? "end" : "start"}
        className={cn("min-w-56", !compact && "w-(--radix-dropdown-menu-trigger-width)")}
      >
        <DropdownMenuLabel className="font-normal">
          <span className="block truncate text-sm font-medium text-foreground">{user.email}</span>
          <span className="block text-xs text-muted-foreground">
            {ROLE_LABELS[user.role]} · {user.role === "cofounder" ? "read-only access" : "full access"}
          </span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={toggleTheme}>
          {theme === "dark" ? <Sun /> : <Moon />}
          {theme === "dark" ? "Light theme" : "Dark theme"}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => openOverlay("shortcuts")} className="hidden lg:flex">
          <Keyboard />
          Keyboard shortcuts
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={signOut} disabled={logout.isPending}>
          {logout.isPending ? <LoaderCircle className="animate-spin" /> : <LogOut />}
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function SearchButton() {
  const mod = useModKey();
  return (
    <button
      type="button"
      onClick={() => openOverlay("palette")}
      className={cn(
        "flex h-9 w-full items-center gap-2 rounded-lg border bg-background px-2.5 text-sm text-muted-foreground transition-colors duration-150 hover:border-input hover:text-foreground",
        FOCUS,
      )}
    >
      <Search className="size-4" aria-hidden />
      <span className="flex-1 truncate text-left whitespace-nowrap">Search…</span>
      <kbd className="rounded border bg-card px-1.5 font-sans text-[11px]">{mod} K</kbd>
    </button>
  );
}

function ThemeButton() {
  const theme = useTheme();
  const label = theme === "dark" ? "Switch to light theme" : "Switch to dark theme";
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button variant="ghost" size="icon" onClick={toggleTheme} aria-label={label}>
          {theme === "dark" ? <Sun /> : <Moon />}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

export function AppShell({ user, children }: { user: User; children: React.ReactNode }) {
  const pathname = usePathname();
  const overlay = useOverlay();
  useGlobalShortcuts(overlay === "palette");
  // Once opened, keep each overlay mounted so its close animation and state survive.
  const [loaded, setLoaded] = useState({ palette: false, shortcuts: false });
  // Mount the (closed) palette once the first screen is idle. Mounting it on the first Ctrl+K took about 300 ms,
  // and the keys typed in that time were lost.
  useEffect(() => {
    const whenIdle = window.requestIdleCallback ?? ((callback: () => void) => window.setTimeout(callback, 2000));
    whenIdle(() => setLoaded((current) => ({ ...current, palette: true })));
  }, []);
  if (overlay && !loaded[overlay]) setLoaded({ ...loaded, [overlay]: true });

  return (
    <div className="min-h-dvh lg:pl-60">
      <a
        href="#main"
        className="sr-only z-50 rounded-lg bg-card px-3 py-2 text-sm font-medium focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        Skip to content
      </a>

      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 hidden w-60 flex-col border-r border-sidebar-border bg-sidebar lg:flex">
        <div className="flex h-14 items-center justify-between px-4">
          <Link href="/" className={cn("rounded-lg", FOCUS)}>
            <Brand />
          </Link>
          <ThemeButton />
        </div>
        <div className="px-3 pt-1 pb-3">
          <SearchButton />
        </div>
        <div className="flex-1 overflow-y-auto px-3 pb-3">
          <SidebarNav user={user} />
        </div>
        <div className="border-t border-sidebar-border p-2">
          <UserMenu user={user} />
        </div>
      </aside>

      {/* Mobile top bar */}
      <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b bg-card/90 pr-2 pl-4 backdrop-blur lg:hidden">
        <Link href="/" className={cn("rounded-lg", FOCUS)}>
          <Brand />
        </Link>
        <div className="flex items-center">
          <Button variant="ghost" size="icon-lg" aria-label="Search or jump to" onClick={() => openOverlay("palette")}>
            <Search />
          </Button>
          <UserMenu user={user} compact />
        </div>
      </header>

      <main
        id="main"
        className="mx-auto w-full max-w-7xl px-4 pt-6 pb-[calc(5rem+env(safe-area-inset-bottom))] sm:px-6 lg:px-8 lg:py-8"
      >
        <PageTransition key={pathname}>{children}</PageTransition>
      </main>

      <BottomNav user={user} />
      {loaded.palette && <CommandPalette user={user} />}
      {loaded.shortcuts && <ShortcutsSheet />}
    </div>
  );
}
