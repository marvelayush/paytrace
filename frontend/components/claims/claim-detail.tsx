"use client";

import { ArrowLeft, CircleAlert, Download, FileText, LoaderCircle, Lock } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { OrderDrawer } from "@/components/orders/order-drawer";
import { ErrorState } from "@/components/page-header";
import { StatusPill } from "@/components/status-pill";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { downloadFile } from "@/lib/api";
import { canEdit, useCurrentUser } from "@/lib/auth";
import { CLAIM_STATUS_META, type ClaimDetail, type ClaimStatus, NEXT_STATUSES, useChangeClaimStatus, useClaim } from "@/lib/claims";
import { formatCount, formatDate, formatINR } from "@/lib/format";
import { STATUS_META } from "@/lib/recon";
import { cn } from "@/lib/utils";

const ACTION_COPY: Record<ClaimStatus, { button: string; title: string; body: string }> = {
  filed: {
    button: "Mark as filed",
    title: "Mark this claim as filed",
    body: "Record that you sent this claim to the partner. Its orders and amounts are frozen from now on; new issues start a new claim.",
  },
  recovered: { button: "Mark recovered", title: "Mark this claim as recovered", body: "The partner paid this claim. It moves to Recovered." },
  rejected: { button: "Mark rejected", title: "Mark this claim as rejected", body: "The partner disputed this claim. Its orders are not raised again automatically." },
  open: { button: "", title: "", body: "" },
};

function StatusAction({ claim, next }: { claim: ClaimDetail; next: ClaimStatus }) {
  const [open, setOpen] = useState(false);
  const [reference, setReference] = useState(claim.reference ?? "");
  const change = useChangeClaimStatus(claim.id);
  const copy = ACTION_COPY[next];

  return (
    <>
      <Button
        size="sm"
        variant={next === "rejected" ? "outline" : "default"}
        onClick={() => {
          change.reset();
          setOpen(true);
        }}
      >
        {copy.button}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{copy.title}</DialogTitle>
            <DialogDescription>{copy.body}</DialogDescription>
          </DialogHeader>
          {next === "filed" && (
            <div className="space-y-1.5">
              <Label htmlFor="claim-reference">Partner&apos;s ticket or claim number (optional)</Label>
              <Input id="claim-reference" value={reference} maxLength={80} onChange={(event) => setReference(event.target.value)} />
            </div>
          )}
          {change.error && (
            <Alert variant="destructive" className="border-loss/20 bg-loss-soft">
              <CircleAlert />
              <AlertDescription className="text-loss">{change.error.message}</AlertDescription>
            </Alert>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)} disabled={change.isPending}>
              Cancel
            </Button>
            <Button
              disabled={change.isPending}
              onClick={() => {
                // Optimistic: the claim shows its new status straight away; an API refusal puts it back.
                const label = CLAIM_STATUS_META[next].label.toLowerCase();
                setOpen(false);
                toast.success(`Claim #${claim.id} marked ${label}`);
                change.mutate(
                  { status: next, reference: next === "filed" ? reference : undefined },
                  { onError: (error) => toast.error(`Claim #${claim.id} was not marked ${label}: ${error.message}`) },
                );
              }}
            >
              {change.isPending && <LoaderCircle className="animate-spin" aria-hidden />}
              {copy.button}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function ExportButton({ claimId, kind }: { claimId: number; kind: "csv" | "pdf" }) {
  const [busy, setBusy] = useState(false);
  return (
    <Button
      size="sm"
      variant="outline"
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        try {
          await downloadFile(`/claims/${claimId}/evidence.${kind}`, `claim-${claimId}-evidence.${kind}`);
        } catch (error) {
          toast.error(error instanceof Error ? error.message : "Download failed");
        } finally {
          setBusy(false);
        }
      }}
    >
      {busy ? <LoaderCircle className="animate-spin" aria-hidden /> : kind === "csv" ? <Download aria-hidden /> : <FileText aria-hidden />}
      {kind === "csv" ? "Evidence CSV" : "PDF summary"}
    </Button>
  );
}

export function ClaimDetailView({ claimId }: { claimId: number }) {
  const { data: user } = useCurrentUser();
  const claim = useClaim(claimId);
  const [openOrder, setOpenOrder] = useState<string | null>(null);

  const back = (
    <Link href="/claims" className="mb-4 inline-flex items-center gap-1.5 rounded text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50">
      <ArrowLeft className="size-4" aria-hidden /> All claims
    </Link>
  );

  if (claim.isPending) {
    return (
      <>
        {back}
        <Skeleton className="h-10 w-72" />
        <Skeleton className="mt-6 h-28 w-full rounded-xl" />
        <Skeleton className="mt-6 h-80 w-full rounded-xl" />
      </>
    );
  }
  if (claim.error) {
    return (
      <>
        {back}
        <ErrorState
          title={claim.error.status === 404 ? "This claim no longer exists" : "Couldn't load this claim"}
          message={claim.error.status === 404 ? "An open claim disappears when all its orders get paid." : claim.error.message}
          onRetry={claim.error.status === 404 ? undefined : () => claim.refetch()}
        />
      </>
    );
  }

  const data = claim.data;
  const nextStatuses = canEdit(user) ? NEXT_STATUSES[data.status] : [];
  const reasons = Object.entries(data.by_reason).sort((a, b) => (b[1]?.amount_paise ?? 0) - (a[1]?.amount_paise ?? 0));

  return (
    <>
      {back}
      <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">{data.partner_name}</h1>
            <StatusPill {...CLAIM_STATUS_META[data.status]} />
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            Claim #{data.id} · opened {formatDate(data.created_at)}
            {data.reference && ` · partner reference ${data.reference}`}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <ExportButton claimId={data.id} kind="csv" />
          <ExportButton claimId={data.id} kind="pdf" />
          {nextStatuses.map((next) => (
            <StatusAction key={next} claim={data} next={next} />
          ))}
        </div>
      </div>

      {data.status !== "open" && (
        <p className="mb-4 flex items-center gap-2 rounded-lg bg-secondary px-3 py-2 text-sm text-muted-foreground">
          <Lock className="size-4" aria-hidden /> This claim is {CLAIM_STATUS_META[data.status].label.toLowerCase()}: its orders and amounts no longer change.
        </p>
      )}

      <div className="mb-6 grid gap-3 sm:grid-cols-3">
        <div className="rounded-xl border bg-card px-4 py-3">
          <p className="text-xs text-muted-foreground">Amount claimed</p>
          <p className={cn("money text-2xl font-semibold", data.status === "open" && "text-loss")}>{formatINR(data.total_paise)}</p>
          <p className="text-xs text-muted-foreground">
            {formatCount(data.item_count)} orders{data.oldest_age_days ? ` · oldest ${data.oldest_age_days} days overdue` : ""}
          </p>
        </div>
        <div className="rounded-xl border bg-card px-4 py-3 sm:col-span-2">
          <p className="mb-2 text-xs text-muted-foreground">By reason</p>
          <ul className="space-y-1.5">
            {reasons.map(([reason, info]) => (
              <li key={reason} className="flex items-baseline justify-between gap-4 text-sm">
                <span>
                  {STATUS_META[reason as keyof typeof STATUS_META].label}
                  <span className="text-muted-foreground"> · {formatCount(info?.count ?? 0)} orders</span>
                </span>
                <span className="money font-medium">{formatINR(info?.amount_paise ?? 0)}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* Phones: one card per order */}
      <ul className="divide-y rounded-xl border bg-card md:hidden" aria-label="Orders in this claim">
        {data.items.map((item) => {
          const changed = item.current_status && item.current_status !== item.reason_status;
          return (
            <li key={item.order_id}>
              <button
                type="button"
                onClick={() => setOpenOrder(item.order_id)}
                className="flex w-full flex-col gap-1 px-4 py-3 text-left transition-colors duration-150 outline-none hover:bg-accent/40 focus-visible:bg-sidebar-accent"
              >
                <span className="flex items-baseline justify-between gap-3">
                  <span className="money font-medium text-primary">{item.order_id}</span>
                  <span className="money font-semibold text-loss">{formatINR(item.amount_paise)}</span>
                </span>
                <span className="text-sm">
                  {STATUS_META[item.reason_status].label}
                  {changed && item.current_status && (
                    <span className="text-settled"> · now {STATUS_META[item.current_status].label.toLowerCase()}</span>
                  )}
                </span>
                <span className="money text-xs text-muted-foreground">
                  {item.channel} · expected {formatINR(item.expected_paise)} · got {formatINR(item.received_paise)}
                  {item.age_days !== null && ` · ${item.age_days} d overdue`}
                </span>
              </button>
            </li>
          );
        })}
      </ul>

      <div className="relative hidden overflow-x-auto rounded-xl border bg-card md:block">
        <table className="w-full min-w-[52rem] text-sm">
          <thead className="sticky top-0 bg-muted/95">
            <tr className="text-left text-xs text-muted-foreground">
              <th scope="col" className="px-4 py-2.5 font-medium">Order</th>
              <th scope="col" className="px-4 py-2.5 font-medium">Reason</th>
              <th scope="col" className="px-4 py-2.5 text-right font-medium">Expected</th>
              <th scope="col" className="px-4 py-2.5 text-right font-medium">Received</th>
              <th scope="col" className="px-4 py-2.5 text-right font-medium">Claimed</th>
              <th scope="col" className="px-4 py-2.5 text-right font-medium">Due</th>
              <th scope="col" className="px-4 py-2.5 text-right font-medium">Overdue</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {data.items.map((item) => {
              const changed = item.current_status && item.current_status !== item.reason_status;
              return (
                <tr key={item.order_id} className="hover:bg-accent/40">
                  <td className="px-4 py-2.5">
                    <button
                      type="button"
                      onClick={() => setOpenOrder(item.order_id)}
                      className="money rounded font-medium text-primary underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
                    >
                      {item.order_id}
                    </button>
                    <span className="block text-xs text-muted-foreground">
                      {item.channel} · {formatDate(item.order_date)}
                    </span>
                  </td>
                  <td className="px-4 py-2.5">
                    {STATUS_META[item.reason_status].label}
                    {changed && item.current_status && (
                      <span className="block text-xs text-settled">Now {STATUS_META[item.current_status].label.toLowerCase()}</span>
                    )}
                  </td>
                  <td className="money px-4 py-2.5 text-right">{formatINR(item.expected_paise)}</td>
                  <td className="money px-4 py-2.5 text-right">{formatINR(item.received_paise)}</td>
                  <td className="money px-4 py-2.5 text-right font-semibold text-loss">{formatINR(item.amount_paise)}</td>
                  <td className="px-4 py-2.5 text-right text-muted-foreground">{formatDate(item.due_date)}</td>
                  <td className="money px-4 py-2.5 text-right">{item.age_days === null ? "—" : `${item.age_days} d`}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <OrderDrawer orderId={openOrder} onClose={() => setOpenOrder(null)} />
    </>
  );
}
