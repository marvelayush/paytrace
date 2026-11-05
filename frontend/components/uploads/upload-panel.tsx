"use client";

import { Check, CircleAlert, CircleCheck, FileSpreadsheet } from "lucide-react";
import { m } from "motion/react";
import { useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { EASE_OUT } from "@/components/motion";
import { checkFile, DropZone } from "@/components/uploads/drop-zone";
import { MappingReview } from "@/components/uploads/mapping-review";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from "@/components/ui/select";
import { formatCount, formatDuration, formatINRCompact } from "@/lib/format";
import {
  FILE_KIND_LABELS,
  type Inspection,
  type Mapping,
  type ProcessResult,
  type Source,
  useInspect,
  useProcess,
} from "@/lib/uploads";
import { cn } from "@/lib/utils";

/** What the user sees while a file goes through: Parsing → Mapping → Matching → Done. */
const STEPS = ["Parsing", "Mapping", "Matching", "Done"] as const;
type StepName = (typeof STEPS)[number];

type Stage =
  | { name: "choose" }
  | { name: "inspecting"; filename: string; sent: number }
  | { name: "review"; inspection: Inspection }
  | { name: "processing"; filename: string; version: number }
  | { name: "done"; result: ProcessResult; totalMs: number };

function groupByPartner(sources: Source[]): [string, Source[]][] {
  const groups = new Map<string, Source[]>();
  for (const source of sources) {
    groups.set(source.partner_name, [...(groups.get(source.partner_name) ?? []), source]);
  }
  return [...groups.entries()];
}

function Stepper({ current, done }: { current: StepName; done?: boolean }) {
  const currentIndex = STEPS.indexOf(current);
  return (
    <ol className="flex items-center gap-2 text-xs sm:gap-3" aria-label="Progress">
      {STEPS.map((step, index) => {
        const complete = index < currentIndex || (done && index === currentIndex);
        const active = index === currentIndex && !done;
        return (
          <li key={step} className="flex items-center gap-2 sm:gap-3" aria-current={active ? "step" : undefined}>
            <span className={cn("flex items-center gap-1.5", complete ? "text-foreground" : active ? "font-medium text-foreground" : "text-muted-foreground")}>
              <span
                className={cn(
                  "flex size-4 items-center justify-center rounded-full border transition-colors duration-200",
                  complete && "border-settled bg-settled text-card",
                  active && "border-primary",
                )}
                aria-hidden
              >
                {complete ? <Check className="size-2.5" strokeWidth={3} /> : active ? <span className="size-1.5 animate-pulse rounded-full bg-primary" /> : null}
              </span>
              {step}
            </span>
            {index < STEPS.length - 1 && <span aria-hidden className={cn("h-px w-4 sm:w-8", index < currentIndex ? "bg-settled" : "bg-border")} />}
          </li>
        );
      })}
    </ol>
  );
}

/** Progress bar: real upload progress while sending, then a steady creep while the server works. */
function ProgressBar({ value, working }: { value: number; working: boolean }) {
  return (
    <div className="relative h-1.5 w-full overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(value)}>
      <m.div
        className="absolute inset-y-0 left-0 rounded-full bg-primary"
        initial={false}
        animate={{ width: `${value}%` }}
        transition={{ duration: working ? 1.2 : 0.25, ease: EASE_OUT }}
      />
    </div>
  );
}

function WorkingCard({ stage }: { stage: Extract<Stage, { name: "inspecting" | "processing" }> }) {
  const inspecting = stage.name === "inspecting";
  const uploading = inspecting && stage.sent < 1;
  const step: StepName = inspecting ? "Parsing" : "Matching";
  // Sending the file fills the first 40%; the server's work then eases towards the next milestone.
  const value = inspecting ? (uploading ? stage.sent * 40 : 52) : 88;
  const text = uploading
    ? `Uploading… ${Math.round(stage.sent * 100)}%`
    : inspecting
      ? "Parsing rows and recognising the columns…"
      : `Matching every order with mapping v${stage.version} and re-running reconciliation…`;
  return (
    <div className="space-y-4 rounded-xl border border-dashed px-5 py-6" aria-live="polite">
      <Stepper current={step} />
      <ProgressBar value={value} working={!uploading} />
      <div className="flex items-center gap-3">
        <FileSpreadsheet className="size-5 shrink-0 text-muted-foreground" aria-hidden />
        <div className="min-w-0">
          <p className="text-sm font-medium">{text}</p>
          <p className="truncate text-xs text-muted-foreground">{stage.filename}</p>
        </div>
      </div>
    </div>
  );
}

function ResultCard({
  result,
  totalMs,
  onAnother,
  onShowErrors,
}: {
  result: ProcessResult;
  totalMs: number;
  onAnother: () => void;
  onShowErrors: (id: number) => void;
}) {
  const { upload, reconciliation } = result;
  const failed = upload.status === "failed";
  return (
    <m.div
      role="status"
      className="space-y-4 rounded-xl border bg-card p-5"
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, ease: EASE_OUT }}
    >
      {!failed && <Stepper current="Done" done />}
      <div className="flex items-start gap-3">
        <span
          className={cn(
            "flex size-9 shrink-0 items-center justify-center rounded-full",
            failed ? "bg-loss-soft text-loss" : "bg-settled-soft text-settled",
          )}
        >
          {failed ? <CircleAlert className="size-5" aria-hidden /> : <CircleCheck className="size-5" aria-hidden />}
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold">
            {failed ? "This file could not be processed" : `Done in ${formatDuration(totalMs)} of processing`}
          </h2>
          <p className="truncate text-sm text-muted-foreground">
            {upload.filename} · {upload.partner_name} {FILE_KIND_LABELS[upload.file_kind].toLowerCase()}
            {upload.mapping_version !== null && ` · mapping v${upload.mapping_version}`}
          </p>
          {failed && upload.error && <p className="mt-2 text-sm text-loss">{upload.error}</p>}
        </div>
      </div>

      {!failed && (
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            ["Rows saved", formatCount(upload.rows_ok), ""],
            ["Rejected", formatCount(upload.rows_rejected), upload.rows_rejected ? "text-loss" : ""],
            ["Already uploaded", formatCount(upload.rows_duplicate), ""],
            ["Server time", formatDuration(upload.duration_ms), ""],
          ].map(([label, value, tone]) => (
            <div key={label} className="rounded-lg border px-3 py-2">
              <dt className="text-xs text-muted-foreground">{label}</dt>
              <dd className={cn("money text-base font-semibold", tone)}>{value}</dd>
            </div>
          ))}
        </dl>
      )}

      {reconciliation && (
        <p className="text-sm text-muted-foreground">
          Reconciliation re-ran on {formatCount(reconciliation.order_count)} orders in {formatDuration(reconciliation.duration_ms)}. Money at
          risk is now <span className="money font-medium text-loss">{formatINRCompact(reconciliation.money_at_risk_paise)}</span>.
        </p>
      )}

      <div className="flex flex-wrap gap-2">
        {upload.rows_rejected > 0 && (
          <Button variant="outline" size="sm" onClick={() => onShowErrors(upload.id)}>
            See rejected rows
          </Button>
        )}
        <Button size="sm" onClick={onAnother}>
          Upload another file
        </Button>
      </div>
    </m.div>
  );
}

export function UploadPanel({ sources, onShowErrors }: { sources: Source[]; onShowErrors: (uploadId: number) => void }) {
  const [sourceId, setSourceId] = useState<string>("");
  const [stage, setStage] = useState<Stage>({ name: "choose" });
  const [fileError, setFileError] = useState<string | null>(null);
  // Machine time only: uploading and parsing, then processing. Time spent reviewing the mapping is not counted.
  const inspectMs = useRef(0);
  const inspect = useInspect();
  const process = useProcess();

  const groups = useMemo(() => groupByPartner(sources), [sources]);
  const selected = sources.find((source) => String(source.id) === sourceId);

  function runProcess(token: string, mapping: Pick<Mapping, "id" | "version">, filename: string) {
    setStage({ name: "processing", filename, version: mapping.version });
    const processStarted = performance.now();
    process.mutate(
      { token, mappingId: mapping.id },
      {
        onSuccess: (result) => {
          const totalMs = Math.round(inspectMs.current + performance.now() - processStarted);
          setStage({ name: "done", result, totalMs });
          const { upload } = result;
          if (upload.status === "done") {
            toast.success(
              upload.rows_ok === 0 && upload.rows_duplicate > 0
                ? `${upload.filename}: nothing new, all ${formatCount(upload.rows_duplicate)} rows were already uploaded`
                : `${upload.filename}: ${formatCount(upload.rows_ok)} rows saved in ${formatDuration(totalMs)}`,
            );
          } else {
            toast.error(`${result.upload.filename} could not be processed`);
          }
        },
        onError: (error) => {
          toast.error(`Processing failed: ${error.message}`);
          setStage({ name: "choose" });
        },
      },
    );
  }

  function handleFile(file: File) {
    const problem = checkFile(file);
    setFileError(problem);
    if (problem || !selected) return;
    const inspectStarted = performance.now();
    setStage({ name: "inspecting", filename: file.name, sent: 0 });
    inspect.mutate(
      {
        sourceId: selected.id,
        file,
        onProgress: (sent) => setStage((current) => (current.name === "inspecting" ? { ...current, sent } : current)),
      },
      {
        onSuccess: (inspection) => {
          inspectMs.current = performance.now() - inspectStarted;
          if (inspection.decision === "reuse" && inspection.active_mapping) {
            toast.message(`Using saved mapping v${inspection.active_mapping.version}`);
            runProcess(inspection.token, inspection.active_mapping, inspection.filename);
          } else {
            setStage({ name: "review", inspection });
          }
        },
        onError: () => setStage({ name: "choose" }),
      },
    );
  }

  function reset() {
    inspect.reset();
    process.reset();
    setFileError(null);
    setStage({ name: "choose" });
  }

  if (stage.name === "review") {
    return (
      <div className="space-y-4">
        <div className="rounded-xl border bg-card px-5 py-4">
          <Stepper current="Mapping" />
        </div>
        <MappingReview
          inspection={stage.inspection}
          onCancel={reset}
          onApproved={(mapping) => runProcess(stage.inspection.token, mapping, stage.inspection.filename)}
        />
      </div>
    );
  }

  if (stage.name === "done") {
    return <ResultCard result={stage.result} totalMs={stage.totalMs} onAnother={reset} onShowErrors={onShowErrors} />;
  }

  const busy = stage.name === "inspecting" || stage.name === "processing";
  const error = fileError ?? inspect.error?.message ?? process.error?.message;

  return (
    <div className="space-y-4 rounded-xl border bg-card p-5">
      <div className="space-y-1.5">
        <Label htmlFor="upload-source">Which report is this?</Label>
        <Select value={sourceId} onValueChange={setSourceId} disabled={busy}>
          <SelectTrigger id="upload-source" className="h-10 w-full bg-card sm:max-w-md">
            <SelectValue placeholder="Choose partner and report" />
          </SelectTrigger>
          <SelectContent>
            {groups.map(([partner, partnerSources]) => (
              <SelectGroup key={partner}>
                <SelectLabel>{partner}</SelectLabel>
                {partnerSources.map((source) => (
                  <SelectItem key={source.id} value={String(source.id)}>
                    {partner} · {FILE_KIND_LABELS[source.file_kind]}
                  </SelectItem>
                ))}
              </SelectGroup>
            ))}
          </SelectContent>
        </Select>
        {selected && (
          <p className="text-xs text-muted-foreground">
            {selected.active_mapping_version
              ? `Files in the usual layout use saved mapping v${selected.active_mapping_version}. A changed layout opens the mapping review.`
              : "No saved mapping yet: you will review the columns on the first upload."}
          </p>
        )}
      </div>

      {busy ? (
        <WorkingCard stage={stage} />
      ) : (
        <DropZone disabled={!selected} onFile={handleFile} hint={selected ? undefined : "Choose the partner and report first"} />
      )}

      {error && (
        <Alert variant="destructive" className="border-loss/20 bg-loss-soft">
          <CircleAlert />
          <AlertDescription className="text-loss">{error}</AlertDescription>
        </Alert>
      )}
    </div>
  );
}
