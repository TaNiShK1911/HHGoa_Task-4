import { useQuery } from "@tanstack/react-query";
import { healthQuery } from "@/lib/queries";
import { API_BASE_URL } from "@/lib/api";
import { cn } from "@/lib/utils";

export function HealthIndicator() {
  const configured = Boolean(API_BASE_URL);
  const { data, isError, isFetching } = useQuery({ ...healthQuery(), enabled: configured });

  const state = !configured
    ? { tone: "bg-muted-foreground", label: "Service URL not configured" }
    : data?.status === "ok"
      ? { tone: "bg-success", label: "Investigation service online" }
      : isError
        ? { tone: "bg-danger", label: "Investigation service unreachable" }
        : { tone: "bg-warning", label: "Checking investigation service…" };

  return (
    <div className="flex items-center gap-2" title={state.label}>
      <span
        className={cn(
          "inline-block h-2 w-2 rounded-full",
          state.tone,
          isFetching && "animate-pulse",
        )}
      />
      <span className="hidden text-xs text-muted-foreground sm:inline">{state.label}</span>
    </div>
  );
}
