import { useMemo, useState } from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Search } from "lucide-react";

import { casesQuery } from "@/lib/queries";
import { formatDateTime, formatUsd, humanise } from "@/lib/format";
import {
  highestRoute,
  PatternLabel,
  ProbabilityBar,
  RouteBadge,
  StatusBadge,
  TriggerBadge,
  VerdictBadge,
} from "@/components/status-badges";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { hasSupabase } from "@/lib/supabase";
import { API_BASE_URL } from "@/lib/api";
import type { ActionRoute, CaseListRow } from "@/types/answerFile";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Case feed — Fraud Investigation Console" },
      {
        name: "description",
        content:
          "All investigated fraud cases with verdict, pattern, exposure and approval routing at a glance.",
      },
      { property: "og:title", content: "Case feed — Fraud Investigation Console" },
      {
        property: "og:description",
        content: "Browse agentic fraud investigations: verdicts, patterns, exposure and routing.",
      },
    ],
  }),
  component: CaseFeed,
});

const ALL = "all";

function finalRoute(row: CaseListRow): ActionRoute | null {
  const actions = row.payload?.next_best_actions?.final ?? [];
  return highestRoute(actions.map((a) => a.route));
}

function CaseFeed() {
  const { data, isPending, isError, error } = useQuery(casesQuery());
  const [verdict, setVerdict] = useState(ALL);
  const [pattern, setPattern] = useState(ALL);
  const [trigger, setTrigger] = useState(ALL);
  const [search, setSearch] = useState("");

  const rows = data ?? [];
  const isConfigured = hasSupabase || Boolean(API_BASE_URL);

  const patterns = useMemo(
    () => Array.from(new Set(rows.map((r) => r.pattern).filter(Boolean))) as string[],
    [rows],
  );

  const filtered = useMemo(
    () =>
      rows.filter((r) => {
        if (verdict !== ALL && r.verdict !== verdict) return false;
        if (pattern !== ALL && r.pattern !== pattern) return false;
        if (trigger !== ALL && r.trigger_type !== trigger) return false;
        if (search && !r.case_id.toLowerCase().includes(search.toLowerCase())) return false;
        return true;
      }),
    [rows, verdict, pattern, trigger, search],
  );

  const stats = useMemo(() => {
    const byVerdict = { fraud: 0, legitimate: 0, uncertain: 0 };
    let exposure = 0;
    for (const r of rows) {
      if (r.verdict && r.verdict in byVerdict) byVerdict[r.verdict] += 1;
      if (r.verdict === "fraud") exposure += Number(r.exposure_usd ?? 0);
    }
    return { total: rows.length, byVerdict, exposure };
  }, [rows]);

  return (
    <main className="mx-auto max-w-[1600px] px-4 py-6 lg:px-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Case feed</h1>
          <p className="text-sm text-muted-foreground">
            Investigations produced by the agent, mirrored from the fraud graph.
          </p>
        </div>
      </div>

      <section className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-5">
        <StatCard label="Cases" value={isPending ? "…" : String(stats.total)} />
        <StatCard
          label="Fraud"
          value={isPending ? "…" : String(stats.byVerdict.fraud)}
          tone="text-danger"
        />
        <StatCard
          label="Legitimate"
          value={isPending ? "…" : String(stats.byVerdict.legitimate)}
          tone="text-success"
        />
        <StatCard
          label="Uncertain"
          value={isPending ? "…" : String(stats.byVerdict.uncertain)}
          tone="text-warning"
        />
        <StatCard
          label="Fraud exposure"
          value={isPending ? "…" : formatUsd(stats.exposure)}
          className="col-span-2 lg:col-span-1"
        />
      </section>

      <section className="mt-5 flex flex-wrap items-center gap-2">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search case ID"
            className="h-9 w-56 pl-8 text-sm"
          />
        </div>
        <FilterSelect
          value={verdict}
          onChange={setVerdict}
          placeholder="All verdicts"
          options={["fraud", "legitimate", "uncertain"]}
        />
        <FilterSelect
          value={trigger}
          onChange={setTrigger}
          placeholder="All triggers"
          options={["risk_score", "customer_report", "analyst_request"]}
        />
        <FilterSelect
          value={pattern}
          onChange={setPattern}
          placeholder="All patterns"
          options={patterns}
        />
        <span className="ml-auto text-xs text-muted-foreground">
          {filtered.length} of {rows.length} shown
        </span>
      </section>

      <section className="panel mt-3 overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="bg-surface hover:bg-surface">
              <TableHead className="w-[110px]">Case</TableHead>
              <TableHead className="w-[150px]">Opened</TableHead>
              <TableHead>Trigger</TableHead>
              <TableHead>Verdict</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Fraud prob.</TableHead>
              <TableHead>Pattern</TableHead>
              <TableHead className="text-right">Exposure</TableHead>
              <TableHead>Routing</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isPending &&
              Array.from({ length: 8 }).map((_, i) => (
                <TableRow key={i}>
                  {Array.from({ length: 9 }).map((__, j) => (
                    <TableCell key={j}>
                      <Skeleton className="h-4 w-full" />
                    </TableCell>
                  ))}
                </TableRow>
              ))}

            {!isPending &&
              filtered.map((row) => {
                const route = finalRoute(row);
                return (
                  <TableRow key={row.case_id} className="text-sm">
                    <TableCell>
                      <Link
                        to="/cases/$caseId"
                        params={{ caseId: row.case_id }}
                        className="mono font-medium text-primary hover:underline"
                      >
                        {row.case_id}
                      </Link>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatDateTime(row.opened_at)}
                    </TableCell>
                    <TableCell>
                      <TriggerBadge trigger={row.trigger_type} />
                    </TableCell>
                    <TableCell>
                      <VerdictBadge verdict={row.verdict} />
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={row.status} />
                    </TableCell>
                    <TableCell>
                      <ProbabilityBar value={row.fraud_probability} />
                    </TableCell>
                    <TableCell>
                      <PatternLabel pattern={row.pattern} />
                    </TableCell>
                    <TableCell className="mono text-right">
                      {formatUsd(row.exposure_usd)}
                    </TableCell>
                    <TableCell>
                      {route ? <RouteBadge route={route} /> : <span className="text-muted-foreground">—</span>}
                    </TableCell>
                  </TableRow>
                );
              })}

            {!isPending && filtered.length === 0 && (
              <TableRow>
                <TableCell colSpan={9} className="py-10 text-center text-sm text-muted-foreground">
                  {isError ? "Cases could not be loaded." : "No cases match these filters."}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </section>

      {!isConfigured && (
        <div className="mt-3 rounded-md border border-warning/30 bg-warning-soft px-3 py-2 text-sm text-warning">
          No case source configured yet. Add the case database URL and key plus the investigation
          service URL to see live cases.
        </div>
      )}

      {isError && (
        <div className="mt-3 flex items-start gap-2 rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <p className="font-medium">Could not load cases</p>
            <p className="text-danger/80">
              {(error as Error)?.message ??
                "Check that the case database and investigation service are reachable."}
            </p>
          </div>
        </div>
      )}
    </main>
  );
}

function StatCard({
  label,
  value,
  tone,
  className,
}: {
  label: string;
  value: string;
  tone?: string;
  className?: string;
}) {
  return (
    <div className={`panel px-4 py-3 ${className ?? ""}`}>
      <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={`mono mt-1 text-xl font-semibold ${tone ?? "text-foreground"}`}>{value}</p>
    </div>
  );
}

function FilterSelect({
  value,
  onChange,
  placeholder,
  options,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  options: string[];
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="h-9 w-[190px] text-sm">
        <SelectValue placeholder={placeholder}>
          {value === ALL ? placeholder : humanise(value)}
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL}>{placeholder}</SelectItem>
        {options.map((o) => (
          <SelectItem key={o} value={o}>
            {humanise(o)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
