"use client";

import { Download, FileClock, LoaderCircle } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { EmptyState, ErrorState } from "@/components/page-header";
import { StatusPill } from "@/components/status-pill";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { downloadFile } from "@/lib/api";
import { formatCount, formatDateTime, formatDuration } from "@/lib/format";
import { FILE_KIND_LABELS, type Upload, useUploadErrors, useUploads } from "@/lib/uploads";

const UPLOAD_STATUS: Record<Upload["status"], { label: string; tone: "settled" | "loss" | "attention" | "neutral" }> = {
  done: { label: "Done", tone: "settled" },
  failed: { label: "Failed", tone: "loss" },
  processing: { label: "Processing", tone: "attention" },
  pending: { label: "Pending", tone: "neutral" },
};

export function RejectedRowsDialog({ upload, onClose }: { upload: Upload | null; onClose: () => void }) {
  const errors = useUploadErrors(upload?.id ?? null);
  const [downloading, setDownloading] = useState(false);

  async function download() {
    if (!upload) return;
    setDownloading(true);
    try {
      await downloadFile(`/uploads/${upload.id}/errors.csv`, "rejected-rows.csv");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Download failed");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <Dialog open={upload !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[85dvh] overflow-hidden sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Rejected rows</DialogTitle>
          <DialogDescription>
            {upload ? `${formatCount(upload.rows_rejected)} rows of ${upload.filename} were not saved. Fix them in the file and upload it again; rows already saved are not duplicated.` : ""}
          </DialogDescription>
        </DialogHeader>
        <div className="max-h-[50dvh] overflow-y-auto rounded-lg border">
          {errors.isPending ? (
            <div className="space-y-2 p-3">
              {Array.from({ length: 6 }, (_, index) => (
                <Skeleton key={index} className="h-6 w-full" />
              ))}
            </div>
          ) : errors.error ? (
            <p className="p-4 text-sm text-loss">{errors.error.message}</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-muted">
                <tr>
                  <th scope="col" className="w-20 px-3 py-2 text-left text-xs font-medium text-muted-foreground">Row</th>
                  <th scope="col" className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">Why it was rejected</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {errors.data?.map((error) => (
                  <tr key={error.row_number}>
                    <td className="money px-3 py-2 align-top text-muted-foreground">{error.row_number}</td>
                    <td className="px-3 py-2">{error.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div className="flex justify-end">
          <Button variant="outline" onClick={download} disabled={downloading}>
            {downloading ? <LoaderCircle className="animate-spin" aria-hidden /> : <Download aria-hidden />}
            Download CSV
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function UploadHistory({ onShowErrors }: { onShowErrors: (upload: Upload) => void }) {
  const uploads = useUploads();

  if (uploads.isPending) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 5 }, (_, index) => (
          <Skeleton key={index} className="h-11 w-full" />
        ))}
      </div>
    );
  }
  if (uploads.error) {
    return <ErrorState title="Couldn't load upload history" message={uploads.error.message} onRetry={() => uploads.refetch()} />;
  }
  if (!uploads.data.length) {
    return (
      <EmptyState icon={FileClock} title="No files uploaded yet">
        Every report you upload is listed here with its row counts, rejected rows and how long it took.
      </EmptyState>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border bg-card">
      <table className="w-full min-w-[56rem] text-sm">
        <thead className="bg-muted/50">
          <tr className="text-left text-xs font-medium text-muted-foreground">
            <th scope="col" className="px-4 py-2.5 font-medium">File</th>
            <th scope="col" className="px-4 py-2.5 font-medium">Report</th>
            <th scope="col" className="px-4 py-2.5 text-right font-medium">Rows</th>
            <th scope="col" className="px-4 py-2.5 text-right font-medium">Saved</th>
            <th scope="col" className="px-4 py-2.5 text-right font-medium">Rejected</th>
            <th scope="col" className="px-4 py-2.5 text-right font-medium">Duplicates</th>
            <th scope="col" className="px-4 py-2.5 font-medium">Status</th>
            <th scope="col" className="px-4 py-2.5 text-right font-medium">Took</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {uploads.data.map((upload) => (
            <tr key={upload.id} className="align-top">
              <td className="max-w-64 px-4 py-2.5">
                <span className="block truncate font-medium" title={upload.filename}>{upload.filename}</span>
                <span className="block text-xs text-muted-foreground">
                  {formatDateTime(upload.created_at)}
                  {upload.uploaded_by_name && ` · ${upload.uploaded_by_name}`}
                </span>
              </td>
              <td className="px-4 py-2.5">
                <span className="block">{upload.partner_name}</span>
                <span className="block text-xs text-muted-foreground">
                  {FILE_KIND_LABELS[upload.file_kind]}
                  {upload.mapping_version !== null && ` · mapping v${upload.mapping_version}`}
                </span>
              </td>
              <td className="money px-4 py-2.5 text-right">{formatCount(upload.row_count)}</td>
              <td className="money px-4 py-2.5 text-right">{formatCount(upload.rows_ok)}</td>
              <td className="money px-4 py-2.5 text-right">
                {upload.rows_rejected ? (
                  <button
                    type="button"
                    onClick={() => onShowErrors(upload)}
                    className="rounded font-medium text-loss underline underline-offset-4 outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                  >
                    {formatCount(upload.rows_rejected)}
                  </button>
                ) : (
                  <span className="text-muted-foreground">0</span>
                )}
              </td>
              <td className="money px-4 py-2.5 text-right text-muted-foreground">{formatCount(upload.rows_duplicate)}</td>
              <td className="px-4 py-2.5">
                <StatusPill {...UPLOAD_STATUS[upload.status]} />
                {upload.error && <span className="mt-1 block max-w-56 text-xs text-loss">{upload.error}</span>}
              </td>
              <td className="money px-4 py-2.5 text-right text-muted-foreground">{formatDuration(upload.duration_ms)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
