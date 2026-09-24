import { lazy, Suspense, useState } from "react";
import { ClientOnly, createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft } from "lucide-react";

import { neighborhoodQuery } from "@/lib/queries";
import { humanise } from "@/lib/format";
import { Skeleton } from "@/components/ui/skeleton";
import type { NeighborhoodNode } from "@/types/answerFile";

const NeighborhoodGraph = lazy(() => import("@/components/graph/neighborhood-graph"));

const LEGEND: Array<{ type: string; token: string }> = [
  { type: "transaction", token: "bg-chart-2" },
  { type: "card", token: "bg-chart-1" },
  { type: "device_profile", token: "bg-chart-3" },
  { type: "billing_region", token: "bg-chart-4" },
  { type: "case", token: "bg-chart-5" },
  { type: "closed_case", token: "bg-chart-5" },
  { type: "customer", token: "bg-primary" },
  { type: "policy_rule", token: "bg-warning" },
];

export const Route = createFileRoute("/cases/$caseId/graph")({
  head: ({ params }) => ({
    meta: [
      { title: `Case ${params.caseId} — Graph neighborhood` },
      {
        name: "description",
        content: `Cards, devices, regions and transactions connected to case ${params.caseId} in the fraud graph.`,
      },
      { property: "og:title", content: `Case ${params.caseId} — Graph neighborhood` },
      {
        property: "og:description",
        content: `Explore the fraud graph subgraph around case ${params.caseId}.`,
      },
    ],
  }),
  component: GraphView,
});

function GraphView() {
  const { caseId } = Route.useParams();
  const { data, isPending, isError, error } = useQuery(neighborhoodQuery(caseId));
  const [selected, setSelected] = useState<NeighborhoodNode | null>(null);

  return (
    <main className="mx-auto max-w-[1600px] px-4 py-6 lg:px-6">
      <Link
        to="/cases/$caseId"
        params={{ caseId }}
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> Investigation trace
      </Link>

      <div className="mt-2 flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-lg font-semibold tracking-tight">
          Graph neighborhood · <span className="mono">{caseId}</span>
        </h1>
        <p className="text-sm text-muted-foreground">
          {data ? `${data.nodes.length} nodes · ${data.edges.length} edges` : ""}
        </p>
      </div>

      <div className="mt-4 relative h-[calc(100vh-200px)] min-h-[600px] rounded-xl border border-border/60 bg-surface/30 overflow-hidden shadow-sm">
        <div className="absolute inset-0 z-0">
          {isPending && (
            <div className="flex h-full flex-col items-center justify-center space-y-3 p-5">
              <Skeleton className="h-full w-full absolute inset-0 opacity-20" />
              <div className="z-10 flex flex-col items-center gap-3">
                <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
                <p className="text-sm font-medium text-muted-foreground">
                  Fetching graph neighborhood...
                </p>
              </div>
            </div>
          )}

          {isError && (
            <div className="flex h-full items-center justify-center p-5 text-sm text-danger relative z-10">
              <div className="flex max-w-md flex-col items-center gap-2 rounded-xl border border-danger/30 bg-danger-soft p-5 text-center shadow-sm">
                <AlertTriangle className="h-8 w-8" />
                <div>
                  <p className="font-semibold">Neighborhood could not be loaded</p>
                  <p className="mt-1 text-danger/80">{(error as Error)?.message}</p>
                </div>
              </div>
            </div>
          )}

          {data && data.nodes.length === 0 && (
            <div className="flex h-full items-center justify-center relative z-10">
              <p className="rounded-xl border border-border/50 bg-background/80 p-5 text-sm text-muted-foreground backdrop-blur-md">
                No connected entities returned for this case.
              </p>
            </div>
          )}

          {data && data.nodes.length > 0 && (
            <ClientOnly fallback={<Skeleton className="h-full w-full" />}>
              <Suspense fallback={<Skeleton className="h-full w-full" />}>
                <NeighborhoodGraph data={data} onSelect={setSelected} />
              </Suspense>
            </ClientOnly>
          )}
        </div>

        <aside className="absolute right-4 top-4 bottom-4 w-80 overflow-y-auto space-y-4 z-10 pointer-events-none custom-scrollbar pb-4">
          <section className="rounded-xl border border-border/60 bg-background/80 p-5 shadow-lg backdrop-blur-xl pointer-events-auto transition-all hover:bg-background/90">
            <h2 className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
              Legend
            </h2>
            <ul className="mt-3 space-y-2 text-sm">
              {LEGEND.map((l) => (
                <li key={l.type} className="flex items-center gap-2.5 font-medium">
                  <span className={`inline-block h-3 w-3 rounded-full shadow-sm ${l.token}`} />
                  {humanise(l.type)}
                </li>
              ))}
            </ul>
            <p className="mt-4 text-[11px] leading-relaxed text-muted-foreground">
              Hover an edge for its relationship type. Zoom in to reveal node labels.
            </p>
          </section>

          <section className="rounded-xl border border-border/60 bg-background/80 p-5 shadow-lg backdrop-blur-xl pointer-events-auto transition-all hover:bg-background/90">
            <h2 className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
              Node detail
            </h2>
            {!selected ? (
              <div className="mt-4 rounded-lg border border-dashed border-border/60 p-4 text-center">
                <p className="text-xs text-muted-foreground italic">Select a node to inspect it.</p>
              </div>
            ) : (
              <dl className="mt-4 space-y-3 text-sm">
                {Object.entries(selected)
                  .filter(
                    ([k, v]) =>
                      !["x", "y", "vx", "vy", "index", "fx", "fy", "__indexColor"].includes(k) &&
                      (typeof v === "string" || typeof v === "number" || typeof v === "boolean"),
                  )
                  .map(([k, v]) => (
                    <div key={k} className="border-b border-border/40 pb-2 last:border-0 last:pb-0">
                      <dt className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground mb-1">
                        {humanise(k)}
                      </dt>
                      <dd className="mono text-xs break-all text-foreground bg-surface/50 p-1.5 rounded-md border border-border/30">{String(v)}</dd>
                    </div>
                  ))}
              </dl>
            )}
          </section>
        </aside>
      </div>
    </main>
  );
}
