"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Download, FileSpreadsheet, FileText } from "lucide-react";

import { PortalLayout } from "@/components/shared/Layout";
import { HR_NAV } from "@/components/hr/nav";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { istDateStr, downloadFile } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth-store";
import { API_BASE } from "@/lib/constants";

const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const STATUSES_ATT = ["PRESENT","ABSENT","LATE","HALF_DAY","ON_LEAVE","HOLIDAY","WEEKEND","PENDING_CORRECTION"];
const STATUSES_LEAVE = ["pending_manager","pending_hr","approved","rejected","cancelled"];

export default function HRReportsPage() {
  const { token } = useAuthStore();

  // Attendance report state
  const [attFrom, setAttFrom] = useState(() => { const d=new Date(); d.setDate(1); return istDateStr(d); });
  const [attTo, setAttTo] = useState(istDateStr());
  const [attStatus, setAttStatus] = useState("all");
  const [attFormat, setAttFormat] = useState<"xlsx"|"csv">("xlsx");
  const [attLoading, setAttLoading] = useState(false);

  // Leave report state
  const [leaveFrom, setLeaveFrom] = useState(() => { const d=new Date(); d.setDate(1); return istDateStr(d); });
  const [leaveTo, setLeaveTo] = useState(istDateStr());
  const [leaveStatus, setLeaveStatus] = useState("all");
  const [leaveFormat, setLeaveFormat] = useState<"xlsx"|"csv">("xlsx");
  const [leaveLoading, setLeaveLoading] = useState(false);

  // Payroll report state
  const [payMonth, setPayMonth] = useState(String(new Date().getMonth() + 1));
  const [payYear, setPayYear] = useState(String(new Date().getFullYear()));
  const [payFormat, setPayFormat] = useState<"xlsx"|"csv">("xlsx");
  const [payLoading, setPayLoading] = useState(false);

  const dl = async (url: string, filename: string, setLoading: (v: boolean) => void) => {
    setLoading(true);
    try { await downloadFile(url, filename, token); }
    catch (e: unknown) { toast.error((e as Error).message || "Download failed"); }
    finally { setLoading(false); }
  };

  const downloadAttendance = () => {
    const params = new URLSearchParams({ format: attFormat, from_date: attFrom, to_date: attTo });
    if (attStatus !== "all") params.append("status", attStatus);
    dl(`${API_BASE}/reports/attendance?${params}`, `attendance_${attFrom}_${attTo}.${attFormat}`, setAttLoading);
  };

  const downloadLeave = () => {
    const params = new URLSearchParams({ format: leaveFormat, from_date: leaveFrom, to_date: leaveTo });
    if (leaveStatus !== "all") params.append("status", leaveStatus);
    dl(`${API_BASE}/reports/leave?${params}`, `leave_${leaveFrom}_${leaveTo}.${leaveFormat}`, setLeaveLoading);
  };

  const downloadPayroll = () => {
    const params = new URLSearchParams({ format: payFormat, month: payMonth, year: payYear });
    dl(`${API_BASE}/reports/payroll?${params}`, `payroll_${payYear}_${String(payMonth).padStart(2,"0")}.${payFormat}`, setPayLoading);
  };

  const FormatPicker = ({ value, onChange }: { value: string; onChange: (v: "xlsx"|"csv") => void }) => (
    <Select value={value} onValueChange={v => onChange(v as "xlsx"|"csv")}>
      <SelectTrigger className="w-28"><SelectValue /></SelectTrigger>
      <SelectContent>
        <SelectItem value="xlsx"><span className="flex items-center gap-1"><FileSpreadsheet className="h-3 w-3" /> Excel</span></SelectItem>
        <SelectItem value="csv"><span className="flex items-center gap-1"><FileText className="h-3 w-3" /> CSV</span></SelectItem>
      </SelectContent>
    </Select>
  );

  return (
    <PortalLayout navItems={HR_NAV} portalLabel="HR" pageTitle="Reports">
      <div className="space-y-4">
        <div>
          <h2 className="text-2xl font-bold">Reports</h2>
          <p className="text-sm text-muted-foreground">Export attendance, leave, and payroll data as Excel or CSV</p>
        </div>

        <Tabs defaultValue="attendance">
          <TabsList>
            <TabsTrigger value="attendance">Attendance</TabsTrigger>
            <TabsTrigger value="leave">Leave</TabsTrigger>
            <TabsTrigger value="payroll">Payroll</TabsTrigger>
          </TabsList>

          <TabsContent value="attendance" className="mt-4">
            <div className="rounded-lg border bg-card p-6 max-w-lg space-y-4">
              <h3 className="font-semibold">Attendance Report</h3>
              <p className="text-sm text-muted-foreground">
                Columns: Employee Name, Employee Code, Date, Check-In (IST), Check-Out (IST), Work Hours, Status, Is Late, Late Minutes, Overtime, Source
              </p>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1"><Label>From Date</Label><Input type="date" value={attFrom} onChange={e => setAttFrom(e.target.value)} /></div>
                <div className="space-y-1"><Label>To Date</Label><Input type="date" value={attTo} onChange={e => setAttTo(e.target.value)} /></div>
              </div>
              <div className="flex gap-3">
                <div className="flex-1 space-y-1"><Label>Status Filter</Label>
                  <Select value={attStatus} onValueChange={setAttStatus}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent><SelectItem value="all">All statuses</SelectItem>{STATUSES_ATT.map(s => <SelectItem key={s} value={s}>{s.replace("_"," ")}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <div className="space-y-1"><Label>Format</Label><FormatPicker value={attFormat} onChange={setAttFormat} /></div>
              </div>
              <Button onClick={downloadAttendance} disabled={attLoading} className="w-full">
                <Download className="mr-2 h-4 w-4" />{attLoading ? "Downloading…" : `Download Attendance (${attFormat.toUpperCase()})`}
              </Button>
            </div>
          </TabsContent>

          <TabsContent value="leave" className="mt-4">
            <div className="rounded-lg border bg-card p-6 max-w-lg space-y-4">
              <h3 className="font-semibold">Leave Report</h3>
              <p className="text-sm text-muted-foreground">
                Columns: Employee Name, Employee Code, Leave Type, Leave Code, Start Date, End Date, Days, Status, Reason, Manager, HR, Remarks
              </p>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1"><Label>From Date</Label><Input type="date" value={leaveFrom} onChange={e => setLeaveFrom(e.target.value)} /></div>
                <div className="space-y-1"><Label>To Date</Label><Input type="date" value={leaveTo} onChange={e => setLeaveTo(e.target.value)} /></div>
              </div>
              <div className="flex gap-3">
                <div className="flex-1 space-y-1"><Label>Status Filter</Label>
                  <Select value={leaveStatus} onValueChange={setLeaveStatus}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent><SelectItem value="all">All statuses</SelectItem>{STATUSES_LEAVE.map(s => <SelectItem key={s} value={s}>{s.replace("_"," ")}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <div className="space-y-1"><Label>Format</Label><FormatPicker value={leaveFormat} onChange={setLeaveFormat} /></div>
              </div>
              <Button onClick={downloadLeave} disabled={leaveLoading} className="w-full">
                <Download className="mr-2 h-4 w-4" />{leaveLoading ? "Downloading…" : `Download Leave (${leaveFormat.toUpperCase()})`}
              </Button>
            </div>
          </TabsContent>

          <TabsContent value="payroll" className="mt-4">
            <div className="rounded-lg border bg-card p-6 max-w-lg space-y-4">
              <h3 className="font-semibold">Payroll Deduction Report</h3>
              <p className="text-sm text-muted-foreground">
                Columns: Employee Name, Employee Code, Month, Year, Days Present/Absent/Leave, Late Count, Allowed, Excess, Penalty per Late (₹), Total Deduction (₹)
              </p>
              <div className="flex gap-3">
                <div className="flex-1 space-y-1"><Label>Month</Label>
                  <Select value={payMonth} onValueChange={setPayMonth}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>{MONTHS.map((m,i) => <SelectItem key={i+1} value={String(i+1)}>{m}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <div className="space-y-1"><Label>Year</Label><Input type="number" value={payYear} onChange={e => setPayYear(e.target.value)} className="w-24" /></div>
                <div className="space-y-1"><Label>Format</Label><FormatPicker value={payFormat} onChange={setPayFormat} /></div>
              </div>
              <Button onClick={downloadPayroll} disabled={payLoading} className="w-full">
                <Download className="mr-2 h-4 w-4" />{payLoading ? "Downloading…" : `Download ${MONTHS[Number(payMonth)-1]} ${payYear} (${payFormat.toUpperCase()})`}
              </Button>
            </div>
          </TabsContent>
        </Tabs>
      </div>
    </PortalLayout>
  );
}
