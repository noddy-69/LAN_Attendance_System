"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { Navbar } from "@/components/shared/navbar";
import { Sidebar } from "@/components/shared/sidebar";
import { EMP_NAV } from "@/components/employee/nav";

interface EmployeeLayoutProps {
  children: React.ReactNode;
  pageTitle?: string;
}

export function EmployeeLayout({ children, pageTitle }: EmployeeLayoutProps) {
  const pathname = usePathname();

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Desktop sidebar — the Sidebar component is already hidden on mobile via its own hidden md:flex */}
      <Sidebar items={EMP_NAV} portalLabel="Employee" />

      <div className="flex flex-1 flex-col overflow-hidden">
        <Navbar title={pageTitle} />

        {/* Main scroll area — extra bottom padding on mobile for the tab bar */}
        <main className="flex-1 overflow-y-auto p-4 pb-20 md:p-6 md:pb-6">
          {children}
        </main>

        {/* Mobile bottom tab bar — hidden on md+ where the sidebar takes over */}
        <nav className="fixed inset-x-0 bottom-0 z-40 flex border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80 md:hidden">
          {EMP_NAV.map((item) => {
            const Icon = item.icon;
            const active =
              pathname === item.href ||
              (item.href !== "/employee/dashboard" && pathname.startsWith(item.href));
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex min-h-[56px] flex-1 flex-col items-center justify-center gap-1 px-1 text-[10px] font-medium transition-colors",
                  active ? "text-primary" : "text-muted-foreground"
                )}
                aria-current={active ? "page" : undefined}
              >
                <Icon className={cn("h-[22px] w-[22px] shrink-0", active && "text-primary")} />
                <span className="w-full truncate text-center leading-tight">
                  {item.label}
                </span>
              </Link>
            );
          })}
        </nav>
      </div>
    </div>
  );
}
