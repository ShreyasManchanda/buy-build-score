import { BookOpenIcon, BracesIcon } from "lucide-react";
import Link from "next/link";
import { Wordmark } from "@/components/brand";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";

export function AppHeader({ children }: { children?: React.ReactNode }) {
  return (
    <header className="sticky top-0 z-30 border-b bg-background/85 backdrop-blur supports-[backdrop-filter]:bg-background/70">
      <div className="flex h-14 items-center gap-3 px-4 sm:px-6">
        <Wordmark compact={Boolean(children)} />
        <div className="min-w-0 flex-1">{children}</div>
        <nav className="flex items-center gap-1">
          <Button variant="ghost" size="sm" asChild className="hidden md:inline-flex">
            <Link href="/#how-it-scores">
              <BookOpenIcon /> Scoring model
            </Link>
          </Button>
          <Button variant="ghost" size="sm" asChild className="hidden md:inline-flex">
            <a href="/api/v1/docs" target="_blank" rel="noreferrer">
              <BracesIcon /> API
            </a>
          </Button>
          <ThemeToggle />
        </nav>
      </div>
    </header>
  );
}

export function AttributionFooter({ places = false }: { places?: boolean }) {
  return (
    <footer className="border-t px-4 py-3 text-xs text-muted-foreground sm:px-6">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span>
          Business data ©{" "}
          <a className="underline-offset-2 hover:underline" href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">
            OpenStreetMap contributors
          </a>{" "}
          (ODbL)
        </span>
        {places && <span>Ratings and reviews from Google</span>}
        <span>Public business websites only · robots.txt respected · 1 request/s per site</span>
      </div>
    </footer>
  );
}
