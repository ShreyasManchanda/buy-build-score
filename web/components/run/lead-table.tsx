"use client";

import { type ColumnDef, flexRender, getCoreRowModel, useReactTable } from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ArrowDownIcon, ArrowUpIcon } from "lucide-react";
import { useRef } from "react";
import { EvidenceChip, MiniBars, TierBadge } from "@/components/score-ui";
import { Checkbox } from "@/components/ui/checkbox";
import type { Ranked } from "@/lib/score";
import { cn } from "@/lib/utils";
import { ContactIcons } from "./contact-icons";
import type { Sort, SortKey } from "./filters";

interface Props {
  rows: Ranked[];
  sort: Sort;
  onSort: (k: SortKey) => void;
  selected: Set<string>;
  onToggle: (id: string) => void;
  onToggleAll: (on: boolean) => void;
  onOpen: (id: string) => void;
  openId: string | null;
  fresh: Set<string>;
  showReviews: boolean;
  /** While rows stream in arrival order, no column is "sorted" — don't show an arrow. */
  sortActive?: boolean;
}

function SortHead({
  k,
  sort,
  onSort,
  children,
  className,
  enabled = true,
}: {
  k: SortKey;
  sort: Sort;
  enabled?: boolean;
  onSort: (k: SortKey) => void;
  children: React.ReactNode;
  className?: string;
}) {
  const active = enabled && sort.key === k;
  return (
    <button
      type="button"
      onClick={() => onSort(k)}
      className={cn(
        "inline-flex items-center gap-1 rounded px-0.5 hover:text-foreground",
        active && "text-foreground",
        className,
      )}
      aria-label={`Sort by ${typeof children === "string" ? children : k}${active ? (sort.desc ? ", descending" : ", ascending") : ""}`}
    >
      {children}
      {active && (sort.desc ? <ArrowDownIcon className="size-3" /> : <ArrowUpIcon className="size-3" />)}
    </button>
  );
}

export function LeadTable(p: Props) {
  const parent = useRef<HTMLDivElement>(null);
  const allOn = p.rows.length > 0 && p.rows.every((r) => p.selected.has(r.id));
  const someOn = !allOn && p.rows.some((r) => p.selected.has(r.id));

  const columns: ColumnDef<Ranked>[] = [
    {
      id: "select",
      header: () => (
        <Checkbox
          checked={allOn ? true : someOn ? "indeterminate" : false}
          onCheckedChange={(v) => p.onToggleAll(v === true)}
          aria-label="Select all shown"
        />
      ),
      cell: ({ row }) => (
        <Checkbox
          checked={p.selected.has(row.original.id)}
          onCheckedChange={() => p.onToggle(row.original.id)}
          onClick={(e) => e.stopPropagation()}
          aria-label={`Select ${row.original.name}`}
        />
      ),
    },
    {
      id: "tier",
      header: () => <span>Tier</span>,
      cell: ({ row }) => <TierBadge tier={row.original.tier} capped={row.original.capped} />,
    },
    {
      id: "company",
      header: () => (
        <SortHead k="name" sort={p.sort} onSort={p.onSort} enabled={p.sortActive !== false}>
          Company
        </SortHead>
      ),
      cell: ({ row }) => {
        const l = row.original;
        return (
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <span className="truncate font-medium">{l.name}</span>
              {l.thin_data && (
                <span className="shrink-0 rounded border border-dashed px-1 text-[10px] leading-4 text-muted-foreground">
                  thin data
                </span>
              )}
            </div>
            <div className="truncate text-xs text-muted-foreground">
              {[l.domain, l.city].filter(Boolean).join(" · ") || "No website"}
            </div>
          </div>
        );
      },
    },
    {
      id: "composite",
      header: () => (
        <SortHead k="composite" sort={p.sort} onSort={p.onSort} enabled={p.sortActive !== false} className="justify-end">
          Score
        </SortHead>
      ),
      cell: ({ row }) => (
        <span className="block text-right font-mono text-[15px] font-semibold tabular-nums">{row.original.composite}</span>
      ),
    },
    {
      id: "dsu",
      header: () => (
        <span className="flex items-center gap-2">
          <SortHead k="durability" sort={p.sort} onSort={p.onSort} enabled={p.sortActive !== false}>
            D
          </SortHead>
          <SortHead k="succession" sort={p.sort} onSort={p.onSort} enabled={p.sortActive !== false}>
            S
          </SortHead>
          <SortHead k="upside" sort={p.sort} onSort={p.onSort} enabled={p.sortActive !== false}>
            U
          </SortHead>
        </span>
      ),
      cell: ({ row }) => {
        const s = row.original.scores;
        return <MiniBars d={s.durability} s={s.succession} u={s.upside} />;
      },
    },
    {
      id: "founded",
      header: () => (
        <SortHead k="founded" sort={p.sort} onSort={p.onSort} enabled={p.sortActive !== false}>
          Founded
        </SortHead>
      ),
      cell: ({ row }) => (
        <span className="font-mono text-xs tabular-nums text-muted-foreground">{row.original.founded_year ?? "—"}</span>
      ),
    },
    ...(p.showReviews
      ? [
          {
            id: "reviews",
            header: () => <span>Reviews</span>,
            cell: ({ row }) =>
              row.original.rating !== null ? (
                <span className="font-mono text-xs tabular-nums">
                  ★ {row.original.rating.toFixed(1)}
                  <span className="text-muted-foreground"> · {row.original.review_count ?? 0}</span>
                </span>
              ) : (
                <span className="text-xs text-muted-foreground">—</span>
              ),
          } satisfies ColumnDef<Ranked>,
        ]
      : []),
    {
      id: "evidence",
      header: () => <span>Why</span>,
      cell: ({ row }) => (
        <div className="flex min-w-0 flex-wrap gap-1 overflow-hidden" style={{ maxHeight: 40 }}>
          {row.original.top_evidence.slice(0, 2).map((e) => (
            <EvidenceChip key={e}>{e}</EvidenceChip>
          ))}
          {row.original.top_evidence.length === 0 && <span className="text-xs text-muted-foreground">—</span>}
        </div>
      ),
    },
    {
      id: "contact",
      header: () => <span>Contact</span>,
      cell: ({ row }) => <ContactIcons lead={row.original} />,
    },
  ];

  // TanStack Table/Virtual return non-memoizable functions; the React Compiler skips this component (expected).
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({ data: p.rows, columns, getCoreRowModel: getCoreRowModel(), getRowId: (r) => r.id });
  const tableRows = table.getRowModel().rows;
  const virtual = useVirtualizer({
    count: tableRows.length,
    getScrollElement: () => parent.current,
    estimateSize: () => 56,
    overscan: 12,
  });

  const grid = p.showReviews
    ? "36px 40px minmax(180px,1.6fr) 56px 132px 64px 92px minmax(150px,1.3fr) 84px"
    : "36px 40px minmax(180px,1.6fr) 56px 132px 64px minmax(150px,1.4fr) 84px";

  return (
    <div ref={parent} className="relative h-full overflow-auto" role="table" aria-label="Ranked leads" aria-rowcount={tableRows.length}>
      <div
        role="row"
        className="sticky top-0 z-10 grid items-center gap-3 border-b bg-background/95 px-4 py-2 text-xs text-muted-foreground backdrop-blur sm:px-6"
        style={{ gridTemplateColumns: grid }}
      >
        {table.getHeaderGroups()[0].headers.map((h) => (
          <div key={h.id} role="columnheader" className={h.id === "composite" ? "text-right" : undefined}>
            {flexRender(h.column.columnDef.header, h.getContext())}
          </div>
        ))}
      </div>
      <div className="relative" style={{ height: virtual.getTotalSize() }}>
        {virtual.getVirtualItems().map((vi) => {
          const row = tableRows[vi.index];
          const l = row.original;
          return (
            <div
              key={row.id}
              role="row"
              tabIndex={0}
              aria-selected={p.selected.has(l.id)}
              onClick={() => p.onOpen(l.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter") p.onOpen(l.id);
                if (e.key === " ") {
                  e.preventDefault();
                  p.onToggle(l.id);
                }
              }}
              className={cn(
                "absolute inset-x-0 grid cursor-pointer items-center gap-3 border-b px-4 text-[13px] outline-none transition-colors sm:px-6",
                "hover:bg-surface focus-visible:bg-surface focus-visible:shadow-[inset_2px_0_0_var(--accent)]",
                p.selected.has(l.id) && "bg-brand-soft hover:bg-brand-soft",
                p.openId === l.id && "shadow-[inset_2px_0_0_var(--accent)]",
                p.fresh.has(l.id) && "animate-row-in",
              )}
              style={{ gridTemplateColumns: grid, top: vi.start, height: vi.size }}
            >
              {row.getVisibleCells().map((c) => (
                <div key={c.id} role="cell" className="min-w-0">
                  {flexRender(c.column.columnDef.cell, c.getContext())}
                </div>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function LeadCards({
  rows,
  onOpen,
  selected,
  onToggle,
  fresh,
}: {
  rows: Ranked[];
  onOpen: (id: string) => void;
  selected: Set<string>;
  onToggle: (id: string) => void;
  fresh: Set<string>;
}) {
  return (
    <ul className="flex flex-col gap-2 p-3" aria-label="Ranked leads">
      {rows.map((l) => (
        <li
          key={l.id}
          className={cn(
            "rounded-lg border bg-surface p-3 [content-visibility:auto] [contain-intrinsic-size:auto_132px]",
            selected.has(l.id) && "border-brand bg-brand-soft",
            fresh.has(l.id) && "animate-row-in",
          )}
        >
          <div className="flex items-start gap-3">
            <Checkbox
              checked={selected.has(l.id)}
              onCheckedChange={() => onToggle(l.id)}
              aria-label={`Select ${l.name}`}
              className="mt-1"
            />
            <button type="button" onClick={() => onOpen(l.id)} className="flex min-w-0 flex-1 flex-col gap-2 text-left">
              <span className="flex items-start gap-2">
                <TierBadge tier={l.tier} capped={l.capped} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{l.name}</span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {[l.domain, l.city, l.founded_year ? `since ${l.founded_year}` : null].filter(Boolean).join(" · ")}
                  </span>
                </span>
                <span className="font-mono text-lg leading-6 font-semibold tabular-nums">{l.composite}</span>
              </span>
              <MiniBars d={l.scores.durability} s={l.scores.succession} u={l.scores.upside} />
              <span className="flex flex-wrap items-center gap-1">
                {l.top_evidence.slice(0, 3).map((e) => (
                  <EvidenceChip key={e}>{e}</EvidenceChip>
                ))}
                {l.thin_data && <EvidenceChip className="border-dashed">thin data</EvidenceChip>}
              </span>
            </button>
          </div>
        </li>
      ))}
    </ul>
  );
}
