"use client";

import { MoonIcon, SunIcon } from "lucide-react";
import { useTheme } from "next-themes";
import { Button } from "@/components/ui/button";

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const next = resolvedTheme === "dark" ? "light" : "dark";
  return (
    <Button
      variant="ghost"
      size="icon-sm"
      onClick={() => setTheme(next)}
      aria-label={`Switch to ${next} theme`}
      title={`Switch to ${next} theme`}
    >
      <SunIcon className="hidden dark:block" />
      <MoonIcon className="dark:hidden" />
    </Button>
  );
}
