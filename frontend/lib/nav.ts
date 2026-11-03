import { FileWarning, LayoutDashboard, ListChecks, type LucideIcon, Percent, Upload } from "lucide-react";

import type { Role } from "@/lib/auth";

export type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Roles that see this item. Co-founders never see screens they cannot use (A2). */
  roles: Role[];
};

/**
 * Main navigation. An item is added here only when its screen ships,
 * so the sidebar never links to a placeholder page.
 */
export const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Money at risk", icon: LayoutDashboard, roles: ["finance_exec", "cofounder"] },
  { href: "/orders", label: "Orders", icon: ListChecks, roles: ["finance_exec", "cofounder"] },
  { href: "/claims", label: "Claims", icon: FileWarning, roles: ["finance_exec", "cofounder"] },
  { href: "/uploads", label: "Uploads", icon: Upload, roles: ["finance_exec"] },
  { href: "/rate-cards", label: "Rate cards", icon: Percent, roles: ["finance_exec", "cofounder"] },
];

export function navItemsFor(role: Role): NavItem[] {
  return NAV_ITEMS.filter((item) => item.roles.includes(role));
}

export function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}
