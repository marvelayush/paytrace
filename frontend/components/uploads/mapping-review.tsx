"use client";

import { CircleAlert, CircleCheck, LoaderCircle, Sparkles, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { formatDate, formatDateTime, formatINR, formatWeight } from "@/lib/format";
import {
  type Inspection,
  type Mapping,
  type Preview,
  type PreviewField,
  sourceLabel,
  useApproveMapping,
  usePreviewMapping,
} from "@/lib/uploads";
import { cn } from "@/lib/utils";

const NOT_IN_FILE = "__none__";

function displayValue(field: PreviewField, value: string | number | null): string {
  if (value === null || value === undefined || value === "") return "—";
  switch (field.type) {
    case "money":
      return formatINR(Number(value));
    case "date":
      return formatDate(String(value));
    case "datetime":
      return formatDateTime(String(value));
    case "weight":
      return formatWeight(Number(value));
    default:
      return String(value);
  }
}

function ConfidenceBadge({ confidence }: { confidence: number | null }) {
  if (confidence === null) {
    return <span className="text-xs text-muted-foreground">Chosen by you</span>;
  }
  const percent = Math.round(confidence * 100);
  if (confidence >= 0.9) {
    return <Badge className="border-settled/20 bg-settled-soft font-medium text-settled">High · {percent}%</Badge>;
  }
  if (confidence >= 0.7) {
    return <Badge variant="secondary" className="font-medium">Medium · {percent}%</Badge>;
  }
  return <Badge className="border-attention/25 bg-attention-soft font-medium text-attention">Low · {percent}%</Badge>;
}

function EngineNotice({ inspection }: { inspection: Inspection }) {
  const { engine, notice } = inspection.suggestion;
  if (inspection.matched_version !== null) {
    return (
      <p className="flex items-start gap-2 text-sm text-muted-foreground">
        <CircleCheck className="mt-0.5 size-4 shrink-0 text-settled" aria-hidden />
        This layout matches saved mapping v{inspection.matched_version}. Check it and approve to use it again.
      </p>
    );
  }
  if (notice) {
    return (
      <p className="flex items-start gap-2 text-sm text-attention">
        <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
        {notice}. Check every field before approving.
      </p>
    );
  }
  return (
    <p className="flex items-start gap-2 text-sm text-muted-foreground">
      <Sparkles className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
      {engine === "llm" ? "AI suggested these columns" : "Suggested from column names"} because the file&apos;s columns differ from the
      saved mapping. Nothing is saved until you approve.
    </p>
  );
}

export function MappingReview({
  inspection,
  onApproved,
  onCancel,
}: {
  inspection: Inspection;
  onApproved: (mapping: Mapping) => void;
  onCancel: () => void;
}) {
  const sourceId = inspection.source.id;
  const [columns, setColumns] = useState<Record<string, string | null>>(() =>
    Object.fromEntries(inspection.preview.fields.map((field) => [field.name, field.source_column])),
  );
  const [preview, setPreview] = useState<Preview>(inspection.preview);
  const [confirmed, setConfirmed] = useState<Set<string>>(new Set());
  const [touched, setTouched] = useState<Set<string>>(new Set());
  const [notes, setNotes] = useState("");

  const recheck = usePreviewMapping(sourceId);
  const approve = useApproveMapping(sourceId);
  const firstRender = useRef(true);

  // Re-run the 20-row check shortly after the user changes a column.
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    const timer = setTimeout(() => {
      recheck.mutate({ token: inspection.token, columns }, { onSuccess: setPreview });
    }, 250);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- re-run only when the chosen columns change
  }, [columns]);

  // Confidence and reasons belong to the AI's picks; the latest preview supplies counts and flags.
  const fields = useMemo(
    () =>
      preview.fields.map((field) => {
        const original = inspection.preview.fields.find((item) => item.name === field.name);
        const keptSuggestion = original && original.source_column === columns[field.name];
        return {
          ...field,
          confidence: keptSuggestion ? original.confidence : null,
          reason: keptSuggestion ? original.reason : null,
        };
      }),
    [preview.fields, inspection.preview.fields, columns],
  );

  const needsLook = fields.filter((field) => {
    const lowConfidence = field.source_column && field.confidence !== null && field.confidence < 0.7;
    return field.error_count > 0 || Boolean(field.warning) || (field.required && !field.source_column) || lowConfidence;
  });
  const unresolved = needsLook.filter(
    (field) =>
      (field.required && !field.source_column) ||
      (!confirmed.has(field.name) && !(touched.has(field.name) && field.error_count === 0 && !field.warning)),
  );
  const missingOneOf = fields.find(
    (field) => field.one_of_group && !field.one_of_group.some((name) => columns[name]),
  );

  const mappedFields = fields.filter((field) => columns[field.name]);

  function choose(fieldName: string, value: string) {
    setColumns((current) => ({ ...current, [fieldName]: value === NOT_IN_FILE ? null : value }));
    setTouched((current) => new Set(current).add(fieldName));
    setConfirmed((current) => {
      const next = new Set(current);
      next.delete(fieldName);
      return next;
    });
  }

  function toggleConfirmed(fieldName: string, value: boolean) {
    setConfirmed((current) => {
      const next = new Set(current);
      if (value) next.add(fieldName);
      else next.delete(fieldName);
      return next;
    });
  }

  const canApprove = unresolved.length === 0 && !missingOneOf && !recheck.isPending && !approve.isPending;

  return (
    <section aria-labelledby="review-title" className="space-y-6">
      <div className="rounded-xl border bg-card p-5">
        <div className="flex flex-col gap-1">
          <h2 id="review-title" className="text-base font-semibold">
            Review column mapping
          </h2>
          <p className="text-sm text-muted-foreground">
            {sourceLabel(inspection.source)} · <span className="font-medium text-foreground">{inspection.filename}</span>
          </p>
        </div>
        <div className="mt-3">
          <EngineNotice inspection={inspection} />
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
        {/* Field-by-field mapping */}
        <div className="rounded-xl border bg-card">
          <div className="flex items-center justify-between border-b px-4 py-3">
            <h3 className="text-sm font-semibold">Columns</h3>
            {needsLook.length > 0 ? (
              <span className="text-xs text-attention">
                {unresolved.length > 0 ? `${unresolved.length} to check` : "All checked"}
              </span>
            ) : (
              <span className="text-xs text-settled">All fields look right</span>
            )}
          </div>
          <ul className="divide-y">
            {fields.map((field) => {
              const flagged = needsLook.includes(field);
              const isResolved = !unresolved.includes(field);
              return (
                <li
                  key={field.name}
                  className={cn("space-y-2 px-4 py-3", flagged && !isResolved && "bg-attention-soft/60")}
                >
                  <div className="flex items-center justify-between gap-2">
                    <Label htmlFor={`map-${field.name}`} className="gap-1.5">
                      {field.label}
                      {field.required && <span className="text-xs font-normal text-muted-foreground">required</span>}
                      {field.pii && <span className="text-xs font-normal text-muted-foreground">· masked</span>}
                    </Label>
                    {field.source_column && <ConfidenceBadge confidence={field.confidence} />}
                  </div>
                  <Select value={columns[field.name] ?? NOT_IN_FILE} onValueChange={(value) => choose(field.name, value)}>
                    <SelectTrigger
                      id={`map-${field.name}`}
                      className="h-9 w-full bg-card"
                      aria-invalid={(field.required && !field.source_column) || field.error_count > 0 || undefined}
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={NOT_IN_FILE}>
                        <span className="text-muted-foreground">Not in this file</span>
                      </SelectItem>
                      {inspection.headers.map((header) => (
                        <SelectItem key={header} value={header}>
                          {header}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {field.reason && <p className="text-xs text-muted-foreground">{field.reason}</p>}
                  {field.error_count > 0 && (
                    <p className="text-xs text-loss">
                      {field.error_count} of {preview.rows_checked} preview rows don&apos;t parse as {field.type.replace("_", " ")}.
                    </p>
                  )}
                  {field.warning && (
                    <p className="flex items-start gap-1.5 text-xs text-attention">
                      <TriangleAlert className="mt-px size-3.5 shrink-0" aria-hidden />
                      {field.warning}
                    </p>
                  )}
                  {field.required && !field.source_column && (
                    <p className="text-xs text-loss">Required: pick the column that holds this.</p>
                  )}
                  {flagged && field.source_column && (
                    <label className="flex items-center gap-2 text-xs">
                      <Checkbox
                        checked={confirmed.has(field.name)}
                        onCheckedChange={(value) => toggleConfirmed(field.name, value === true)}
                      />
                      I checked this column is right
                    </label>
                  )}
                </li>
              );
            })}
          </ul>
        </div>

        {/* 20-row preview */}
        <div className="min-w-0 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold">
              Preview of the first {preview.rows_checked} rows
              {recheck.isPending && <LoaderCircle className="ml-2 inline size-4 animate-spin text-muted-foreground" aria-label="Checking" />}
            </h3>
            <span className={cn("text-xs", preview.rows_with_errors ? "text-loss" : "text-settled")}>
              {preview.rows_with_errors ? `${preview.rows_with_errors} rows would be rejected` : "Every row parses"}
            </span>
          </div>
          <div className="overflow-x-auto rounded-xl border bg-card">
            <table className="w-full min-w-max text-sm">
              <thead className="bg-muted/50">
                <tr>
                  <th scope="col" className="sticky left-0 bg-muted/90 px-3 py-2 text-left text-xs font-medium text-muted-foreground">
                    Row
                  </th>
                  {mappedFields.map((field) => (
                    <th key={field.name} scope="col" className="px-3 py-2 text-left text-xs font-medium whitespace-nowrap text-muted-foreground">
                      {field.label}
                      <span className="block font-normal text-muted-foreground/80">{columns[field.name]}</span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y">
                {preview.rows.map((row) => (
                  <tr key={row.row_number}>
                    <td className="money sticky left-0 bg-card px-3 py-2 text-xs text-muted-foreground">{row.row_number}</td>
                    {mappedFields.map((field) => {
                      const error = row.errors[field.name];
                      return (
                        <td
                          key={field.name}
                          className={cn(
                            "px-3 py-2 whitespace-nowrap",
                            field.type === "money" && "money text-right",
                            error && "bg-loss-soft text-loss",
                          )}
                          title={error}
                        >
                          {error ? (
                            <span className="flex items-center gap-1">
                              <CircleAlert className="size-3.5 shrink-0" aria-hidden />
                              <span className="sr-only">Error: </span>
                              {row.raw[field.name] ?? "empty"}
                            </span>
                          ) : (
                            displayValue(field, row.values[field.name])
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-muted-foreground">
            Values are shown as PayTrace will store them. Hover a red cell to see why it fails. Personal data is masked.
          </p>
        </div>
      </div>

      <div className="space-y-4 rounded-xl border bg-card p-5">
        <div className="space-y-1.5">
          <Label htmlFor="mapping-notes">Note for the version history (optional)</Label>
          <Textarea
            id="mapping-notes"
            value={notes}
            maxLength={500}
            onChange={(event) => setNotes(event.target.value)}
            placeholder="e.g. Marketplace 1 renamed its settlement columns in November"
            className="min-h-16 bg-card"
          />
        </div>

        {(approve.error || recheck.error) && (
          <Alert variant="destructive" className="border-loss/20 bg-loss-soft">
            <CircleAlert />
            <AlertDescription className="text-loss">{(approve.error ?? recheck.error)?.message}</AlertDescription>
          </Alert>
        )}

        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-muted-foreground">
            {canApprove
              ? "Approving saves this as a new mapping version. Earlier versions stay available for rollback."
              : missingOneOf
                ? `Map at least one of: ${missingOneOf.one_of_group?.join(" or ")}.`
                : `Check the ${unresolved.length} highlighted field${unresolved.length === 1 ? "" : "s"} first.`}
          </p>
          <div className="flex gap-2">
            <Button variant="outline" onClick={onCancel} disabled={approve.isPending}>
              Cancel
            </Button>
            <Button
              disabled={!canApprove}
              onClick={() => approve.mutate({ token: inspection.token, columns, notes }, { onSuccess: onApproved })}
            >
              {approve.isPending && <LoaderCircle className="animate-spin" aria-hidden />}
              Approve and process file
            </Button>
          </div>
        </div>
      </div>
    </section>
  );
}
