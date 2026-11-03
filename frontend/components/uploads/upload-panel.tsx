"use client";

import { CircleAlert, CircleCheck, FileSpreadsheet, LoaderCircle } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

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

type Stage =
  | { name: "choose" }
  | { name: "inspecting"; filename: string }
  | { name: "review"; inspection: Inspection }
  | { name: "processing"; filename: string; version: number }
  | { name: "done"; result: ProcessResult };

function groupByPartner(sources: Source[]): [string, Source[]][] {
  const groups = new Map<string, Source[]>();
  for (const source of sources) {
    groups.set(source.partner_name, [...(groups.get(source.partner_name) ?? []), source]);
  }
  return [...groups.entries()];
}

function ResultCard({ result, onAnother, onShowErrors }: { result: ProcessResult; onAnother: () => void; onShowErrors: (id: number) => void }) {
  const { upload, reconciliation } = result;
  const failed = upload.status === "failed";
  return (
    <div role="status" className="rounded-xl border bg-card p-5">
      <div className="flex items-start gap-3">
        <span
          className={`flex size-9 shrink-0 items-center justify-center rounded-full ${failed ? "bg-loss-soft text-loss" : "bg-settled-soft text-settled"}`}
        >
          {failed ? <CircleAlert className="size-5" aria-hidden /> : <CircleCheck className="size-5" aria-hidden />}
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold">{failed ? "This file could not be processed" : "File processed"}</h2>
          <p className="truncate text-sm text-muted-foreground">
            {upload.filename} · {upload.partner_name} {FILE_KIND_LABELS[upload.file_kind].toLowerCase()}
            {upload.mapping_version !== null && ` · mapping v${upload.mapping_version}`}
          </p>
          {failed && upload.error && <p className="mt-2 text-sm text-loss">{upload.error}</p>}
        </div>
      </div>

      {!failed && (
        <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            ["Rows saved", formatCount(upload.rows_ok), ""],
            ["Rejected", formatCount(upload.rows_rejected), upload.rows_rejected ? "text-loss" : ""],
            ["Already uploaded", formatCount(upload.rows_duplicate), ""],
            ["Took", formatDuration(upload.duration_ms), ""],
          ].map(([label, value, tone]) => (
            <div key={label} className="rounded-lg border px-3 py-2">
              <dt className="text-xs text-muted-foreground">{label}</dt>
              <dd className={`money text-base font-semibold ${tone}`}>{value}</dd>
            </div>
          ))}
        </dl>
      )}

      {reconciliation && (
        <p className="mt-4 text-sm text-muted-foreground">
          Reconciliation re-ran on {formatCount(reconciliation.order_count)} orders in {formatDuration(reconciliation.duration_ms)}. Money at
          risk is now <span className="money font-medium text-loss">{formatINRCompact(reconciliation.money_at_risk_paise)}</span>.
        </p>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        {upload.rows_rejected > 0 && (
          <Button variant="outline" size="sm" onClick={() => onShowErrors(upload.id)}>
            See rejected rows
          </Button>
        )}
        <Button size="sm" onClick={onAnother}>
          Upload another file
        </Button>
      </div>
    </div>
  );
}

export function UploadPanel({ sources, onShowErrors }: { sources: Source[]; onShowErrors: (uploadId: number) => void }) {
  const [sourceId, setSourceId] = useState<string>("");
  const [stage, setStage] = useState<Stage>({ name: "choose" });
  const [fileError, setFileError] = useState<string | null>(null);
  const inspect = useInspect();
  const process = useProcess();

  const groups = useMemo(() => groupByPartner(sources), [sources]);
  const selected = sources.find((source) => String(source.id) === sourceId);

  function runProcess(token: string, mapping: Pick<Mapping, "id" | "version">, filename: string) {
    setStage({ name: "processing", filename, version: mapping.version });
    process.mutate(
      { token, mappingId: mapping.id },
      {
        onSuccess: (result) => {
          setStage({ name: "done", result });
          if (result.upload.status === "done") toast.success(`${result.upload.filename} processed`);
        },
        onError: () => setStage({ name: "choose" }),
      },
    );
  }

  function handleFile(file: File) {
    const problem = checkFile(file);
    setFileError(problem);
    if (problem || !selected) return;
    setStage({ name: "inspecting", filename: file.name });
    inspect.mutate(
      { sourceId: selected.id, file },
      {
        onSuccess: (inspection) => {
          if (inspection.decision === "reuse" && inspection.active_mapping) {
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
      <MappingReview
        inspection={stage.inspection}
        onCancel={reset}
        onApproved={(mapping) => {
          toast.success(`Mapping v${mapping.version} saved for ${stage.inspection.source.name}`);
          runProcess(stage.inspection.token, mapping, stage.inspection.filename);
        }}
      />
    );
  }

  if (stage.name === "done") {
    return <ResultCard result={stage.result} onAnother={reset} onShowErrors={onShowErrors} />;
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
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed px-6 py-10 text-center" aria-live="polite">
          <FileSpreadsheet className="size-6 text-muted-foreground" aria-hidden />
          <p className="mt-3 flex items-center gap-2 text-sm font-medium">
            <LoaderCircle className="size-4 animate-spin" aria-hidden />
            {stage.name === "inspecting" ? "Reading columns…" : `Processing with mapping v${stage.version}…`}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">{stage.filename}</p>
        </div>
      ) : (
        <DropZone
          disabled={!selected}
          onFile={handleFile}
          hint={selected ? undefined : "Choose the partner and report first"}
        />
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
