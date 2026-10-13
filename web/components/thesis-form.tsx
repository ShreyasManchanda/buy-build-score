"use client";

import { ArrowRightIcon, Loader2Icon, SparklesIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { api, ApiError } from "@/lib/api";
import { PRESETS } from "@/lib/score";
import { parseThesis } from "@/lib/thesis";
import type { Preset } from "@/lib/types";
import { cn } from "@/lib/utils";

const RADII = [10, 25, 40, 80];

export function ThesisForm({
  preset,
  onPresetChange,
}: {
  preset: Preset;
  onPresetChange: (p: Preset) => void;
}) {
  const router = useRouter();
  const [sentence, setSentence] = useState("");
  const [industry, setIndustry] = useState("");
  const [location, setLocation] = useState("");
  const [radius, setRadius] = useState(40);
  const [maxResults, setMaxResults] = useState<20 | 40 | 60>(60);
  const [expand, setExpand] = useState(false);
  const [busy, setBusy] = useState(false);

  const ready = industry.trim().length >= 2 && location.trim().length >= 2 && !busy;

  function applySentence(text: string) {
    setSentence(text);
    const p = parseThesis(text);
    if (p.industry) setIndustry(p.industry);
    if (p.location) setLocation(p.location);
    if (p.radiusKm) setRadius(RADII.reduce((a, b) => (Math.abs(b - p.radiusKm!) < Math.abs(a - p.radiusKm!) ? b : a)));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!ready) return;
    setBusy(true);
    try {
      const { run_id } = await api.createRun({
        industry: industry.trim(),
        location: location.trim(),
        radius_km: radius,
        max_results: maxResults,
        expand,
        preset,
      });
      router.push(`/runs/${run_id}`);
    } catch (err) {
      const e = err as ApiError;
      toast.error(e.title, { description: e.detail ?? "Try again in a moment, or open the demo run." });
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-5" aria-label="Thesis">
      <div className="flex flex-col gap-2">
        <Label htmlFor="sentence" className="text-muted-foreground">
          Describe your thesis
        </Label>
        <div className="relative">
          <SparklesIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            id="sentence"
            value={sentence}
            onChange={(e) => applySentence(e.target.value)}
            placeholder="HVAC companies near Columbus, OH"
            className="h-11 pl-9 text-[15px]"
            autoComplete="off"
          />
        </div>
        <p className="text-xs text-muted-foreground">We fill in the fields below as you type. Adjust anything.</p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-2">
          <Label htmlFor="industry">Industry</Label>
          <Input id="industry" value={industry} onChange={(e) => setIndustry(e.target.value)} placeholder="HVAC" />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="location">Location</Label>
          <Input
            id="location"
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            placeholder="Columbus, OH"
            autoComplete="off"
          />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="radius">Radius</Label>
          <Select value={String(radius)} onValueChange={(v) => setRadius(Number(v))}>
            <SelectTrigger id="radius" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {RADII.map((r) => (
                <SelectItem key={r} value={String(r)}>
                  {r} km
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-2">
          <Label id="max-label">Max results</Label>
          <div className="flex items-center gap-3">
            <ToggleGroup
              type="single"
              variant="outline"
              value={String(maxResults)}
              onValueChange={(v) => v && setMaxResults(Number(v) as 20 | 40 | 60)}
              aria-labelledby="max-label"
            >
              {[20, 40, 60].map((n) => (
                <ToggleGroupItem key={n} value={String(n)} className="w-11 font-mono">
                  {n}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
            <label className="flex items-center gap-2 text-sm text-muted-foreground">
              <Switch checked={expand} onCheckedChange={setExpand} aria-label="Expand with related keywords" />
              Expand
            </label>
          </div>
        </div>
      </div>

      <fieldset className="flex flex-col gap-2">
        <legend className="mb-2 text-sm font-medium">Who are you?</legend>
        <div role="radiogroup" className="grid gap-2 sm:grid-cols-3">
          {(Object.keys(PRESETS) as Preset[]).map((p) => (
            <button
              key={p}
              type="button"
              role="radio"
              aria-checked={preset === p}
              onClick={() => onPresetChange(p)}
              className={cn(
                "flex flex-col items-start gap-1 rounded-lg border px-3 py-2.5 text-left transition-colors",
                "hover:border-foreground/25 focus-visible:outline-2",
                preset === p ? "border-brand bg-brand-soft" : "bg-surface",
              )}
            >
              <span className="flex w-full items-center justify-between text-sm font-medium">
                {PRESETS[p].label}
                <span className="font-mono text-[10px] text-muted-foreground">
                  {PRESETS[p].durability}/{PRESETS[p].succession}/{PRESETS[p].upside}
                </span>
              </span>
              <span className="text-xs leading-4 text-muted-foreground">{PRESETS[p].blurb}</span>
            </button>
          ))}
        </div>
      </fieldset>

      <Button type="submit" size="lg" disabled={!ready} className="h-11 text-[15px]">
        {busy ? <Loader2Icon className="animate-spin" /> : null}
        Find targets
        {!busy && <ArrowRightIcon />}
      </Button>
      {!ready && !busy && (
        <p className="-mt-3 text-center text-xs text-muted-foreground">Add an industry and a location to start.</p>
      )}
    </form>
  );
}
