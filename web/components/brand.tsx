import Link from "next/link";
import { cn } from "@/lib/utils";

/** Three ascending bars: durability, succession, upside. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={cn("size-6", className)}>
      <rect width="24" height="24" rx="6" className="fill-brand" />
      <rect x="5.5" y="12" width="3" height="6.5" rx="1" className="fill-white/70 dark:fill-black/55" />
      <rect x="10.5" y="8.5" width="3" height="10" rx="1" className="fill-white/85 dark:fill-black/70" />
      <rect x="15.5" y="5" width="3" height="13.5" rx="1" className="fill-white dark:fill-black/85" />
    </svg>
  );
}

export function Wordmark({ compact = false }: { compact?: boolean }) {
  return (
    <Link href="/" className="group flex items-center gap-2 rounded-md outline-offset-4">
      <LogoMark />
      <span className="font-semibold tracking-tight">Buy &amp; Build Score</span>
      {!compact && (
        <span className="hidden text-muted-foreground sm:inline">
          <span className="mx-1.5 text-line">/</span>for SaaSquatch Leads
        </span>
      )}
    </Link>
  );
}
