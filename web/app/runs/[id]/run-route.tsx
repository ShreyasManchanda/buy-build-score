"use client";

import { useParams } from "next/navigation";
import { RunView } from "@/components/run/run-view";

export function RunRoute() {
  const { id } = useParams<{ id: string }>();
  // Keyed by id so every run starts from a clean state.
  return <RunView key={id} runId={id} />;
}
