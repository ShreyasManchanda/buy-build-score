"use client";

import { ArrowUpRightIcon, PlayIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { CsvDrop } from "@/components/csv-drop";
import { ThesisForm } from "@/components/thesis-form";
import type { Preset } from "@/lib/types";

export function ThesisScreen() {
  const [preset, setPreset] = useState<Preset>("searcher");
  return (
    <div className="grid gap-6">
      <div className="rounded-xl border bg-surface p-5 sm:p-6">
        <ThesisForm preset={preset} onPresetChange={setPreset} />
      </div>
      <div className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-start">
        <CsvDrop preset={preset} />
        <Link
          href="/runs/demo"
          className="group flex items-center gap-3 rounded-lg border px-4 py-3 transition-colors hover:border-foreground/30 hover:bg-surface"
        >
          <PlayIcon className="size-4 shrink-0 text-muted-foreground" />
          <span className="flex flex-col">
            <span className="flex items-center gap-1 text-sm font-medium">
              Try the demo run
              <ArrowUpRightIcon className="size-3.5 text-muted-foreground transition-transform group-hover:-translate-y-px group-hover:translate-x-px" />
            </span>
            <span className="text-xs text-muted-foreground">Real Columbus run · no keys needed</span>
          </span>
        </Link>
      </div>
    </div>
  );
}
