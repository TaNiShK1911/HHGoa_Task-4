import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { humanise } from "@/lib/format";
import type {
  ActionRoute,
  CaseStatus,
  EvidenceSource,
  Pattern,
  TriggerType,
  Verdict,
} from "@/types/answerFile";

const tone = {
  danger: "bg-danger-soft text-danger border-danger/30",
  warning: "bg-warning-soft text-warning border-warning/30",
  success: "bg-success-soft text-success border-success/30",
  info: "bg-info-soft text-info border-info/30",
  neutral: "bg-neutral-soft text-muted-foreground border-border",
} as const;

type Tone = keyof typeof tone;

function Pill({
  children,
  variantTone,
  className,
  title,
}: {
  children: React.ReactNode;
  variantTone: Tone;
  className?: string;
  title?: string;
}) {
  return (
    <Badge
      variant="outline"
      title={title}
      className={cn("font-medium tracking-tight", tone[variantTone], className)}
    >
      {children}
    </Badge>
  );
}

export function VerdictBadge({ verdict }: { verdict: Verdict | null }) {
  if (!verdict) return <Pill variantTone="neutral">Not assessed</Pill>;
  const map: Record<Verdict, Tone> = {
    fraud: "danger",
    legitimate: "success",
    uncertain: "warning",
  };
  return <Pill variantTone={map[verdict]}>{humanise(verdict)}</Pill>;
}

export function StatusBadge({ status }: { status: CaseStatus | null }) {
  if (!status) return <Pill variantTone="neutral">—</Pill>;
  const map: Record<CaseStatus, Tone> = {
    open: "info",
    closed_fraud: "danger",
    closed_legitimate: "success",
    escalated: "warning",
  };
  return <Pill variantTone={map[status]}>{humanise(status)}</Pill>;
}

export function RouteBadge({ route }: { route: ActionRoute }) {
  const map: Record<ActionRoute, Tone> = { auto: "neutral", L1: "warning", L2: "danger" };
  const label: Record<ActionRoute, string> = {
    auto: "Auto",
    L1: "L1 approval",
    L2: "L2 approval",
  };
  return (
    <Pill variantTone={map[route]} className="mono">
      {label[route]}
    </Pill>
  );
}

export function TriggerBadge({ trigger }: { trigger: TriggerType | null }) {
  if (!trigger) return <Pill variantTone="neutral">—</Pill>;
  const map: Record<TriggerType, Tone> = {
    risk_score: "info",
    customer_report: "warning",
    analyst_request: "neutral",
  };
  return <Pill variantTone={map[trigger]}>{humanise(trigger)}</Pill>;
}

export function SourceBadge({ source }: { source: EvidenceSource }) {
  const map: Record<EvidenceSource, Tone> = {
    graph: "info",
    document: "neutral",
    customer: "warning",
    external: "success",
  };
  return <Pill variantTone={map[source]}>{humanise(source)}</Pill>;
}

export function PatternLabel({ pattern }: { pattern: Pattern | null }) {
  if (!pattern || pattern === "none")
    return <span className="text-muted-foreground">No pattern</span>;
  return <span className="text-foreground">{humanise(pattern)}</span>;
}

export function highestRoute(routes: ActionRoute[]): ActionRoute | null {
  if (routes.includes("L2")) return "L2";
  if (routes.includes("L1")) return "L1";
  if (routes.includes("auto")) return "auto";
  return null;
}

export function ProbabilityBar({ value }: { value: number | null }) {
  if (value === null || value === undefined)
    return <span className="text-muted-foreground">—</span>;
  const pct = Math.max(0, Math.min(100, value <= 1 ? value * 100 : value));
  const barTone = pct >= 70 ? "bg-danger" : pct >= 40 ? "bg-warning" : "bg-success";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-neutral-soft">
        <div className={cn("h-full rounded-full", barTone)} style={{ width: `${pct}%` }} />
      </div>
      <span className="mono text-xs text-muted-foreground">{pct.toFixed(0)}%</span>
    </div>
  );
}
