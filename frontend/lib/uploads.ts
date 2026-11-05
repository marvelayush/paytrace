"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, apiFetch, apiUpload } from "@/lib/api";

export type FileKind = "orders" | "settlement" | "cod_remittance" | "freight_invoice" | "warehouse_returns";

export const FILE_KIND_LABELS: Record<FileKind, string> = {
  orders: "Orders",
  settlement: "Settlement",
  cod_remittance: "COD remittance",
  freight_invoice: "Freight invoice",
  warehouse_returns: "Return scans",
};

export type Source = {
  id: number;
  partner_id: number;
  partner_name: string;
  partner_kind: string;
  file_kind: FileKind;
  name: string;
  active_mapping_version: number | null;
  mapping_versions: number;
  last_upload_at: string | null;
};

export type Mapping = {
  id: number;
  source_id: number;
  version: number;
  columns: Record<string, string>;
  is_active: boolean;
  approved_at: string | null;
  created_at: string;
  created_by_name: string | null;
  engine: "llm" | "fuzzy" | "saved" | null;
  notes: string | null;
};

export type PreviewField = {
  name: string;
  label: string;
  type: string;
  required: boolean;
  one_of_group: string[] | null;
  description: string;
  pii: boolean;
  source_column: string | null;
  confidence: number | null;
  reason: string | null;
  error_count: number;
  /** Rule-based plausibility warning (e.g. TCS and TDS look swapped). */
  warning: string | null;
  needs_confirmation: boolean;
};

export type PreviewRow = {
  row_number: number;
  values: Record<string, string | number | null>;
  raw: Record<string, string | null>;
  errors: Record<string, string>;
  row_error: string | null;
};

export type Preview = {
  fields: PreviewField[];
  rows: PreviewRow[];
  rows_checked: number;
  rows_with_errors: number;
};

export type Inspection = {
  token: string;
  filename: string;
  source: Source;
  headers: string[];
  decision: "reuse" | "review";
  active_mapping: Mapping | null;
  matched_version: number | null;
  suggestion: { engine: "llm" | "fuzzy" | "saved"; notice: string | null };
  preview: Preview;
};

export type Upload = {
  id: number;
  source_id: number;
  source_name: string;
  partner_name: string;
  file_kind: FileKind;
  mapping_version: number | null;
  filename: string;
  row_count: number;
  rows_ok: number;
  rows_rejected: number;
  rows_duplicate: number;
  status: "pending" | "processing" | "done" | "failed";
  error: string | null;
  uploaded_by_name: string | null;
  created_at: string;
  duration_ms: number | null;
};

export type ReconSummary = {
  run_id: number;
  order_count: number;
  duration_ms: number;
  status_counts: Record<string, number>;
  money_at_risk_paise: number;
};

export type ProcessResult = { upload: Upload; reconciliation: ReconSummary | null };

export type RowError = { row_number: number; reason: string };

export function sourceLabel(source: Pick<Source, "partner_name" | "file_kind">): string {
  return `${source.partner_name} · ${FILE_KIND_LABELS[source.file_kind]}`;
}

export function useSources() {
  return useQuery<Source[], ApiError>({ queryKey: ["sources"], queryFn: () => apiFetch<Source[]>("/sources") });
}

export function useUploads() {
  return useQuery<Upload[], ApiError>({ queryKey: ["uploads"], queryFn: () => apiFetch<Upload[]>("/uploads?limit=100") });
}

export function useUploadErrors(uploadId: number | null) {
  return useQuery<RowError[], ApiError>({
    queryKey: ["uploads", uploadId, "errors"],
    queryFn: () => apiFetch<RowError[]>(`/uploads/${uploadId}/errors?limit=500`),
    enabled: uploadId !== null,
  });
}

export function useMappings(sourceId: number | null) {
  return useQuery<Mapping[], ApiError>({
    queryKey: ["sources", sourceId, "mappings"],
    queryFn: () => apiFetch<Mapping[]>(`/sources/${sourceId}/mappings`),
    enabled: sourceId !== null,
  });
}

export function useInspect() {
  return useMutation<Inspection, ApiError, { sourceId: number; file: File; onProgress?: (fraction: number) => void }>({
    mutationFn: ({ sourceId, file, onProgress }) => {
      const form = new FormData();
      form.append("source_id", String(sourceId));
      form.append("file", file);
      return apiUpload<Inspection>("/uploads/inspect", form, onProgress);
    },
  });
}

/** Everything that changes after data is processed: lists, results, dashboard. */
function invalidateAfterProcessing(queryClient: ReturnType<typeof useQueryClient>) {
  for (const key of ["uploads", "sources", "recon", "dashboard", "claims"]) {
    queryClient.invalidateQueries({ queryKey: [key] });
  }
}

export function useProcess() {
  const queryClient = useQueryClient();
  return useMutation<ProcessResult, ApiError, { token: string; mappingId: number }>({
    mutationFn: ({ token, mappingId }) =>
      apiFetch<ProcessResult>(`/uploads/${token}/process`, { method: "POST", body: JSON.stringify({ mapping_id: mappingId }) }),
    onSuccess: () => invalidateAfterProcessing(queryClient),
  });
}

export function usePreviewMapping(sourceId: number) {
  return useMutation<Preview, ApiError, { token: string; columns: Record<string, string | null> }>({
    mutationFn: ({ token, columns }) =>
      apiFetch<Preview>(`/sources/${sourceId}/mappings/preview`, { method: "POST", body: JSON.stringify({ token, columns }) }),
  });
}

export function useApproveMapping(sourceId: number) {
  const queryClient = useQueryClient();
  return useMutation<Mapping, ApiError, { token: string; columns: Record<string, string | null>; notes: string }, MappingSnapshot>({
    mutationFn: ({ token, columns, notes }) =>
      apiFetch<Mapping>(`/sources/${sourceId}/mappings`, { method: "POST", body: JSON.stringify({ token, columns, notes }) }),
    // Optimistic: the source shows its next version as active straight away; restored if the API refuses.
    onMutate: async () => {
      await queryClient.cancelQueries({ queryKey: ["sources"], exact: true });
      const snapshot: MappingSnapshot = { sources: queryClient.getQueryData<Source[]>(["sources"]) };
      if (snapshot.sources) {
        queryClient.setQueryData<Source[]>(
          ["sources"],
          snapshot.sources.map((source) =>
            source.id === sourceId
              ? { ...source, active_mapping_version: source.mapping_versions + 1, mapping_versions: source.mapping_versions + 1 }
              : source,
          ),
        );
      }
      return snapshot;
    },
    onError: (_error, _variables, snapshot) => {
      if (snapshot?.sources) queryClient.setQueryData(["sources"], snapshot.sources);
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["sources"] }),
  });
}

type MappingSnapshot = { mappings?: Mapping[]; sources?: Source[] };

/** Optimistic: the chosen version shows as active at once; an API refusal restores the previous state. */
export function useRollback(sourceId: number) {
  const queryClient = useQueryClient();
  const mappingsKey = ["sources", sourceId, "mappings"];
  return useMutation<Mapping, ApiError, { mappingId: number; version: number }, MappingSnapshot>({
    mutationFn: ({ mappingId }) => apiFetch<Mapping>(`/sources/${sourceId}/mappings/${mappingId}/rollback`, { method: "POST" }),
    onMutate: async ({ mappingId, version }) => {
      await queryClient.cancelQueries({ queryKey: ["sources"] });
      const snapshot: MappingSnapshot = {
        mappings: queryClient.getQueryData<Mapping[]>(mappingsKey),
        sources: queryClient.getQueryData<Source[]>(["sources"]),
      };
      if (snapshot.mappings) {
        queryClient.setQueryData<Mapping[]>(
          mappingsKey,
          snapshot.mappings.map((mapping) => ({ ...mapping, is_active: mapping.id === mappingId })),
        );
      }
      if (snapshot.sources) {
        queryClient.setQueryData<Source[]>(
          ["sources"],
          snapshot.sources.map((source) => (source.id === sourceId ? { ...source, active_mapping_version: version } : source)),
        );
      }
      return snapshot;
    },
    onError: (_error, _variables, snapshot) => {
      if (snapshot?.mappings) queryClient.setQueryData(mappingsKey, snapshot.mappings);
      if (snapshot?.sources) queryClient.setQueryData(["sources"], snapshot.sources);
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["sources"] }),
  });
}
