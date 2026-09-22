import { useState } from "react";
import { createFileRoute, Link, useRouter } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  ChevronDown,
  FileText,
  Loader2,
  Network,
  RefreshCw,
} from "lucide-react";
import { toast } from "sonner";

import { api } from "@/lib/api";
import { caseQuery, traceQuery } from "@/lib/queries";
import { formatDateTime, formatUsd, humanise } from "@/lib/format";
import {
  ProbabilityBar,
  RouteBadge,
  SourceBadge,
  StatusBadge,
  VerdictBadge,
} from "@/components/status-badges";
import { RuleChip } from "@/components/rule-chip";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { AnswerFile, NextBestAction, TraceStep } from "@/types/answerFile";

export const Route = createFileRoute("/cases/$caseId/")({
  head: ({ params }) => ({
    meta: [
      { title: `Case ${params.caseId} — Investigation trace` },
      {
        name: "description",
        content: `Full investigation trace, evidence, recommended actions and SAR decision for case ${params.caseId}.`,
      },
      { property: "og:title", content: `Case ${params.caseId} — Investigation trace` },
      {
        property: "og:description",
        content: `Evidence, policy citations and next best actions for case ${params.caseId}.`,
      },
    ],
  }),
  component: InvestigationTrace,
});

function InvestigationTrace() {
  const { caseId } = Route.useParams();
  const router = useRouter();
  const queryClient = useQueryClient();

  const caseResult = useQuery(caseQuery(caseId));
  const traceResult = useQuery(traceQuery(caseId));

  const rerun = useMutation({
    mutationFn: () => api.runCase(caseId),
    onSuccess: async () => {
      toast.success("Investigation re-run complete", { description: `Case ${caseId} updated.` });
      await queryClient.invalidateQueries({ queryKey: ["case", caseId] });
      await queryClient.invalidateQueries({ queryKey: ["trace", caseId] });
      await queryClient.invalidateQueries({ queryKey: ["cases"] });
      router.invalidate();
    },
    onError: (e: Error) =>
      toast.error("Re-run failed", {
        description: e.message || "The investigation service did not respond.",
      }),
  });

  const answer = caseResult.data;

  return (
    <main className="mx-auto max-w-[1600px] px-4 py-6 lg:px-6">
      <Link
        to="/"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> Case feed
      </Link>

      {caseResult.isPending && (
        <div className="panel mt-3 space-y-3 p-5">
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-4 w-full max-w-2xl" />
          <Skeleton className="h-4 w-2/3" />
        </div>
      )}

      {caseResult.isError && (
        <ErrorBanner
          title={`Case ${caseId} could not be loaded`}
          message={(caseResult.error as Error)?.message ?? "Unknown error."}
        />
      )}

      {answer && (
        <>
          <CaseHeader
            answer={answer}
            onRerun={() => rerun.mutate()}
            rerunning={rerun.isPending}
            caseId={caseId}
          />

          <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
            <TracePanel
              steps={traceResult.data}
              isPending={traceResult.isPending}
              isError={traceResult.isError}
              errorMessage={(traceResult.error as Error)?.message}
            />
            <div className="space-y-4">
              <EvidencePanel answer={answer} />
              <ProgressionPanel answer={answer} />
              <SarPanel answer={answer} />
              <MemoryPanel answer={answer} />
            </div>
          </div>
        </>
      )}
    </main>
  );
}

function CaseHeader({
  answer,
  onRerun,
  rerunning,
  caseId,
}: {
  answer: AnswerFile;
  onRerun: () => void;
  rerunning: boolean;
  caseId: string;
}) {
  const c = answer.case;
  return (
    <section className="panel mt-3 p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="mono text-lg font-semibold tracking-tight">{answer.case_id}</h1>
            <VerdictBadge verdict={c.verdict} />
            <StatusBadge status={c.status} />
            <span className="text-sm text-muted-foreground">{humanise(c.pattern)}</span>
          </div>
          <p className="mt-2 max-w-3xl text-sm leading-relaxed text-foreground">{c.summary}</p>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{c.pattern_description}</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" asChild>
            <Link to="/cases/$caseId/graph" params={{ caseId }}>
              <Network className="mr-1.5 h-3.5 w-3.5" /> View graph neighborhood
            </Link>
          </Button>
          <Button size="sm" onClick={onRerun} disabled={rerunning}>
            {rerunning ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
            )}
            {rerunning ? "Re-running…" : "Re-run investigation"}
          </Button>
        </div>
      </div>

      {rerunning && (
        <p className="mt-3 text-xs text-muted-foreground">
          Waking up the investigation service — the first run after a quiet period can take up to a
          minute.
        </p>
      )}

      <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 border-t border-border pt-4 text-sm md:grid-cols-4 xl:grid-cols-7">
        <Field label="Fraud probability">
          <ProbabilityBar value={c.fraud_probability} />
        </Field>
        <Field label="Exposure">
          <span className="mono">{formatUsd(c.exposure_usd)}</span>
        </Field>
        <Field label="First suspicious txn">
          <span className="mono truncate">{c.first_suspicious_txn_id || "—"}</span>
        </Field>
        <Field label="Affected txns">
          <span className="mono">{c.affected_txn_ids.length}</span>
        </Field>
        <Field label="Connected cards">
          <span className="mono">{c.connected_card_ids.length}</span>
        </Field>
        <Field label="Device profiles">
          <span className="mono">{c.connected_device_profiles.length}</span>
        </Field>
        <Field label="Written to graph">
          <span className="mono">
            {c.written_to_graph ? c.graph_case_id || "yes" : "not written"}
          </span>
        </Field>
      </dl>

      <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted-foreground">
        <span>Tool calls: {answer.tool_calls}</span>
        <span>Tokens: {answer.tokens.toLocaleString()}</span>
        <span>Latency: {answer.latency_s}s</span>
      </div>
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="mt-1 truncate">{children}</dd>
    </div>
  );
}

function TracePanel({
  steps,
  isPending,
  isError,
  errorMessage,
}: {
  steps: TraceStep[] | undefined;
  isPending: boolean;
  isError: boolean;
  errorMessage?: string;
}) {
  return (
    <section className="panel p-5">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        Investigation timeline
      </h2>

      {isPending && (
        <div className="mt-4 space-y-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
          <p className="text-xs text-muted-foreground">
            Waking up the investigation service — this can take a moment on first load.
          </p>
        </div>
      )}

      {isError && (
        <p className="mt-4 text-sm text-muted-foreground">
          Trace unavailable. {errorMessage}
        </p>
      )}

      {steps && steps.length === 0 && (
        <p className="mt-4 text-sm text-muted-foreground">No trace recorded for this case.</p>
      )}

      {steps && steps.length > 0 && (
        <ol className="mt-4 space-y-1">
          {steps.map((step, i) => (
            <TraceStepRow key={`${step.node_name}-${i}`} step={step} index={i} />
          ))}
        </ol>
      )}
    </section>
  );
}

function TraceStepRow({ step, index }: { step: TraceStep; index: number }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="relative pl-7">
      <span className="absolute left-2 top-7 h-[calc(100%-1rem)] w-px bg-border" />
      <span className="mono absolute left-0 top-1.5 flex h-4 w-4 items-center justify-center rounded-full border border-border bg-card text-[9px] text-muted-foreground">
        {index + 1}
      </span>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left transition-colors hover:bg-surface"
      >
        <span className="mono text-xs font-semibold">{step.node_name}</span>
        {step.policy_rule_fired && <RuleChip rule={step.policy_rule_fired} />}
        <span className="ml-auto text-[11px] text-muted-foreground">
          {formatDateTime(step.timestamp)}
        </span>
        <ChevronDown
          className={`h-3.5 w-3.5 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && (
        <div className="mb-2 ml-2 space-y-2 rounded-md border border-border bg-surface px-3 py-2 text-xs">
          <div>
            <p className="uppercase tracking-wide text-muted-foreground">Input</p>
            <p className="mt-0.5 leading-relaxed">{step.input_summary || "—"}</p>
          </div>
          <div>
            <p className="uppercase tracking-wide text-muted-foreground">Output</p>
            <p className="mt-0.5 leading-relaxed">{step.output_summary || "—"}</p>
          </div>
        </div>
      )}
    </li>
  );
}

function EvidencePanel({ answer }: { answer: AnswerFile }) {
  const evidence = answer.case.evidence ?? [];
  const requests = answer.evidence_requests ?? [];
  return (
    <section className="panel p-5">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        Evidence
      </h2>
      <ul className="mt-3 space-y-3">
        {evidence.map((item, i) => (
          <li key={i} className="border-b border-border pb-3 last:border-0 last:pb-0">
            <div className="flex flex-wrap items-center gap-2">
              <SourceBadge source={item.source} />
              <span className="mono text-[11px] text-muted-foreground">{item.ref}</span>
            </div>
            <p className="mt-1.5 text-sm leading-relaxed">{item.claim}</p>
            {item.entity_ids.length > 0 && (
              <div className="mt-1.5 flex flex-wrap gap-1">
                {item.entity_ids.map((id) => (
                  <span
                    key={id}
                    className="mono rounded bg-neutral-soft px-1.5 py-0.5 text-[10px] text-muted-foreground"
                  >
                    {id}
                  </span>
                ))}
              </div>
            )}
          </li>
        ))}
        {evidence.length === 0 && (
          <li className="text-sm text-muted-foreground">No evidence recorded.</li>
        )}
      </ul>

      {requests.length > 0 && (
        <div className="mt-4 border-t border-border pt-3">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            Evidence requested during the investigation
          </p>
          <ul className="mt-2 space-y-2">
            {requests.map((r, i) => (
              <li key={i} className="text-sm">
                <span className="font-medium">{humanise(r.type)}</span>
                <span className="text-muted-foreground"> · after step {r.asked_after_step}</span>
                <p className="text-sm text-muted-foreground">{r.assumed_response}</p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function ActionList({ title, actions }: { title: string; actions: NextBestAction[] }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-muted-foreground">{title}</p>
      <ul className="mt-2 space-y-2">
        {actions.map((a, i) => (
          <li key={i} className="rounded-md border border-border bg-surface px-3 py-2">
            <div className="flex items-start justify-between gap-2">
              <span className="text-sm font-medium">{a.action}</span>
              <RouteBadge route={a.route} />
            </div>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{a.reason}</p>
          </li>
        ))}
        {actions.length === 0 && <li className="text-sm text-muted-foreground">None.</li>}
      </ul>
    </div>
  );
}

function ProgressionPanel({ answer }: { answer: AnswerFile }) {
  const nba = answer.next_best_actions;
  return (
    <section className="panel p-5">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        Case progression — next best actions
      </h2>
      <div className="mt-3 grid gap-4 md:grid-cols-2">
        <ActionList title="Initial recommendation" actions={nba?.initial ?? []} />
        <ActionList title="Final recommendation" actions={nba?.final ?? []} />
      </div>
      <div className="mt-4 space-y-2">
        <Callout label="What changed">{nba?.what_changed || "No change recorded."}</Callout>
        <Callout label="Stop reason">{answer.stop_reason || "—"}</Callout>
      </div>
    </section>
  );
}

function Callout({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-md border-l-2 border-primary bg-surface px-3 py-2">
      <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-0.5 text-sm leading-relaxed">{children}</p>
    </div>
  );
}

function SarPanel({ answer }: { answer: AnswerFile }) {
  const sar = answer.sar;
  if (!sar) return null;

  if (!sar.file) {
    return (
      <section className="panel p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Suspicious activity report
        </h2>
        <p className="mt-2 text-sm text-muted-foreground">No SAR required — {sar.reason}</p>
      </section>
    );
  }

  const dates = sar.activity_dates ?? [];
  return (
    <section className="panel border-warning/40 p-5">
      <div className="flex items-center gap-2">
        <FileText className="h-4 w-4 text-warning" />
        <h2 className="text-sm font-semibold uppercase tracking-wide text-warning">
          SAR to be filed
        </h2>
      </div>
      <p className="mt-2 text-sm text-muted-foreground">{sar.reason}</p>
      <p className="mt-3 whitespace-pre-line text-sm leading-relaxed">{sar.narrative}</p>
      <dl className="mt-4 grid gap-3 border-t border-border pt-3 text-sm sm:grid-cols-3">
        <Field label="Total amount">
          <span className="mono">{formatUsd(sar.total_amount_usd)}</span>
        </Field>
        <Field label="Activity dates">
          <span className="mono">
            {dates.length ? `${dates[0]} → ${dates[dates.length - 1]}` : "—"}
          </span>
        </Field>
        <Field label="Subjects">
          <div className="flex flex-wrap gap-1">
            {(sar.subjects ?? []).map((s) => (
              <span
                key={s}
                className="mono rounded bg-neutral-soft px-1.5 py-0.5 text-[10px] text-muted-foreground"
              >
                {s}
              </span>
            ))}
          </div>
        </Field>
      </dl>
    </section>
  );
}

function MemoryPanel({ answer }: { answer: AnswerFile }) {
  const [selected, setSelected] = useState<string | null>(null);
  const prior = answer.case.similar_prior_cases ?? [];
  return (
    <section className="panel p-5">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        Case memory — similar prior cases
      </h2>
      {prior.length === 0 ? (
        <p className="mt-2 text-sm text-muted-foreground">No similar prior cases retrieved.</p>
      ) : (
        <div className="mt-3 flex flex-wrap gap-2">
          {prior.map((id) => (
            <button
              key={id}
              type="button"
              onClick={() => setSelected(id)}
              className="mono rounded border border-border bg-surface px-2 py-1 text-xs transition-colors hover:bg-accent"
            >
              {id}
            </button>
          ))}
        </div>
      )}
      <PriorCaseDialog caseId={selected} onClose={() => setSelected(null)} />
    </section>
  );
}

function PriorCaseDialog({ caseId, onClose }: { caseId: string | null; onClose: () => void }) {
  const { data, isPending, isError } = useQuery({
    ...caseQuery(caseId ?? ""),
    enabled: Boolean(caseId),
  });

  return (
    <Dialog open={Boolean(caseId)} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle className="mono">{caseId}</DialogTitle>
          <DialogDescription>Retrieved from case memory.</DialogDescription>
        </DialogHeader>
        {isPending && <Skeleton className="h-16 w-full" />}
        {isError && (
          <p className="text-sm text-muted-foreground">
            No stored detail available for this prior case.
          </p>
        )}
        {data && (
          <div className="space-y-2 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <VerdictBadge verdict={data.case.verdict} />
              <StatusBadge status={data.case.status} />
              <span className="text-muted-foreground">{humanise(data.case.pattern)}</span>
            </div>
            <p className="leading-relaxed">{data.case.summary}</p>
            <p className="mono text-xs text-muted-foreground">
              Exposure {formatUsd(data.case.exposure_usd)}
            </p>
            {caseId && (
              <Link
                to="/cases/$caseId"
                params={{ caseId }}
                onClick={onClose}
                className="inline-block text-sm text-primary hover:underline"
              >
                Open full case
              </Link>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function ErrorBanner({ title, message }: { title: string; message: string }) {
  return (
    <div className="mt-3 flex items-start gap-2 rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <div>
        <p className="font-medium">{title}</p>
        <p className="text-danger/80">{message}</p>
      </div>
    </div>
  );
}
