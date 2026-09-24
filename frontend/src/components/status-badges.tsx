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
  danger: "bg-red-100 text-red-700 border-red-200 dark:bg-red-900/30 dark:text-red-400 dark:border-red-800/50",
  warning: "bg-amber-100 text-amber-700 border-amber-200 dark:bg-amber-900/30 dark:text-amber-400 dark:border-amber-800/50",
  success: "bg-emerald-100 text-emerald-700 border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-400 dark:border-emerald-800/50",
  info: "bg-blue-100 text-blue-700 border-blue-200 dark:bg-blue-900/30 dark:text-blue-400 dark:border-blue-800/50",
  neutral: "bg-gray-100 text-gray-700 border-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:border-gray-700",
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
    <span
      title={title}
      className={cn("inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold border shadow-sm transition-colors", tone[variantTone], className)}
    >
      {children}
    </span>
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
