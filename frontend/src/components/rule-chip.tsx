import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { lookupRule } from "@/lib/policyRules";

export function RuleChip({ rule }: { rule: string }) {
  const [open, setOpen] = useState(false);
  const resolved = lookupRule(rule);
  const label = resolved?.id ?? rule;

  return (
    <>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setOpen(true);
        }}
        className="mono rounded border border-info/40 bg-info-soft px-1.5 py-0.5 text-[11px] font-semibold text-info transition-colors hover:bg-info/15"
      >
        {label}
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>
              {label} — {resolved?.title ?? "Policy rule"}
            </DialogTitle>
            <DialogDescription className="pt-2 text-sm leading-relaxed text-foreground">
              {resolved?.text ?? `No reference text available for “${rule}”.`}
            </DialogDescription>
          </DialogHeader>
          <p className="text-xs text-muted-foreground">
            Reference text from the fraud policy. Rule evaluation runs in the backend policy
            engine.
          </p>
        </DialogContent>
      </Dialog>
    </>
  );
}
