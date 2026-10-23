"use client";
export default function Error({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <div className="flex h-screen flex-col items-center justify-center gap-4">
      <p className="text-muted-foreground">{error.message || "Something went wrong"}</p>
      <button onClick={reset} className="underline text-sm">Try again</button>
    </div>
  );
}
