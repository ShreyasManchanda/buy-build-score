import { Suspense } from "react";
import { RunRoute } from "./run-route";

export default function RunPage() {
  // The run id is only known at request time; stream it in behind a shell.
  return (
    <Suspense fallback={<div className="h-dvh" aria-busy="true" />}>
      <RunRoute />
    </Suspense>
  );
}
