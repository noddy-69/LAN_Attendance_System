"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { Users, Clock, CalendarCheck, Receipt, AlertCircle, CheckCircle2, FileText } from "lucide-react";
import Link from "next/link";

import { PortalLayout } from "@/components/shared/Layout";
import { HR_NAV } from "@/components/hr/nav";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/stores/auth-store";
import { apiGet } from "@/lib/api";
import { istDateStr } from "@/lib/utils";

interface DailyAtt { id: string; employee_id: string; status: string; is_late: boolean; date: string }
interface LeaveReq { id: string; employee_name: string; leave_type_name: string; start_date: string; end_date: string; days_requested: number; status: string }
interface Reimbursement { id: string; employee_name: string; title: string; amount_paise: number; status: string }
interface Correction { daily_id: string; employee_id: string; date: string; correction_status: string; reason: string }

function StatCard({ label, value, icon: Icon, href, color }: { label: string; value: string | number; icon: React.ElementType; href: string; color: string }) {
  return (
    <Link href={href} className="block rounded-lg border bg-card p-6 shadow-sm transition-shadow hover:shadow-md">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-muted-foreground">{label}</p>
        <Icon className={`h-4 w-4 ${color}`} />
      </div>
      <p className="mt-2 text-3xl font-bold">{value}</p>
    </Link>
  );
}

export default function HRDashboardPage() {
  const router = useRouter();
  const { isAuthenticated } = useAuthStore();
  useEffect(() => { if (!isAuthenticated) router.replace("/login"); }, [isAuthenticated, router]);

  const today = istDateStr();

  const { data: attResp, isLoading: attLoading } = useQuery({
    queryKey: ["hr-att-today"],
    queryFn: () => apiGet<DailyAtt[]>("/attendance/daily", { from_date: today, to_date: today, per_page: 100 }),
  });

  const { data: leaveResp, isLoading: leaveLoading } = useQuery({
    queryKey: ["hr-leave-pending"],
    queryFn: () => apiGet<LeaveReq[]>("/leave/requests", { per_page: 100 }),
  });

  const { data: reimbResp, isLoading: reimbLoading } = useQuery({
    queryKey: ["hr-reimb-pending"],
    queryFn: () => apiGet<Reimbursement[]>("/reimbursements", { per_page: 100 }),
  });

  const { data: corrResp, isLoading: corrLoading } = useQuery({
    queryKey: ["hr-corrections"],
    queryFn: () => apiGet<Correction[]>("/attendance/corrections"),
  });

  const todayAtt = attResp?.data ?? [];
  const present = todayAtt.filter(r => ["PRESENT","LATE","HALF_DAY"].includes(r.status)).length;
  const absent  = todayAtt.filter(r => r.status === "ABSENT").length;
  const late    = todayAtt.filter(r => r.is_late).length;
  // HR sees everything still pending — the manager stage AND the HR stage (they can
  // finalize either).
  const PENDING_REQ = ["pending_manager", "pending_hr"];
  const pendingLeaveList = (leaveResp?.data ?? []).filter(r => PENDING_REQ.includes(r.status));
  const pendingReimbList = (reimbResp?.data ?? []).filter(r => PENDING_REQ.includes(r.status));
  const pendingCorrList  = (corrResp?.data ?? []).filter(c => c.correction_status === "pending" || c.correction_status === "pending_hr");
  const pendingLeave  = pendingLeaveList.length;
  const pendingCorr   = pendingCorrList.length;

  return (
    <PortalLayout navItems={HR_NAV} portalLabel="HR" pageTitle="HR Dashboard">
      <div className="space-y-6">
        <div>
          <h2 className="text-2xl font-bold">HR Operations</h2>
          <p className="text-sm text-muted-foreground">Today: {new Date().toLocaleDateString("en-IN", { weekday:"long", day:"2-digit", month:"long", year:"numeric" })}</p>
        </div>

        {/* Today's summary */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {attLoading ? Array.from({length:4}).map((_,i) => <Skeleton key={i} className="h-28 rounded-lg" />) : <>
            <StatCard label="Present Today" value={present} icon={CheckCircle2} href="/hr/attendance" color="text-green-500" />
            <StatCard label="Absent Today"  value={absent}  icon={AlertCircle}  href="/hr/attendance" color="text-red-500" />
            <StatCard label="Late Today"    value={late}    icon={Clock}        href="/hr/attendance" color="text-yellow-500" />
            <StatCard label="Leave Pending" value={pendingLeave} icon={CalendarCheck} href="/hr/leave" color="text-blue-500" />
          </>}
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          {/* Pending Leave Approvals */}
          <div className="rounded-lg border bg-card p-6 shadow-sm">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="font-semibold">Pending Leave Approvals</h3>
              <Button variant="ghost" size="sm" asChild><Link href="/hr/leave">View all</Link></Button>
            </div>
            {leaveLoading ? <Skeleton className="h-32 w-full" /> : (
              pendingLeaveList.length === 0
                ? <p className="text-sm text-muted-foreground">No pending approvals</p>
                : <ul className="space-y-3">
                    {pendingLeaveList.slice(0, 5).map(r => (
                      <li key={r.id} className="flex items-center justify-between text-sm">
                        <div>
                          <p className="font-medium">{r.employee_name}</p>
                          <p className="text-xs text-muted-foreground">{r.leave_type_name} · {r.days_requested}d · {r.start_date}</p>
                        </div>
                        <StatusBadge status={r.status} />
                      </li>
                    ))}
                  </ul>
            )}
          </div>

          {/* Pending Reimbursements */}
          <div className="rounded-lg border bg-card p-6 shadow-sm">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="font-semibold">Pending Reimbursements</h3>
              <Button variant="ghost" size="sm" asChild><Link href="/hr/reimbursements">View all</Link></Button>
            </div>
            {reimbLoading ? <Skeleton className="h-32 w-full" /> : (
              pendingReimbList.length === 0
                ? <p className="text-sm text-muted-foreground">No pending reimbursements</p>
                : <ul className="space-y-3">
                    {pendingReimbList.slice(0, 5).map(r => (
                      <li key={r.id} className="flex items-center justify-between text-sm">
                        <div>
                          <p className="font-medium">{r.employee_name}</p>
                          <p className="text-xs text-muted-foreground">{r.title} · ₹{(r.amount_paise/100).toFixed(2)}</p>
                        </div>
                        <StatusBadge status={r.status} />
                      </li>
                    ))}
                  </ul>
            )}
          </div>

          {/* Pending Corrections */}
          <div className="rounded-lg border bg-card p-6 shadow-sm">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="font-semibold">Correction Requests ({pendingCorr})</h3>
              <Button variant="ghost" size="sm" asChild><Link href="/hr/attendance">Review</Link></Button>
            </div>
            {corrLoading ? <Skeleton className="h-20 w-full" /> : (
              pendingCorrList.length === 0
                ? <p className="text-sm text-muted-foreground">No pending corrections</p>
                : <ul className="space-y-2">
                    {pendingCorrList.slice(0, 4).map(c => (
                      <li key={c.daily_id} className="text-sm">
                        <p className="font-medium">{c.date}</p>
                        <p className="text-xs text-muted-foreground truncate">{c.reason}</p>
                      </li>
                    ))}
                  </ul>
            )}
          </div>

          {/* Quick actions */}
          <div className="rounded-lg border bg-card p-6 shadow-sm">
            <h3 className="mb-4 font-semibold">Quick Actions</h3>
            <div className="grid grid-cols-2 gap-3">
              <Button variant="outline" asChild className="h-auto flex-col gap-1 py-3">
                <Link href="/hr/employees"><Users className="h-4 w-4" /><span className="text-xs">Add Employee</span></Link>
              </Button>
              <Button variant="outline" asChild className="h-auto flex-col gap-1 py-3">
                <Link href="/hr/leave"><CalendarCheck className="h-4 w-4" /><span className="text-xs">Approve Leave</span></Link>
              </Button>
              <Button variant="outline" asChild className="h-auto flex-col gap-1 py-3">
                <Link href="/hr/payroll"><Receipt className="h-4 w-4" /><span className="text-xs">Run Payroll</span></Link>
              </Button>
              <Button variant="outline" asChild className="h-auto flex-col gap-1 py-3">
                <Link href="/hr/reports"><FileText className="h-4 w-4" /><span className="text-xs">Download Reports</span></Link>
              </Button>
            </div>
          </div>
        </div>
      </div>
    </PortalLayout>
  );
}
