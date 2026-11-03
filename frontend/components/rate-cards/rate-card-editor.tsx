"use client";

import { CircleAlert, LoaderCircle, Plus, Trash2 } from "lucide-react";
import { type FormEvent, useState } from "react";
import { toast } from "sonner";

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
import { bpToInput, paiseToInput, parsePercentToBp, parseRupeesToPaise } from "@/lib/format";
import { slabRows, useSaveRateCard } from "@/lib/rate-cards";
import type { Partner, RateCard, RateCardTerms, WeightSlab } from "@/lib/types";

type Mode = "edit" | "new-version";

type SlabDraft = { key: number; upTo: string; forward: string; returnLeg: string };

type Draft = {
  effectiveFrom: string;
  commission: string;
  fixedFee: string;
  gateway: string;
  tcs: string;
  tds: string;
  codFee: string;
  codPct: string;
  slabs: SlabDraft[];
};

function draftFrom(card: RateCard, mode: Mode): Draft {
  let key = 0;
  return {
    effectiveFrom: mode === "edit" ? card.effective_from : new Date().toISOString().slice(0, 10),
    commission: bpToInput(card.commission_pct_bp),
    fixedFee: paiseToInput(card.fixed_fee_paise),
    gateway: bpToInput(card.gateway_pct_bp),
    tcs: bpToInput(card.tcs_pct_bp),
    tds: bpToInput(card.tds_pct_bp),
    codFee: paiseToInput(card.cod_fee_paise),
    codPct: bpToInput(card.cod_fee_pct_bp),
    slabs: slabRows(card.slabs).map((row) => ({
      key: key++,
      upTo: String(row.up_to_g),
      forward: row.forward === null ? "" : paiseToInput(row.forward),
      returnLeg: row.return === null ? "" : paiseToInput(row.return),
    })),
  };
}

type Errors = Partial<Record<keyof Draft | `slab-${number}`, string>>;

/** Turn the form into API terms, or return the problems to show next to each field. */
function toTerms(draft: Draft, card: RateCard, isCourier: boolean): { terms?: RateCardTerms; errors: Errors } {
  const errors: Errors = {};
  const percent = (field: keyof Draft, value: string) => {
    const bp = parsePercentToBp(value);
    if (bp === null) errors[field] = "Enter a percentage between 0 and 100.";
    return bp ?? 0;
  };
  const rupees = (field: keyof Draft, value: string) => {
    const paise = parseRupeesToPaise(value);
    if (paise === null) errors[field] = "Enter an amount in rupees, e.g. 60.20";
    return paise ?? 0;
  };

  if (!/^\d{4}-\d{2}-\d{2}$/.test(draft.effectiveFrom)) errors.effectiveFrom = "Pick a date.";

  const terms: RateCardTerms = {
    effective_from: draft.effectiveFrom,
    commission_pct_bp: isCourier ? card.commission_pct_bp : percent("commission", draft.commission),
    fixed_fee_paise: isCourier ? card.fixed_fee_paise : rupees("fixedFee", draft.fixedFee),
    gateway_pct_bp: isCourier ? card.gateway_pct_bp : percent("gateway", draft.gateway),
    tcs_pct_bp: isCourier ? card.tcs_pct_bp : percent("tcs", draft.tcs),
    tds_pct_bp: isCourier ? card.tds_pct_bp : percent("tds", draft.tds),
    cod_fee_paise: isCourier ? rupees("codFee", draft.codFee) : card.cod_fee_paise,
    cod_fee_pct_bp: isCourier ? percent("codPct", draft.codPct) : card.cod_fee_pct_bp,
    slabs: [],
  };

  if (isCourier) {
    const seen = new Set<number>();
    const slabs: WeightSlab[] = [];
    draft.slabs.forEach((row, index) => {
      const upTo = Number(row.upTo);
      const forward = parseRupeesToPaise(row.forward);
      const returnLeg = parseRupeesToPaise(row.returnLeg);
      if (!Number.isInteger(upTo) || upTo <= 0) {
        errors[`slab-${index}`] = "Weight must be a whole number of grams.";
      } else if (seen.has(upTo)) {
        errors[`slab-${index}`] = "Two slabs have the same weight.";
      } else if (forward === null || returnLeg === null) {
        errors[`slab-${index}`] = "Enter both prices in rupees.";
      } else {
        seen.add(upTo);
        slabs.push({ leg: "forward", up_to_g: upTo, price_paise: forward });
        slabs.push({ leg: "return", up_to_g: upTo, price_paise: returnLeg });
      }
    });
    terms.slabs = slabs;
  }

  return Object.keys(errors).length ? { errors } : { terms, errors };
}

function Field({
  id,
  label,
  suffix,
  prefix,
  value,
  error,
  onChange,
  type = "text",
}: {
  id: string;
  label: string;
  suffix?: string;
  prefix?: string;
  value: string;
  error?: string;
  onChange: (value: string) => void;
  type?: string;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <div className="relative">
        {prefix && (
          <span className="pointer-events-none absolute inset-y-0 left-2.5 flex items-center text-sm text-muted-foreground">
            {prefix}
          </span>
        )}
        <Input
          id={id}
          type={type}
          inputMode={type === "text" ? "decimal" : undefined}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${id}-error` : undefined}
          className={`money h-9 ${prefix ? "pl-6" : ""} ${suffix ? "pr-7" : ""}`}
        />
        {suffix && (
          <span className="pointer-events-none absolute inset-y-0 right-2.5 flex items-center text-sm text-muted-foreground">
            {suffix}
          </span>
        )}
      </div>
      {error && (
        <p id={`${id}-error`} className="text-xs text-loss">
          {error}
        </p>
      )}
    </div>
  );
}

export function RateCardEditor({
  partner,
  card,
  mode,
  open,
  onOpenChange,
  onSaved,
}: {
  partner: Partner;
  card: RateCard;
  mode: Mode;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: (card: RateCard) => void;
}) {
  const isCourier = partner.kind === "courier";
  const [draft, setDraft] = useState<Draft>(() => draftFrom(card, mode));
  const [errors, setErrors] = useState<Errors>({});
  const save = useSaveRateCard();

  const set = (field: keyof Draft) => (value: string) => setDraft((current) => ({ ...current, [field]: value }));

  function setSlab(index: number, patch: Partial<SlabDraft>) {
    setDraft((current) => ({
      ...current,
      slabs: current.slabs.map((row, rowIndex) => (rowIndex === index ? { ...row, ...patch } : row)),
    }));
  }

  function addSlab() {
    setDraft((current) => ({
      ...current,
      slabs: [...current.slabs, { key: Date.now(), upTo: "", forward: "", returnLeg: "" }],
    }));
  }

  function removeSlab(index: number) {
    setDraft((current) => ({ ...current, slabs: current.slabs.filter((_, rowIndex) => rowIndex !== index) }));
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const { terms, errors: found } = toTerms(draft, card, isCourier);
    setErrors(found);
    if (!terms) return;
    save.mutate(
      { cardId: mode === "edit" ? card.id : null, partnerId: partner.id, terms },
      {
        onSuccess: (saved) => {
          toast.success(mode === "edit" ? `${partner.name} rates updated` : `New ${partner.name} rates saved`);
          onSaved(saved);
          onOpenChange(false);
        },
      },
    );
  }

  const title = mode === "edit" ? `Edit ${partner.name} rates` : `New ${partner.name} rate version`;
  const description =
    mode === "edit"
      ? "Changes apply to every order this version covers. The change is recorded in the audit log."
      : "Orders placed on or after the effective date use the new rates; older orders keep the previous ones.";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-lg">
        <form onSubmit={handleSubmit} noValidate className="space-y-5">
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>{description}</DialogDescription>
          </DialogHeader>

          {save.error && (
            <Alert variant="destructive" className="border-loss/20 bg-loss-soft">
              <CircleAlert />
              <AlertDescription className="text-loss">{save.error.message}</AlertDescription>
            </Alert>
          )}

          <Field
            id="effective-from"
            label="Effective from"
            type="date"
            value={draft.effectiveFrom}
            error={errors.effectiveFrom}
            onChange={set("effectiveFrom")}
          />

          {isCourier ? (
            <>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field id="cod-fee" label="COD fee (fixed)" prefix="₹" value={draft.codFee} error={errors.codFee} onChange={set("codFee")} />
                <Field id="cod-pct" label="COD fee (% of value)" suffix="%" value={draft.codPct} error={errors.codPct} onChange={set("codPct")} />
              </div>

              <fieldset className="space-y-2">
                <legend className="text-sm font-medium">Weight slabs</legend>
                <div className="grid grid-cols-[1fr_1fr_1fr_2rem] gap-2 text-xs font-medium text-muted-foreground">
                  <span>Up to (g)</span>
                  <span>Forward ₹</span>
                  <span>Return ₹</span>
                  <span className="sr-only">Remove</span>
                </div>
                {draft.slabs.map((row, index) => (
                  <div key={row.key} className="space-y-1">
                    <div className="grid grid-cols-[1fr_1fr_1fr_2rem] items-center gap-2">
                      <Input
                        aria-label={`Slab ${index + 1} weight limit in grams`}
                        inputMode="numeric"
                        value={row.upTo}
                        onChange={(event) => setSlab(index, { upTo: event.target.value })}
                        aria-invalid={errors[`slab-${index}`] ? true : undefined}
                        className="money h-9"
                      />
                      <Input
                        aria-label={`Slab ${index + 1} forward price in rupees`}
                        inputMode="decimal"
                        value={row.forward}
                        onChange={(event) => setSlab(index, { forward: event.target.value })}
                        aria-invalid={errors[`slab-${index}`] ? true : undefined}
                        className="money h-9"
                      />
                      <Input
                        aria-label={`Slab ${index + 1} return price in rupees`}
                        inputMode="decimal"
                        value={row.returnLeg}
                        onChange={(event) => setSlab(index, { returnLeg: event.target.value })}
                        aria-invalid={errors[`slab-${index}`] ? true : undefined}
                        className="money h-9"
                      />
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        onClick={() => removeSlab(index)}
                        aria-label={`Remove slab ${index + 1}`}
                      >
                        <Trash2 />
                      </Button>
                    </div>
                    {errors[`slab-${index}`] && <p className="text-xs text-loss">{errors[`slab-${index}`]}</p>}
                  </div>
                ))}
                <Button type="button" variant="outline" size="sm" onClick={addSlab}>
                  <Plus /> Add slab
                </Button>
              </fieldset>
            </>
          ) : (
            <>
              <div className="grid gap-4 sm:grid-cols-3">
                <Field id="commission" label="Commission" suffix="%" value={draft.commission} error={errors.commission} onChange={set("commission")} />
                <Field id="fixed-fee" label="Fixed fee" prefix="₹" value={draft.fixedFee} error={errors.fixedFee} onChange={set("fixedFee")} />
                <Field id="gateway" label="Gateway fee" suffix="%" value={draft.gateway} error={errors.gateway} onChange={set("gateway")} />
              </div>
              <div className="grid gap-4 sm:grid-cols-3">
                <Field id="tcs" label="GST TCS" suffix="%" value={draft.tcs} error={errors.tcs} onChange={set("tcs")} />
                <Field id="tds" label="Income-tax TDS" suffix="%" value={draft.tds} error={errors.tds} onChange={set("tds")} />
              </div>
            </>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={save.isPending}>
              Cancel
            </Button>
            <Button type="submit" disabled={save.isPending}>
              {save.isPending && <LoaderCircle className="animate-spin" aria-hidden />}
              {mode === "edit" ? "Save changes" : "Save new version"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
