"use client";

import { ChevronsUpDown, Keyboard, LoaderCircle, LogOut, Moon, Search, Sun } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { Brand } from "@/components/brand";
import { CommandPalette } from "@/components/command-palette";
import { PageTransition } from "@/components/motion";
import { ShortcutsSheet } from "@/components/shortcuts-sheet";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ROLE_LABELS, type User, useLogout } from "@/lib/auth";
import { isActive, navItemsFor } from "@/lib/nav";
import { toggleTheme, useTheme } from "@/lib/theme";
import { openOverlay, useModKey } from "@/lib/ui-store";
import { cn } from "@/lib/utils";

const FOCUS = "outline-none focus-visible:ring-3 focus-visible:ring-ring/50";

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

function SidebarNav({ user }: { user: User }) {
  const pathname = usePathname();
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
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}

/** Mobile: the main screens as a bottom bar, thumb-reachable, 56px tall plus the safe area. */
function BottomNav({ user }: { user: User }) {
  const pathname = usePathname();
  return (
    <nav
      aria-label="Main"
      className="fixed inset-x-0 bottom-0 z-30 border-t bg-card/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden"
    >
      <ul className="mx-auto flex max-w-lg">
        {navItemsFor(user.role).map((item) => {
          const active = isActive(pathname, item.href);
          return (
            <li key={item.href} className="flex-1">
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex h-14 flex-col items-center justify-center gap-1 text-[11px] font-medium transition-colors duration-150",
                  FOCUS,
                  active ? "text-primary" : "text-muted-foreground hover:text-foreground",
                )}
              >
                <item.icon className="size-5" aria-hidden strokeWidth={active ? 2.25 : 2} />
                {item.short}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
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
      <span className="flex-1 text-left">Search or jump to…</span>
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
      <CommandPalette user={user} />
      <ShortcutsSheet />
    </div>
  );
}
