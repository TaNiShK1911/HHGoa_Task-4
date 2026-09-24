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

      <div className="mt-3 grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
        <section className="panel overflow-hidden">
          {isPending && (
            <div className="space-y-3 p-5">
              <Skeleton className="h-[500px] w-full" />
              <p className="text-xs text-muted-foreground">
                Waking up the investigation service — fetching the graph neighborhood.
              </p>
            </div>
          )}

          {isError && (
            <div className="flex items-start gap-2 p-5 text-sm text-danger">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <div>
                <p className="font-medium">Neighborhood could not be loaded</p>
                <p className="text-danger/80">{(error as Error)?.message}</p>
              </div>
            </div>
          )}

          {data && data.nodes.length === 0 && (
            <p className="p-5 text-sm text-muted-foreground">
              No connected entities returned for this case.
            </p>
          )}

          {data && data.nodes.length > 0 && (
            <ClientOnly fallback={<Skeleton className="m-5 h-[500px]" />}>
              <Suspense fallback={<Skeleton className="m-5 h-[500px]" />}>
                <NeighborhoodGraph data={data} onSelect={setSelected} />
              </Suspense>
            </ClientOnly>
          )}
        </section>

        <aside className="space-y-4">
          <section className="panel p-4">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Legend
            </h2>
            <ul className="mt-2 space-y-1.5 text-sm">
              {LEGEND.map((l) => (
                <li key={l.type} className="flex items-center gap-2">
                  <span className={`inline-block h-2.5 w-2.5 rounded-full ${l.token}`} />
                  {humanise(l.type)}
                </li>
              ))}
            </ul>
            <p className="mt-3 text-xs text-muted-foreground">
              Hover an edge for its relationship type. Zoom in to reveal node labels.
            </p>
          </section>

          <section className="panel p-4">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Node detail
            </h2>
            {!selected ? (
              <p className="mt-2 text-sm text-muted-foreground">Select a node to inspect it.</p>
            ) : (
              <dl className="mt-2 space-y-2 text-sm">
                {Object.entries(selected)
                  .filter(
                    ([k, v]) =>
                      !["x", "y", "vx", "vy", "index", "fx", "fy", "__indexColor"].includes(k) &&
                      (typeof v === "string" || typeof v === "number" || typeof v === "boolean"),
                  )
                  .map(([k, v]) => (
                    <div key={k}>
                      <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                        {humanise(k)}
                      </dt>
                      <dd className="mono break-all">{String(v)}</dd>
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
