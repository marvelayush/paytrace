import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatDate, formatINR, formatPercentBp, formatWeight } from "@/lib/format";
import { slabRows } from "@/lib/rate-cards";
import type { Partner, RateCard } from "@/lib/types";

function Term({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border bg-card px-4 py-3">
      <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
      <dd className="money mt-1 text-base font-semibold">{value}</dd>
      {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

export function RateCardDetail({ partner, card }: { partner: Partner; card: RateCard }) {
  const isCourier = partner.kind === "courier";
  const rows = slabRows(card.slabs);
  const hasTax = card.tcs_pct_bp > 0 || card.tds_pct_bp > 0;

  return (
    <div className="space-y-6">
      {isCourier ? (
        <section aria-labelledby="cod-heading" className="space-y-3">
          <h3 id="cod-heading" className="text-sm font-semibold">
            Charges per shipment
          </h3>
          <dl className="grid gap-3 sm:grid-cols-2">
            <Term
              label="COD fee"
              value={
                card.cod_fee_pct_bp > 0 && card.cod_fee_paise > 0
                  ? `${formatINR(card.cod_fee_paise)} + ${formatPercentBp(card.cod_fee_pct_bp)}`
                  : card.cod_fee_pct_bp > 0
                    ? `${formatPercentBp(card.cod_fee_pct_bp)} of order value`
                    : formatINR(card.cod_fee_paise)
              }
              hint="Charged on cash-on-delivery orders only"
            />
            <Term
              label="COD remittance due"
              value={`${partner.settlement_days} days`}
              hint="After delivery (A3)"
            />
          </dl>
        </section>
      ) : (
        <section aria-labelledby="fees-heading" className="space-y-3">
          <h3 id="fees-heading" className="text-sm font-semibold">
            Deductions per order
          </h3>
          <dl className="grid gap-3 sm:grid-cols-3">
            <Term label="Commission" value={formatPercentBp(card.commission_pct_bp)} hint="Of order value" />
            <Term label="Fixed fee" value={formatINR(card.fixed_fee_paise)} hint="Per order" />
            <Term label="Payment gateway" value={formatPercentBp(card.gateway_pct_bp)} hint="Prepaid orders" />
          </dl>
          <p className="text-xs text-muted-foreground">
            Money due {partner.settlement_days} days after delivery. Returns reverse these deductions.
          </p>
        </section>
      )}

      {!isCourier && (
        <section aria-labelledby="tax-heading" className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <h3 id="tax-heading" className="text-sm font-semibold">
              Tax withheld at source
            </h3>
            <Badge variant="secondary" className="font-normal">
              Tax, not leakage
            </Badge>
          </div>
          {hasTax ? (
            <dl className="grid gap-3 sm:grid-cols-3">
              <Term label="GST TCS" value={formatPercentBp(card.tcs_pct_bp)} hint="Claimable in GST returns" />
              <Term label="Income-tax TDS" value={formatPercentBp(card.tds_pct_bp)} hint="Claimable against tax" />
            </dl>
          ) : (
            <p className="text-sm text-muted-foreground">No TCS or TDS on this channel.</p>
          )}
        </section>
      )}

      {isCourier && (
        <section aria-labelledby="slabs-heading" className="space-y-3">
          <div>
            <h3 id="slabs-heading" className="text-sm font-semibold">
              Freight by weight slab
            </h3>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Priced on the higher of dead and volumetric weight. Heavier parcels pay the top slab.
            </p>
          </div>
          {rows.length === 0 ? (
            <p className="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
              No slabs yet. Freight for this courier is expected to be ₹0 until slabs are added.
            </p>
          ) : (
            <div className="overflow-hidden rounded-lg border bg-card">
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/50 hover:bg-muted/50">
                    <TableHead>Up to</TableHead>
                    <TableHead className="text-right">Forward</TableHead>
                    <TableHead className="text-right">Return</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((row) => (
                    <TableRow key={row.up_to_g}>
                      <TableCell className="money">{formatWeight(row.up_to_g)}</TableCell>
                      <TableCell className="money text-right">
                        {row.forward === null ? "—" : formatINR(row.forward)}
                      </TableCell>
                      <TableCell className="money text-right">
                        {row.return === null ? "—" : formatINR(row.return)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </section>
      )}

      <p className="text-xs text-muted-foreground">Effective for orders placed from {formatDate(card.effective_from)}.</p>
    </div>
  );
}
