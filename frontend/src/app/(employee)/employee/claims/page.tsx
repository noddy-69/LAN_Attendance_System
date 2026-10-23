"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Receipt, Paperclip, Upload, X } from "lucide-react";
import { useAuthStore } from "@/stores/auth-store";
import { useMe } from "@/hooks/use-auth";
import { apiGet, apiPost, apiDelete, api } from "@/lib/api";
import { EmployeeLayout } from "@/components/employee/EmployeeLayout";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Sheet, SheetContent, SheetHeader, SheetTitle,
} from "@/components/ui/sheet";
import { istDateStr, formatDate, formatPaise } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Claim {
  id: string;
  title: string;
  description: string | null;
  amount_paise: number;
  category: string;
  expense_date: string;
  status: string;
  document_count: number;
  manager_remarks: string | null;
  hr_remarks: string | null;
  created_at: string;
}

// value = backend ReimbursementCategory enum value (lowercase); label = display text.
// The form must submit the value — the API validates the enum by value, not label.
const CATEGORIES: { value: string; label: string }[] = [
  { value: "travel",          label: "Travel" },
  { value: "food",            label: "Food & Meals" },
  { value: "accommodation",   label: "Accommodation" },
  { value: "medical",         label: "Medical" },
  { value: "office_supplies", label: "Office Supplies" },
  { value: "other",           label: "Other" },
];

const CATEGORY_LABELS: Record<string, string> = Object.fromEntries(
  CATEGORIES.map((c) => [c.value, c.label]),
);

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ClaimsPage() {
  const router = useRouter();
  const { isAuthenticated } = useAuthStore();
  const { data: user, isLoading: userLoading } = useMe();
  const qc = useQueryClient();

  const [formOpen, setFormOpen] = useState(false);
  const [title, setTitle]       = useState("");
  const [desc, setDesc]         = useState("");
  const [amountRs, setAmountRs] = useState("");  // user enters ₹
  const [category, setCategory] = useState("");
  const [expDate, setExpDate]   = useState("");
  const [receipt, setReceipt]   = useState<File | null>(null);
  const [formErr, setFormErr]   = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!isAuthenticated && !userLoading) router.replace("/login");
  }, [isAuthenticated, userLoading, router]);

  const { data: claimsResp, isLoading } = useQuery({
    queryKey: ["emp-claims"],
    queryFn: () => apiGet<Claim[]>("/reimbursements", { per_page: 30 }),
    enabled: !!user?.id,
  });

  const { mutate: submit, isPending: submitting } = useMutation({
    mutationFn: async () => {
      const amountPaise = Math.round(parseFloat(amountRs) * 100);
      const claimRes = await apiPost<Claim>("/reimbursements", {
        title: title.trim(),
        description: desc.trim() || null,
        amount_paise: amountPaise,
        category,
        expense_date: expDate,
      });
      if (!claimRes.success || !claimRes.data) throw new Error(claimRes.error ?? "Submit failed");
      const claimId = claimRes.data.id;

      // Upload receipt if provided
      if (receipt) {
        const fd = new FormData();
        fd.append("file", receipt);
        await api.post(`/reimbursements/${claimId}/receipts`, fd, {
          headers: { "Content-Type": "multipart/form-data" },
        });
      }
      return claimId;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["emp-claims"] });
      setFormOpen(false);
      resetForm();
    },
    onError: (e: Error) => setFormErr(e.message ?? "Failed to submit"),
  });

  const { mutate: deleteClaim } = useMutation({
    mutationFn: (id: string) => apiDelete(`/reimbursements/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["emp-claims"] }),
  });

  function resetForm() {
    setTitle(""); setDesc(""); setAmountRs(""); setCategory(""); setExpDate("");
    setReceipt(null); setFormErr("");
    if (fileRef.current) fileRef.current.value = "";
  }

  function handleSubmit() {
    setFormErr("");
    if (!title.trim())   return setFormErr("Title is required");
    const amt = parseFloat(amountRs);
    if (isNaN(amt) || amt <= 0) return setFormErr("Enter a valid amount in ₹");
    if (!category)       return setFormErr("Select a category");
    if (!expDate)        return setFormErr("Select expense date");
    submit();
  }

  const today = istDateStr();

  if (userLoading || !user) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    );
  }

  const claims = claimsResp?.data ?? [];

  return (
    <EmployeeLayout pageTitle="Claims">
      <div className="mx-auto max-w-xl space-y-5">

        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-bold">Reimbursements</h2>
            <p className="text-xs text-muted-foreground">Submit and track expense claims</p>
          </div>
          <Button onClick={() => setFormOpen(true)} size="sm" className="h-10 px-4">
            + New Claim
          </Button>
        </div>

        {/* Claims list */}
        {isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-24 rounded-xl" />
            ))}
          </div>
        ) : claims.length === 0 ? (
          <div className="flex flex-col items-center rounded-xl border border-dashed py-12 text-muted-foreground">
            <Receipt className="mb-2 h-8 w-8 opacity-40" />
            <p className="text-sm">No claims submitted yet.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {claims.map(claim => (
              <div key={claim.id} className="rounded-xl border bg-card p-4 shadow-sm">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{claim.title}</span>
                      <StatusBadge status={claim.status} />
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-sm text-muted-foreground">
                      <span className="font-semibold text-foreground">
                        {formatPaise(claim.amount_paise)}
                      </span>
                      <span>{CATEGORY_LABELS[claim.category] ?? claim.category}</span>
                      <span>{formatDate(claim.expense_date)}</span>
                    </div>
                    {claim.description && (
                      <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                        {claim.description}
                      </p>
                    )}
                    {claim.document_count > 0 && (
                      <div className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
                        <Paperclip className="h-3 w-3" />
                        {claim.document_count} receipt{claim.document_count !== 1 ? "s" : ""}
                      </div>
                    )}
                    {(claim.manager_remarks || claim.hr_remarks) && (
                      <p className="mt-1.5 text-xs italic text-muted-foreground">
                        {claim.hr_remarks ?? claim.manager_remarks}
                      </p>
                    )}
                  </div>
                  {["pending_manager", "pending_hr"].includes(claim.status) && (
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 shrink-0 text-muted-foreground hover:text-destructive"
                      title="Delete claim"
                      onClick={() => deleteClaim(claim.id)}
                    >
                      <X className="h-4 w-4" />
                      <span className="sr-only">Delete</span>
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Claim form sheet */}
      <Sheet open={formOpen} onOpenChange={v => { if (!submitting) { setFormOpen(v); if (!v) resetForm(); } }}>
        <SheetContent side="bottom" className="max-h-[92vh] rounded-t-2xl overflow-y-auto">
          <SheetHeader className="mb-5">
            <SheetTitle>New Expense Claim</SheetTitle>
          </SheetHeader>

          <div className="space-y-4 pb-4">
            {/* Title */}
            <div className="space-y-1.5">
              <Label htmlFor="claim-title">Title</Label>
              <Input
                id="claim-title"
                placeholder="e.g. Client lunch, Train ticket…"
                value={title}
                onChange={e => setTitle(e.target.value)}
                className="h-12"
              />
            </div>

            {/* Amount + Category */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="amount">Amount (₹)</Label>
                <Input
                  id="amount"
                  type="number"
                  inputMode="decimal"
                  placeholder="0.00"
                  min="0"
                  step="0.01"
                  value={amountRs}
                  onChange={e => setAmountRs(e.target.value)}
                  className="h-12"
                />
              </div>
              <div className="space-y-1.5">
                <Label>Category</Label>
                <Select value={category} onValueChange={setCategory}>
                  <SelectTrigger className="h-12">
                    <SelectValue placeholder="Category…" />
                  </SelectTrigger>
                  <SelectContent>
                    {CATEGORIES.map(c => (
                      <SelectItem key={c.value} value={c.value}>{c.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Date */}
            <div className="space-y-1.5">
              <Label htmlFor="exp-date">Expense Date</Label>
              <Input
                id="exp-date"
                type="date"
                max={today}
                value={expDate}
                onChange={e => setExpDate(e.target.value)}
                className="h-12"
              />
            </div>

            {/* Description */}
            <div className="space-y-1.5">
              <Label htmlFor="desc">Description (optional)</Label>
              <Textarea
                id="desc"
                placeholder="Details about the expense…"
                value={desc}
                onChange={e => setDesc(e.target.value)}
                rows={2}
                className="resize-none"
              />
            </div>

            {/* Receipt upload */}
            <div className="space-y-1.5">
              <Label>Receipt (optional)</Label>
              <button
                type="button"
                onClick={() => fileRef.current?.click()}
                className="flex h-12 w-full items-center gap-3 rounded-md border border-dashed px-3 text-sm text-muted-foreground transition-colors hover:border-primary hover:text-primary active:bg-muted"
              >
                <Upload className="h-4 w-4 shrink-0" />
                {receipt ? (
                  <span className="truncate text-foreground">{receipt.name}</span>
                ) : (
                  "Upload image or PDF (max 10 MB)"
                )}
              </button>
              <input
                ref={fileRef}
                type="file"
                accept="image/*,application/pdf"
                className="hidden"
                onChange={e => setReceipt(e.target.files?.[0] ?? null)}
              />
            </div>

            {formErr && (
              <p className="text-sm font-medium text-destructive">{formErr}</p>
            )}

            <Button
              className="h-12 w-full text-base"
              onClick={handleSubmit}
              disabled={submitting}
            >
              {submitting ? "Submitting…" : "Submit Claim"}
            </Button>
          </div>
        </SheetContent>
      </Sheet>
    </EmployeeLayout>
  );
}
