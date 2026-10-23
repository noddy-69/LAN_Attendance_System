"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { LucideIcon, ChevronDown } from "lucide-react";

export interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
  badge?: number;
}

// A collapsible group of nav items (used to keep long sidebars tidy).
export interface NavGroup {
  group: string;
  icon: LucideIcon;
  items: NavItem[];
}

export type NavEntry = NavItem | NavGroup;

function isNavGroup(e: NavEntry): e is NavGroup {
  return (e as NavGroup).items !== undefined;
}

interface SidebarProps {
  items: NavEntry[];
  portalLabel: string;
}

export function Sidebar({ items, portalLabel }: SidebarProps) {
  const pathname = usePathname();
  const isActive = (href: string) =>
    pathname === href || pathname.startsWith(href + "/");
  const groupHasActive = (g: NavGroup) => g.items.some((i) => isActive(i.href));

  // Manual expand/collapse overrides. Default (undefined) = open when a child is active.
  const [overrides, setOverrides] = useState<Record<string, boolean>>({});
  const isOpen = (g: NavGroup) => overrides[g.group] ?? groupHasActive(g);
  const toggle = (g: NavGroup) =>
    setOverrides((o) => ({ ...o, [g.group]: !(o[g.group] ?? groupHasActive(g)) }));

  return (
    <aside className="hidden w-64 flex-col border-r bg-background md:flex">
      <div className="flex h-16 items-center border-b px-6">
        <span className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
          {portalLabel}
        </span>
      </div>
      <nav className="flex-1 overflow-y-auto px-3 py-4">
        <ul className="space-y-1">
          {items.map((entry) => {
            if (!isNavGroup(entry)) {
              return (
                <li key={entry.href}>
                  <SidebarLink item={entry} active={isActive(entry.href)} />
                </li>
              );
            }
            const open = isOpen(entry);
            const active = groupHasActive(entry);
            const groupBadge = entry.items.reduce((s, i) => s + (i.badge ?? 0), 0);
            const GroupIcon = entry.icon;
            return (
              <li key={entry.group}>
                <button
                  type="button"
                  onClick={() => toggle(entry)}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                    active
                      ? "text-foreground"
                      : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                  )}
                >
                  <GroupIcon className="h-4 w-4 shrink-0" />
                  <span className="flex-1 text-left">{entry.group}</span>
                  {groupBadge > 0 && !open && (
                    <span className="flex h-5 min-w-[20px] items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-bold text-white">
                      {groupBadge > 99 ? "99+" : groupBadge}
                    </span>
                  )}
                  <ChevronDown
                    className={cn("h-4 w-4 shrink-0 transition-transform", open && "rotate-180")}
                  />
                </button>
                {open && (
                  <ul className="mt-1 space-y-1 border-l border-border/60 pl-3">
                    {entry.items.map((item) => (
                      <li key={item.href}>
                        <SidebarLink item={item} active={isActive(item.href)} />
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      </nav>
    </aside>
  );
}

function SidebarLink({ item, active }: { item: NavItem; active: boolean }) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      className={cn(
        "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
        active
          ? "bg-primary text-primary-foreground"
          : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
      )}
    >
      <Icon className="h-4 w-4 shrink-0" />
      <span className="flex-1">{item.label}</span>
      {typeof item.badge === "number" && item.badge > 0 && (
        <span className="ml-auto flex h-5 min-w-[20px] items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-bold text-white">
          {item.badge > 99 ? "99+" : item.badge}
        </span>
      )}
    </Link>
  );
}
