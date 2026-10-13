"use client";

import { CheckIcon, FileSpreadsheetIcon, Loader2Icon, UploadIcon, XIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api";
import { mapHeaders, sniffCsv } from "@/lib/thesis";
import type { Preset } from "@/lib/types";
import { cn } from "@/lib/utils";

const FIELD_LABEL: Record<string, string> = {
  name: "Company",
  website: "Website",
  phone: "Phone",
  city: "City",
  region: "State",
  location: "Location",
  postcode: "ZIP",
  email: "Email",
  revenue_est: "Revenue (kept, not scored)",
  industry: "Industry",
};

interface Preview {
  file: File;
  rows: number;
  mapping: Record<string, string>;
  unmapped: string[];
  ok: boolean;
}

export function CsvDrop({ preset }: { preset: Preset }) {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);

  async function read(file: File) {
    if (file.size > 2 * 1024 * 1024) {
      toast.error("CSV is larger than 2 MB", { description: "Split it into smaller files (≤ 500 rows each)." });
      return;
    }
    const { headers, rows } = sniffCsv(await file.text());
    const { mapping, unmapped } = mapHeaders(headers);
    const ok = Boolean(mapping.website || (mapping.name && (mapping.city || mapping.location)));
    setPreview({ file, rows, mapping, unmapped, ok });
  }

  async function submit() {
    if (!preview) return;
    setBusy(true);
    try {
      const r = await api.createCsvRun(preview.file, preset);
      if (r.rows_rejected) toast.message(`${r.rows_rejected} rows skipped`, { description: "They had no website and no company name + city." });
      router.push(`/runs/${r.run_id}`);
    } catch (err) {
      const e = err as ApiError;
      toast.error(e.title, { description: e.detail });
      setBusy(false);
    }
  }

  if (preview) {
    return (
      <div className="flex flex-col gap-3 rounded-lg border bg-surface p-4">
        <div className="flex items-center gap-2">
          <FileSpreadsheetIcon className="size-4 text-muted-foreground" />
          <span className="truncate text-sm font-medium">{preview.file.name}</span>
          <span className="font-mono text-xs text-muted-foreground">{preview.rows} rows</span>
          <Button variant="ghost" size="icon-xs" className="ml-auto" onClick={() => setPreview(null)} aria-label="Remove file">
            <XIcon />
          </Button>
        </div>
        <ul className="grid gap-1 text-xs sm:grid-cols-2">
          {Object.entries(preview.mapping).map(([field, header]) => (
            <li key={field} className="flex items-center gap-1.5">
              <CheckIcon className="size-3 text-tier-a" />
              <span className="truncate text-muted-foreground">{header}</span>
              <span className="text-muted-foreground/60">→</span>
              <span>{FIELD_LABEL[field] ?? field}</span>
            </li>
          ))}
        </ul>
        {preview.unmapped.length > 0 && (
          <p className="text-xs text-muted-foreground">
            Kept as-is: {preview.unmapped.slice(0, 6).join(", ")}
            {preview.unmapped.length > 6 ? ` +${preview.unmapped.length - 6}` : ""}
          </p>
        )}
        {!preview.ok && (
          <p className="text-xs text-warn">Needs a website column, or company name plus city.</p>
        )}
        <Button onClick={submit} disabled={!preview.ok || busy}>
          {busy && <Loader2Icon className="animate-spin" />}
          Score {Math.min(preview.rows, 500)} rows
        </Button>
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => input.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        setDrag(true);
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDrag(false);
        const f = e.dataTransfer.files?.[0];
        if (f) void read(f);
      }}
      className={cn(
        "flex w-full items-center gap-3 rounded-lg border border-dashed px-4 py-3 text-left transition-colors",
        drag ? "border-brand bg-brand-soft" : "hover:border-foreground/30 hover:bg-surface",
      )}
    >
      <UploadIcon className="size-4 shrink-0 text-muted-foreground" />
      <span className="flex flex-col">
        <span className="text-sm font-medium">Upload a SaaSquatch CSV</span>
        <span className="text-xs text-muted-foreground">Drop your export here · headers map automatically · ≤ 500 rows</span>
      </span>
      <input
        ref={input}
        type="file"
        accept=".csv,text/csv"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) void read(f);
          e.target.value = "";
        }}
      />
    </button>
  );
}
