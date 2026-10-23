"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import { ChevronLeft, ChevronRight, FileText, ExternalLink } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { formatDateTime } from "@/lib/utils";

interface ProofItem {
  url: string;
  proof_type?: string;
  captured_at?: string;
  mime_type?: string;
}

interface ProofImageModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  // Multi-image mode: pass every proof to browse them (entry + exit, or receipts).
  proofs?: ProofItem[];
  // Single-image mode (kept for existing callers):
  src?: string | null;
  title?: string;
  timestamp?: string;
}

function labelFor(t?: string): string {
  if (!t) return "Proof";
  const s = t.toLowerCase();
  if (s.includes("entry")) return "Entry Proof";
  if (s.includes("exit")) return "Exit Proof";
  return t.charAt(0).toUpperCase() + t.slice(1);
}

function isPdf(it?: ProofItem): boolean {
  if (!it) return false;
  return (it.mime_type ?? "").toLowerCase().includes("pdf") ||
    (it.url ?? "").toLowerCase().includes(".pdf");
}

export function ProofImageModal({
  open,
  onOpenChange,
  proofs,
  src,
  title = "Proof",
  timestamp,
}: ProofImageModalProps) {
  // Normalise inputs to a single list. Multi-image mode takes precedence; otherwise
  // fall back to the single src/title/timestamp the older callers pass.
  const multiMode = !!proofs && proofs.length > 0;
  const items: ProofItem[] = multiMode
    ? proofs!
    : src
    ? [{ url: src, proof_type: title, captured_at: timestamp }]
    : [];

  const [idx, setIdx] = useState(0);
  // Reset to the first image whenever the dialog opens or the image set changes.
  useEffect(() => {
    if (open) setIdx(0);
  }, [open, items.length]);

  const current = items[Math.min(idx, Math.max(0, items.length - 1))];
  const many = items.length > 1;
  const heading = multiMode ? labelFor(current?.proof_type) : title;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center justify-between gap-2">
            <span>
              {heading}
              {many ? ` (${idx + 1} of ${items.length})` : ""}
            </span>
            {current?.url && (
              <a
                href={current.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-xs font-normal text-primary hover:underline"
              >
                Open in new tab <ExternalLink className="h-3 w-3" />
              </a>
            )}
          </DialogTitle>
          {current?.captured_at && (
            <p className="text-sm text-muted-foreground">{formatDateTime(current.captured_at)}</p>
          )}
        </DialogHeader>

        <div className="relative aspect-video w-full overflow-hidden rounded-md bg-muted">
          {current?.url ? (
            isPdf(current) ? (
              <a
                href={current.url}
                target="_blank"
                rel="noopener noreferrer"
                className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-primary"
              >
                <FileText className="h-10 w-10" />
                <span className="text-sm font-medium underline">Open PDF document</span>
              </a>
            ) : (
              <a
                href={current.url}
                target="_blank"
                rel="noopener noreferrer"
                title="Click to open full-size in a new tab"
                className="absolute inset-0"
              >
                <Image
                  src={current.url}
                  alt={heading}
                  fill
                  className="object-contain"
                  unoptimized // presigned URLs include query params; bypass Next.js image optimizer
                />
              </a>
            )
          ) : (
            <div className="flex h-full items-center justify-center text-muted-foreground">
              No image available
            </div>
          )}

          {many && (
            <>
              <Button
                type="button"
                variant="secondary"
                size="icon"
                aria-label="Previous proof"
                className="absolute left-2 top-1/2 z-10 h-8 w-8 -translate-y-1/2 rounded-full opacity-90"
                onClick={() => setIdx((i) => (i - 1 + items.length) % items.length)}
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <Button
                type="button"
                variant="secondary"
                size="icon"
                aria-label="Next proof"
                className="absolute right-2 top-1/2 z-10 h-8 w-8 -translate-y-1/2 rounded-full opacity-90"
                onClick={() => setIdx((i) => (i + 1) % items.length)}
              >
                <ChevronRight className="h-4 w-4" />
              </Button>
            </>
          )}
        </div>

        {many && (
          <div className="flex flex-wrap justify-center gap-2">
            {items.map((p, i) => (
              <button
                key={i}
                type="button"
                onClick={() => setIdx(i)}
                className={`max-w-[10rem] truncate rounded-full px-3 py-1 text-xs font-medium capitalize transition-colors ${
                  i === idx
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-muted-foreground hover:bg-muted/70"
                }`}
              >
                {labelFor(p.proof_type).replace(" Proof", "")}
              </button>
            ))}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
