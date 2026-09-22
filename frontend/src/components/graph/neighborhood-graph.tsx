import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import type { Neighborhood, NeighborhoodNode } from "@/types/answerFile";

const TYPE_TOKEN: Record<string, string> = {
  transaction: "--chart-2",
  txn: "--chart-2",
  card: "--chart-1",
  device: "--chart-3",
  device_profile: "--chart-3",
  region: "--chart-4",
  billing_region: "--chart-4",
  case: "--chart-5",
  customer: "--primary",
};

function readToken(name: string, fallback: string) {
  if (typeof window === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

export default function NeighborhoodGraph({
  data,
  onSelect,
}: {
  data: Neighborhood;
  onSelect: (node: NeighborhoodNode | null) => void;
}) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 800, height: 560 });

  useEffect(() => {
    const el = wrapperRef.current;
    if (!el) return;
    const observer = new ResizeObserver(() => {
      setSize({ width: el.clientWidth, height: el.clientHeight });
    });
    observer.observe(el);
    setSize({ width: el.clientWidth, height: el.clientHeight });
    return () => observer.disconnect();
  }, []);

  const palette = useMemo(() => {
    const entries = Object.entries(TYPE_TOKEN).map(([type, token]) => [
      type,
      readToken(token, "#64748b"),
    ]);
    return Object.fromEntries(entries) as Record<string, string>;
  }, []);

  const textColor = useMemo(() => readToken("--foreground", "#1e293b"), []);
  const edgeColor = useMemo(() => readToken("--muted-foreground", "#94a3b8"), []);

  const graphData = useMemo(
    () => ({
      nodes: data.nodes.map((n) => ({ ...n })),
      links: data.edges.map((e) => ({ ...e })),
    }),
    [data],
  );

  const colorFor = (type: string) => palette[type?.toLowerCase()] ?? "#64748b";

  return (
    <div ref={wrapperRef} className="h-[560px] w-full">
      <ForceGraph2D
        width={size.width}
        height={size.height}
        graphData={graphData}
        backgroundColor="transparent"
        nodeRelSize={5}
        linkColor={() => edgeColor}
        linkWidth={1}
        linkDirectionalArrowLength={3}
        linkDirectionalArrowRelPos={0.9}
        linkLabel={(l: object) => String((l as { label?: string }).label ?? "")}
        onNodeClick={(n: object) => onSelect(n as NeighborhoodNode)}
        onBackgroundClick={() => onSelect(null)}
        nodeCanvasObject={(node: object, ctx: CanvasRenderingContext2D, scale: number) => {
          const n = node as NeighborhoodNode & { x: number; y: number };
          const r = 5;
          ctx.beginPath();
          ctx.arc(n.x, n.y, r, 0, 2 * Math.PI);
          ctx.fillStyle = colorFor(String(n.type));
          ctx.fill();
          if (scale > 1.2) {
            ctx.font = `${10 / scale}px "IBM Plex Sans", sans-serif`;
            ctx.fillStyle = textColor;
            ctx.textAlign = "center";
            ctx.fillText(String(n.label ?? n.id), n.x, n.y + r + 8 / scale);
          }
        }}
      />
    </div>
  );
}

export const NODE_TYPE_COLORS = TYPE_TOKEN;
