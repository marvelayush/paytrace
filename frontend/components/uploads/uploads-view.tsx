"use client";

import { useState } from "react";

import { ErrorState, PageHeader } from "@/components/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { SourcesTable } from "@/components/uploads/sources-table";
import { RejectedRowsDialog, UploadHistory } from "@/components/uploads/upload-history";
import { UploadPanel } from "@/components/uploads/upload-panel";
import { canEdit, useCurrentUser } from "@/lib/auth";
import { type Upload, useSources, useUploads } from "@/lib/uploads";

export function UploadsView() {
  const { data: user } = useCurrentUser();
  const sources = useSources();
  const uploads = useUploads();
  const [errorsFor, setErrorsFor] = useState<Upload | null>(null);
  const editor = canEdit(user);

  function showErrorsById(uploadId: number) {
    const upload = uploads.data?.find((item) => item.id === uploadId);
    if (upload) setErrorsFor(upload);
  }

  return (
    <>
      <PageHeader
        title="Uploads"
        description="Upload each partner's settlement, COD remittance, freight and order reports. Columns are matched to a saved mapping, or reviewed when a partner changes its format."
      />

      {editor && (
        <div className="mb-8">
          {sources.isPending ? (
            <Skeleton className="h-56 w-full rounded-xl" />
          ) : sources.error ? (
            <ErrorState title="Couldn't load report types" message={sources.error.message} onRetry={() => sources.refetch()} />
          ) : (
            <UploadPanel sources={sources.data} onShowErrors={showErrorsById} />
          )}
        </div>
      )}

      <Tabs defaultValue="history">
        <TabsList>
          <TabsTrigger value="history">Upload history</TabsTrigger>
          <TabsTrigger value="sources">Reports and mappings</TabsTrigger>
        </TabsList>
        <TabsContent value="history" className="mt-4">
          <UploadHistory onShowErrors={setErrorsFor} />
        </TabsContent>
        <TabsContent value="sources" className="mt-4">
          {sources.data ? (
            <SourcesTable sources={sources.data} canEdit={editor} />
          ) : sources.error ? (
            <ErrorState title="Couldn't load report types" message={sources.error.message} onRetry={() => sources.refetch()} />
          ) : (
            <Skeleton className="h-64 w-full rounded-xl" />
          )}
        </TabsContent>
      </Tabs>

      <RejectedRowsDialog upload={errorsFor} onClose={() => setErrorsFor(null)} />
    </>
  );
}
