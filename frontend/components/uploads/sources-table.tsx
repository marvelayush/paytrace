"use client";

import { History, LoaderCircle, RotateCcw } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { StatusPill } from "@/components/status-pill";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDateTime } from "@/lib/format";
import { FILE_KIND_LABELS, type Mapping, type Source, sourceLabel, useMappings, useRollback } from "@/lib/uploads";

const ENGINE_LABEL: Record<NonNullable<Mapping["engine"]>, string> = {
  llm: "AI suggested",
  fuzzy: "Name matching",
  saved: "From saved version",
};

function VersionsDialog({ source, canEdit, onClose }: { source: Source | null; canEdit: boolean; onClose: () => void }) {
  const mappings = useMappings(source?.id ?? null);
  const rollback = useRollback(source?.id ?? 0);

  return (
    <Dialog open={source !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Mapping versions</DialogTitle>
          <DialogDescription>
            {source ? sourceLabel(source) : ""}. Every approved mapping is kept. Roll back if a newer one turns out wrong.
          </DialogDescription>
        </DialogHeader>
        {mappings.isPending ? (
          <div className="space-y-2">
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-20 w-full" />
          </div>
        ) : mappings.error ? (
          <p className="text-sm text-loss">{mappings.error.message}</p>
        ) : (
          <ol className="space-y-3">
            {mappings.data.map((mapping) => (
              <li key={mapping.id} className="rounded-lg border p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold">v{mapping.version}</span>
                    {mapping.is_active && <StatusPill label="Active" tone="settled" />}
                    {mapping.engine && <span className="text-xs text-muted-foreground">{ENGINE_LABEL[mapping.engine]}</span>}
                  </div>
                  {canEdit && !mapping.is_active && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={rollback.isPending}
                      onClick={() =>
                        rollback.mutate(
                          { mappingId: mapping.id },
                          {
                            onSuccess: () => {
                              toast.success(`Rolled back to v${mapping.version}`);
                              mappings.refetch();
                            },
                            onError: (error) => toast.error(error.message),
                          },
                        )
                      }
                    >
                      {rollback.isPending && rollback.variables?.mappingId === mapping.id ? (
                        <LoaderCircle className="animate-spin" aria-hidden />
                      ) : (
                        <RotateCcw aria-hidden />
                      )}
                      Make active
                    </Button>
                  )}
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  Approved {formatDateTime(mapping.approved_at)}
                  {mapping.created_by_name && ` by ${mapping.created_by_name}`}
                </p>
                {mapping.notes && <p className="mt-2 text-sm">{mapping.notes}</p>}
                <details className="mt-2 text-xs">
                  <summary className="cursor-pointer text-muted-foreground">{Object.keys(mapping.columns).length} columns mapped</summary>
                  <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
                    {Object.entries(mapping.columns).map(([field, column]) => (
                      <div key={field} className="contents">
                        <dt className="text-muted-foreground">{field.replaceAll("_", " ")}</dt>
                        <dd className="font-medium">{column}</dd>
                      </div>
                    ))}
                  </dl>
                </details>
              </li>
            ))}
          </ol>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function SourcesTable({ sources, canEdit }: { sources: Source[]; canEdit: boolean }) {
  const [open, setOpen] = useState<Source | null>(null);
  return (
    <>
      <div className="overflow-x-auto rounded-xl border bg-card">
        <table className="w-full min-w-[40rem] text-sm">
          <thead className="bg-muted/50">
            <tr className="text-left text-xs text-muted-foreground">
              <th scope="col" className="px-4 py-2.5 font-medium">Partner</th>
              <th scope="col" className="px-4 py-2.5 font-medium">Report</th>
              <th scope="col" className="px-4 py-2.5 font-medium">Active mapping</th>
              <th scope="col" className="px-4 py-2.5 font-medium">Last upload</th>
              <th scope="col" className="px-4 py-2.5"><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {sources.map((source) => (
              <tr key={source.id}>
                <td className="px-4 py-2.5 font-medium">{source.partner_name}</td>
                <td className="px-4 py-2.5">{FILE_KIND_LABELS[source.file_kind]}</td>
                <td className="px-4 py-2.5">
                  {source.active_mapping_version ? (
                    <span>
                      v{source.active_mapping_version}
                      <span className="text-muted-foreground"> of {source.mapping_versions}</span>
                    </span>
                  ) : (
                    <span className="text-muted-foreground">None yet</span>
                  )}
                </td>
                <td className="px-4 py-2.5 text-muted-foreground">{formatDateTime(source.last_upload_at)}</td>
                <td className="px-4 py-2.5 text-right">
                  {source.mapping_versions > 0 && (
                    <Button size="sm" variant="ghost" onClick={() => setOpen(source)}>
                      <History aria-hidden /> Versions
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <VersionsDialog source={open} canEdit={canEdit} onClose={() => setOpen(null)} />
    </>
  );
}
