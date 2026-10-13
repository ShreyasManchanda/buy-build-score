import { AppHeader, AttributionFooter } from "@/components/app-header";
import { DIM_QUESTION, EvidenceChip } from "@/components/score-ui";
import { ThesisScreen } from "@/components/thesis-screen";

const DIMENSIONS = [
  {
    key: "durability" as const,
    name: "Durability",
    signals: [
      ["Years in business", "35"],
      ["Reviews, rating, recency", "50"],
      ["Operating at a fixed address", "15"],
    ],
    example: ["Since 1979", "© 2018 footer"],
  },
  {
    key: "succession" as const,
    name: "Succession likelihood",
    signals: [
      ["Long tenure", "25"],
      ["Founder / family-run", "20"],
      ["One named leader, stale site", "30"],
      ["Exit language, not hiring", "25"],
    ],
    example: ["“owner is retiring”", "Family owned"],
  },
  {
    key: "upside" as const,
    name: "Digital upside gap",
    signals: [
      ["No online booking or quote", "20"],
      ["Slow, no HTTPS, not mobile", "35"],
      ["No chat, analytics, social", "25"],
      ["Outdated stack, phone-only", "20"],
    ],
    example: ["No online booking", "jQuery 1.12"],
  },
];

export default function Home() {
  return (
    <div className="flex min-h-dvh flex-col">
      <AppHeader />
      <main className="mx-auto w-full max-w-[720px] flex-1 px-4 pt-10 pb-16 sm:px-6 sm:pt-16">
        <p className="mb-3 font-mono text-xs tracking-wide text-muted-foreground uppercase">
          Score before you enrich
        </p>
        <h1 className="text-2xl leading-8 font-semibold tracking-tight text-balance sm:text-[28px] sm:leading-9">
          Spend SaaSquatch credits only on owners who&rsquo;ll actually sell.
        </h1>
        <p className="mt-3 max-w-[60ch] text-muted-foreground text-pretty">
          Enter an industry and a city. We find owner-operated businesses, read their public websites politely, and
          rank them on durability, succession likelihood and digital upside &mdash; every point linked to the page
          that earned it.
        </p>

        <div className="mt-8">
          <ThesisScreen />
        </div>

        <section id="how-it-scores" className="mt-16 scroll-mt-20" aria-labelledby="how-title">
          <h2 id="how-title" className="text-base font-semibold tracking-tight">
            How it scores
          </h2>
          <p className="mt-1 max-w-[62ch] text-sm text-muted-foreground">
            Three sub-scores from 0 to 100, built only from signals we can show you. A signal we can&rsquo;t find
            scores zero and lowers coverage &mdash; it is never guessed. Tier A needs a composite of 70+, at least
            40% coverage and durability of 30+.
          </p>
          <div className="mt-5 grid gap-3 sm:grid-cols-3">
            {DIMENSIONS.map((d) => (
              <div key={d.key} className="flex flex-col gap-3 rounded-lg border bg-surface p-4">
                <div>
                  <h3 className="text-sm font-medium">{d.name}</h3>
                  <p className="text-xs text-muted-foreground">{DIM_QUESTION[d.key]}</p>
                </div>
                <ul className="flex flex-col gap-1.5 text-xs">
                  {d.signals.map(([label, pts]) => (
                    <li key={label} className="flex items-baseline justify-between gap-2">
                      <span className="text-muted-foreground">{label}</span>
                      <span className="font-mono tabular-nums">{pts}</span>
                    </li>
                  ))}
                </ul>
                <div className="mt-auto flex flex-wrap gap-1">
                  {d.example.map((e) => (
                    <EvidenceChip key={e}>{e}</EvidenceChip>
                  ))}
                </div>
              </div>
            ))}
          </div>
          <dl className="mt-6 grid gap-4 text-sm sm:grid-cols-3">
            <div>
              <dt className="font-medium">Explainable</dt>
              <dd className="text-muted-foreground">Every point links to the page, snippet or API field behind it.</dd>
            </div>
            <div>
              <dt className="font-medium">Re-weight instantly</dt>
              <dd className="text-muted-foreground">Sliders re-rank in your browser. Nothing is re-crawled.</dd>
            </div>
            <div>
              <dt className="font-medium">Collected ethically</dt>
              <dd className="text-muted-foreground">robots.txt, 1 request/s per site, no LinkedIn, no inbox probing.</dd>
            </div>
          </dl>
        </section>
      </main>
      <AttributionFooter />
    </div>
  );
}
