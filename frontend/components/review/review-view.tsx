"use client";

import { Bot, Check, CircleAlert, Inbox, ListChecks, LoaderCircle, Scale, X } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { EmptyState, ErrorState, PageHeader } from "@/components/page-header";
import { StatusPill, type Tone } from "@/components/status-pill";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { canEdit, useCurrentUser } from "@/lib/auth";
import { formatCount, formatDate, formatDateTime, formatINR, formatSignedINR, plural } from "@/lib/format";
import { STATUS_META } from "@/lib/recon";
import {
  BULK_MIN,
  type Candidate,
  KIND_LABEL,
  type QueueLine,
  type QueueStatus,
  useAcceptLine,
  useBulkAccept,
  useRejectLine,
  useReviewQueue,
} from "@/lib/review";
import { cn } from "@/lib/utils";

const TABS: { value: QueueStatus; label: string }[] = [
  { value: "open", label: "To review" },
  { value: "accepted", label: "Accepted" },
  { value: "rejected", label: "Rejected" },
];

function confidenceTone(confidence: number | null): Tone {
  if (confidence == null) return "neutral";
  if (confidence >= BULK_MIN) return "settled";
  if (confidence >= 0.6) return "attention";
  return "neutral";
}

function ConfidenceBadge({ line }: { line: QueueLine }) {
  const percent = line.confidence == null ? "—" : `${Math.round(line.confidence * 100)}%`;
  return <StatusPill label={`${percent} confidence`} tone={confidenceTone(line.confidence)} />;
}

function EngineBadge({ line }: { line: QueueLine }) {
  if (line.ai_note === "pending") {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
        <LoaderCircle className="size-3 animate-spin" aria-hidden />
        AI ranking…
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-md bg-secondary px-1.5 py-0.5 text-xs text-secondary-foreground" title={line.ai_note ?? undefined}>
      {line.engine === "llm" ? <Bot className="size-3" aria-hidden /> : <Scale className="size-3" aria-hidden />}
      {line.engine === "llm" ? "AI + rules" : "Rules"}
    </span>
  );
}

/** Line vs candidate, field by field. Matching values are calm; differences are called out. */
function Comparison({ line, candidate }: { line: QueueLine; candidate: Candidate | undefined }) {
  const lineAmountLabel = line.kind === "settlement" && line.gross_paise !== 0 ? "Gross (sale value)" : line.kind === "settlement" ? "Net paid" : "Cash remitted";
  const lineAmount = line.kind === "settlement" && line.gross_paise !== 0 ? line.gross_paise : line.amount_paise;
  const orderAmount = candidate
    ? line.kind === "settlement" && line.gross_paise === 0
      ? candidate.expected_net_paise
      : candidate.value_paise
    : null;
  const rows: { field: string; line: React.ReactNode; order: React.ReactNode; differs?: boolean }[] = [
    {
      field: "Amount",
      line: (
        <>
          <span className="money">{formatINR(lineAmount)}</span>
          <span className="block text-xs text-muted-foreground">{lineAmountLabel}</span>
        </>
      ),
      order: candidate ? (
        <>
          <span className="money">{orderAmount == null ? "—" : formatINR(orderAmount)}</span>
          <span className="block text-xs text-muted-foreground">
            {candidate.amount_diff_paise === 0 ? "exact match" : `${formatSignedINR(candidate.amount_diff_paise)} off`}
          </span>
        </>
      ) : "—",
      differs: candidate ? candidate.amount_diff_paise !== 0 : false,
    },
    {
      field: "Date",
      line: (
        <>
          {formatDate(line.line_date)}
          <span className="block text-xs text-muted-foreground">{line.kind === "settlement" ? "settled" : "remitted"}</span>
        </>
      ),
      order: candidate ? (
        <>
          due {formatDate(candidate.due_date)}
          <span className="block text-xs text-muted-foreground">
            {candidate.days_from_due === 0 ? "paid on the due date" : `paid ${Math.abs(candidate.days_from_due)} d ${candidate.days_from_due > 0 ? "after" : "before"}`}
            {" · delivered "}
            {formatDate(candidate.delivered_date)}
          </span>
        </>
      ) : "—",
      differs: candidate ? Math.abs(candidate.days_from_due) > 3 : false,
    },
    {
      field: "AWB",
      line: <span className="money">{line.awb ?? "not given"}</span>,
      order: <span className="money">{candidate?.awb ?? "—"}</span>,
      differs: Boolean(line.awb && candidate?.awb && line.awb !== candidate.awb),
    },
    {
      field: "Partner",
      line: line.partner_name,
      order: candidate ? `${candidate.partner_name ?? "—"} · ${candidate.payment_mode === "cod" ? "COD" : "prepaid"}` : "—",
    },
  ];
  return (
    <table className="w-full text-sm">
      <caption className="sr-only">This line compared with {candidate?.order_id ?? "the selected order"}</caption>
      <thead className="text-xs text-muted-foreground">
        <tr className="border-b">
          <th scope="col" className="w-20 py-1.5 pr-2 text-left font-medium" />
          <th scope="col" className="py-1.5 pr-2 text-left font-medium">This line</th>
          <th scope="col" className="money py-1.5 text-left font-medium">{candidate?.order_id ?? "Order"}</th>
        </tr>
      </thead>
      <tbody className="divide-y">
        {rows.map((row) => (
          <tr key={row.field} className="align-top">
            <th scope="row" className="py-2 pr-2 text-left text-xs font-medium text-muted-foreground">{row.field}</th>
            <td className="py-2 pr-2">{row.line}</td>
            <td className={cn("py-2", row.differs && "text-attention")}>{row.order}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function CandidateList({ line, selected, onSelect, disabled }: { line: QueueLine; selected: string; onSelect: (orderId: string) => void; disabled: boolean }) {
  return (
    <fieldset disabled={disabled}>
      <legend className="mb-1.5 text-xs font-medium text-muted-foreground">
        {line.candidates.length} {plural(line.candidates.length, "candidate")} from the rules (same partner, amount, date window, unpaid)
      </legend>
      <div className="space-y-1">
        {line.candidates.map((candidate) => {
          const checked = candidate.order_id === selected;
          return (
            <label
              key={candidate.order_id}
              className={cn(
                "flex cursor-pointer items-center gap-2.5 rounded-lg border px-2.5 py-2 text-sm transition-colors has-[:focus-visible]:ring-3 has-[:focus-visible]:ring-ring/50",
                checked ? "border-primary/40 bg-sidebar-accent" : "hover:bg-accent/50",
                disabled && "cursor-default",
              )}
            >
              <input
                type="radio"
                name={`line-${line.id}`}
                value={candidate.order_id}
                checked={checked}
                onChange={() => onSelect(candidate.order_id)}
                className="size-4 accent-[var(--primary)]"
              />
              <span className="min-w-0 flex-1">
                <span className="money font-medium">{candidate.order_id}</span>
                {candidate.order_id === line.suggested_order_id && <span className="ml-2 text-xs font-medium text-primary">Suggested</span>}
                {candidate.ai_pick && candidate.order_id !== line.suggested_order_id && (
                  <span className="ml-2 text-xs text-muted-foreground">AI&apos;s pick</span>
                )}
                <span className="block text-xs text-muted-foreground">
                  {formatINR(candidate.value_paise ?? 0)} · due {formatDate(candidate.due_date)}
                  {candidate.recon_status && ` · ${STATUS_META[candidate.recon_status].label.toLowerCase()}`}
                </span>
              </span>
              <span className="money shrink-0 text-xs text-muted-foreground" title="Rule score: amount and date closeness">
                {candidate.rule_score.toFixed(2)}
              </span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

function RejectButton({ line }: { line: QueueLine }) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const reject = useRejectLine();
  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => {
          reject.reset();
          setNote("");
          setOpen(true);
        }}
      >
        <X aria-hidden />
        Reject
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Leave this line unmatched?</DialogTitle>
            <DialogDescription>
              The {formatINR(line.amount_paise)} line from {line.partner_name} stays out of the books. Use this when none of the orders is right.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor={`reject-${line.id}`}>Note (optional)</Label>
            <Textarea id={`reject-${line.id}`} rows={2} maxLength={500} value={note} onChange={(event) => setNote(event.target.value)} placeholder="e.g. Belongs to last month's batch; raised with the partner" />
          </div>
          {reject.error && (
            <Alert variant="destructive" className="border-loss/20 bg-loss-soft">
              <CircleAlert />
              <AlertDescription className="text-loss">{reject.error.message}</AlertDescription>
            </Alert>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)} disabled={reject.isPending}>
              Cancel
            </Button>
            <Button
              disabled={reject.isPending}
              onClick={() =>
                reject.mutate(
                  { lineId: line.id, note },
                  {
                    onSuccess: () => {
                      setOpen(false);
                      toast.success("Line left unmatched");
                    },
                  },
                )
              }
            >
              {reject.isPending && <LoaderCircle className="animate-spin" aria-hidden />}
              Reject
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function LineCard({ line, editable, checked, onCheck }: { line: QueueLine; editable: boolean; checked: boolean; onCheck: (value: boolean) => void }) {
  const [selected, setSelected] = useState(line.suggested_order_id ?? line.candidates[0]?.order_id ?? "");
  const accept = useAcceptLine();
  const candidate = line.candidates.find((item) => item.order_id === selected);
  const isOpen = line.status === "open";
  const bulkable = isOpen && (line.confidence ?? 0) >= BULK_MIN && Boolean(line.suggested_order_id);

  return (
    <li className="rounded-xl border bg-card">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b px-4 py-3">
        <div className="flex min-w-0 items-start gap-3">
          {editable && isOpen && (
            <Checkbox
              className="mt-1"
              checked={checked}
              disabled={!bulkable}
              onCheckedChange={(value) => onCheck(value === true)}
              aria-label={bulkable ? `Select line ${line.id} for bulk accept` : `Line ${line.id}: confidence below ${BULK_MIN * 100}%, review it on its own`}
            />
          )}
          <div className="min-w-0">
            <p className="font-medium">
              {line.partner_name} · {KIND_LABEL[line.kind]} · <span className="money">{formatINR(line.amount_paise)}</span>
            </p>
            <p className="text-xs text-muted-foreground">
              {formatDate(line.line_date)}
              {line.reference && <> · ref <span className="money">{line.reference}</span></>}
              {line.filename && <> · {line.filename}, row {line.row_number}</>}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <EngineBadge line={line} />
          {isOpen && <ConfidenceBadge line={line} />}
        </div>
      </div>

      {isOpen ? (
        <div className="grid gap-4 px-4 py-3 lg:grid-cols-2">
          <div className="space-y-3">
            {line.reason && (
              <p className="text-sm">
                <span className="font-medium">Why {line.suggested_order_id ?? "no order"}: </span>
                {line.reason}
              </p>
            )}
            {line.candidates.length > 0 ? (
              <CandidateList line={line} selected={selected} onSelect={setSelected} disabled={!editable || accept.isPending} />
            ) : (
              <p className="text-sm text-muted-foreground">No order fits the partner, amount and date window. Reject it, or check the partner&apos;s report.</p>
            )}
          </div>
          <div className="space-y-3">
            <div className="rounded-lg border px-3 py-1">
              <Comparison line={line} candidate={candidate} />
            </div>
            {accept.error && (
              <Alert variant="destructive" className="border-loss/20 bg-loss-soft">
                <CircleAlert />
                <AlertDescription className="text-loss">{accept.error.message}</AlertDescription>
              </Alert>
            )}
            {editable && (
              <div className="flex flex-wrap justify-end gap-2">
                <RejectButton line={line} />
                {candidate && (
                  <Button
                    size="sm"
                    disabled={accept.isPending}
                    onClick={() =>
                      accept.mutate(
                        { lineId: line.id, orderId: candidate.order_id },
                        { onSuccess: () => toast.success(`Line linked to ${candidate.order_id}; the order was re-matched`) },
                      )
                    }
                  >
                    {accept.isPending ? <LoaderCircle className="animate-spin" aria-hidden /> : <Check aria-hidden />}
                    {candidate.order_id === line.suggested_order_id ? `Accept ${candidate.order_id}` : `Accept ${candidate.order_id} instead`}
                  </Button>
                )}
              </div>
            )}
          </div>
        </div>
      ) : (
        <p className="px-4 py-3 text-sm">
          {line.status === "accepted" ? (
            <>
              Linked to{" "}
              <Link href={`/orders?q=${line.resolved_order_id}&open=${line.resolved_order_id}`} className="money font-medium underline-offset-4 hover:underline">
                {line.resolved_order_id}
              </Link>
              {line.resolved_order_id !== line.suggested_order_id && " (not the suggestion)"}
            </>
          ) : (
            "Left unmatched"
          )}
          <span className="text-muted-foreground">
            {" "}by {line.resolved_by ?? "finance"} · {formatDateTime(line.resolved_at)}
            {line.note && <> · “{line.note}”</>}
          </span>
        </p>
      )}
    </li>
  );
}

function BulkBar({ lines, selection, setSelection }: { lines: QueueLine[]; selection: Set<number>; setSelection: (ids: Set<number>) => void }) {
  const [open, setOpen] = useState(false);
  const bulk = useBulkAccept();
  const confident = lines.filter((line) => (line.confidence ?? 0) >= BULK_MIN && line.suggested_order_id);
  if (confident.length === 0) return null;
  const allSelected = confident.every((line) => selection.has(line.id));
  return (
    <div className="sticky bottom-[calc(4rem+env(safe-area-inset-bottom))] z-20 flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-card/95 px-4 py-3 shadow-sm backdrop-blur lg:bottom-4">
      <label className="flex items-center gap-2.5 text-sm">
        <Checkbox
          checked={allSelected}
          onCheckedChange={(value) => setSelection(value === true ? new Set(confident.map((line) => line.id)) : new Set())}
          aria-label="Select every line at 90% confidence or more"
        />
        <span>
          <span className="money font-medium">{formatCount(confident.length)}</span> {plural(confident.length, "line")} at {BULK_MIN * 100}% confidence or more
        </span>
      </label>
      <Button size="sm" disabled={selection.size === 0 || bulk.isPending} onClick={() => setOpen(true)}>
        <ListChecks aria-hidden />
        Accept selected ({formatCount(selection.size)})
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Accept {formatCount(selection.size)} suggestions?</DialogTitle>
            <DialogDescription>
              Each selected line is linked to its suggested order and that order is re-matched. Only lines at {BULK_MIN * 100}% confidence or more
              are accepted; anything else is skipped and stays in the queue. Every link is recorded in the audit log.
            </DialogDescription>
          </DialogHeader>
          {bulk.error && (
            <Alert variant="destructive" className="border-loss/20 bg-loss-soft">
              <CircleAlert />
              <AlertDescription className="text-loss">{bulk.error.message}</AlertDescription>
            </Alert>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)} disabled={bulk.isPending}>
              Cancel
            </Button>
            <Button
              disabled={bulk.isPending}
              onClick={() =>
                bulk.mutate([...selection], {
                  onSuccess: (result) => {
                    setOpen(false);
                    setSelection(new Set());
                    const skipped = result.skipped.length ? `, ${result.skipped.length} skipped` : "";
                    toast.success(`${result.accepted.length} ${plural(result.accepted.length, "line")} linked${skipped}`);
                  },
                })
              }
            >
              {bulk.isPending && <LoaderCircle className="animate-spin" aria-hidden />}
              Accept {formatCount(selection.size)}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function LoadingState() {
  return (
    <ul className="space-y-3" role="status" aria-busy aria-label="Loading the review queue">
      {Array.from({ length: 3 }, (_, index) => (
        <li key={index} className="rounded-xl border bg-card">
          <div className="flex justify-between border-b px-4 py-3">
            <div className="space-y-1.5">
              <Skeleton className="h-4 w-64 max-w-full" />
              <Skeleton className="h-3 w-48" />
            </div>
            <Skeleton className="h-5 w-28 rounded-full" />
          </div>
          <div className="grid gap-4 px-4 py-3 lg:grid-cols-2">
            <div className="space-y-2">
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
            </div>
            <Skeleton className="h-36 w-full" />
          </div>
        </li>
      ))}
    </ul>
  );
}

export function ReviewView() {
  const { data: user } = useCurrentUser();
  const editable = canEdit(user);
  const [tab, setTab] = useState<QueueStatus>("open");
  const [selection, setSelection] = useState<Set<number>>(new Set());
  const queue = useReviewQueue(tab);
  const lines = useMemo(() => queue.data?.lines ?? [], [queue.data]);
  const counts = queue.data?.counts;
  const aiNotes = [...new Set(lines.map((line) => line.ai_note).filter((note): note is string => Boolean(note) && note !== "pending"))];

  return (
    <>
      <PageHeader
        title="Review queue"
        description="Partner lines that arrived without an order ID. The rules shortlist the orders that fit and the AI helps rank them; nothing is linked until you accept."
      />
      <div role="tablist" aria-label="Queue" className="mb-5 inline-flex rounded-lg border bg-card p-0.5">
        {TABS.map((item) => (
          <button
            key={item.value}
            role="tab"
            type="button"
            aria-selected={tab === item.value}
            onClick={() => {
              setTab(item.value);
              setSelection(new Set());
            }}
            className={cn(
              "inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-sm transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
              tab === item.value ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {item.label}
            {counts && <span className="money text-xs">{formatCount(counts[item.value])}</span>}
          </button>
        ))}
      </div>

      {queue.isPending ? (
        <LoadingState />
      ) : queue.error ? (
        <ErrorState title="Couldn't load the review queue" message={queue.error.message} onRetry={() => queue.refetch()} />
      ) : lines.length === 0 ? (
        <EmptyState icon={Inbox} title={tab === "open" ? "Nothing to review" : `No ${tab} lines yet`}>
          {tab === "open"
            ? "Every settlement and COD line in the uploaded reports carries an order ID or an AWB PayTrace recognises. Lines without one appear here."
            : "Decisions made in the queue are listed here with who made them."}
        </EmptyState>
      ) : (
        <div className="space-y-4">
          {tab === "open" && (
            <p className="text-sm text-muted-foreground">
              <span className="money font-medium text-foreground">{formatINR(counts?.open_value_paise ?? 0)}</span> in{" "}
              {formatCount(lines.length)} {plural(lines.length, "line")} is not linked to any order yet, so those orders still show as unpaid.
            </p>
          )}
          {tab === "open" && (counts?.ai_pending ?? 0) > 0 && (
            <Alert role="status">
              <LoaderCircle className="animate-spin" />
              <AlertDescription>The AI is ranking {counts?.ai_pending} new lines. The rule suggestions below already work; this page updates by itself.</AlertDescription>
            </Alert>
          )}
          {tab === "open" && aiNotes.length > 0 && (
            <Alert className="border-attention/25 bg-attention-soft">
              <CircleAlert className="text-attention" />
              <AlertDescription className="text-foreground">
                {aiNotes.join(". ")}. The suggestions use the rule score only (amount and date closeness), and confidence is never raised by the AI.
              </AlertDescription>
            </Alert>
          )}
          <ul className="space-y-3">
            {lines.map((line) => (
              <LineCard
                key={line.id}
                line={line}
                editable={editable}
                checked={selection.has(line.id)}
                onCheck={(value) => {
                  const next = new Set(selection);
                  if (value) next.add(line.id);
                  else next.delete(line.id);
                  setSelection(next);
                }}
              />
            ))}
          </ul>
          {editable && tab === "open" && <BulkBar lines={lines} selection={selection} setSelection={setSelection} />}
        </div>
      )}
    </>
  );
}
