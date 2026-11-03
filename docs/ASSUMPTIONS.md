# Assumptions

Everything the brief does not state explicitly. Each item has an ID so the code, tests and TDD can refer to it.
Items marked **verify** should be confirmed with the client before go-live.

| ID | Assumption | Where it matters |
|---|---|---|
| A1 | Partner names are generic: Website, Marketplace 1/2/3, QuickCom 1/2, Courier A, Courier B. No real brand names anywhere. | Seed data, UI |
| A2 | The co-founder role is read-only. Co-founders see the dashboard, orders and claims and can export. They cannot upload, edit mappings, edit rate cards or change a claim's status. Hidden in the UI and enforced by the API. | Auth, every write endpoint |
| A3 | Settlement cycle per partner, used for "past due": marketplaces T+7 days after delivery, quick-commerce T+7, COD remittance by courier T+10. Configurable per partner (`partners.settlement_days`). **verify** | Matching, ageing |
| A4 | Money-at-risk age buckets: 0–15, 16–30, 31–60 and 60+ days since the amount became due. | Dashboard |
| A5 | The ₹10 gap threshold from the brief applies per order to the net difference. A difference of exactly ₹10.00 is settled; ₹10.01 is flagged. | Matching |
| A6 | TCS and TDS rates are configurable per channel on the rate card. Default: GST TCS 0.5% and income-tax TDS 0.1% of order value (see A20) on marketplace and quick-commerce settlements; none on the own website. They are shown separately and never counted as leakage. **verify with the client's CA** | Expected-amount engine |
| A7 | Claims have manual statuses: open → filed → recovered / rejected. The user files claims outside the app (automatic filing is out of scope). | Claims |
| A8 | "Return not received" means the courier marked the order returned/RTO but no warehouse receipt scan arrived within 7 days (configurable). | Matching |
| A9 | Freight is charged by weight slab on the higher of dead weight and volumetric weight. The rate card defines slabs per courier and leg. | Expected-amount engine |
| A10 | All money is stored as integer paise in the database and the engines, and displayed as ₹ with 2 decimals in Indian digit grouping. | Everywhere |
| A11 | Orders that are not yet due and have no payment are `pending`. This status is not in the brief's list and does not count as money at risk. | Matching, dashboard |
| A12 | Orders overpaid by more than ₹10 keep the status `settled` and carry an `overpaid` flag shown in the UI. | Matching, orders screen |
| A13 | Sessions last 8 hours (JWT expiry, configurable). After that the user signs in again. No refresh tokens. | Auth |
| A14 | Login is rate-limited to 5 failed attempts per minute per IP and email, counted in memory (one backend instance). | Auth |
| A15 | On a return or RTO the sale and the channel's fees (commission, fixed fee, gateway fee, COD fee, TCS, TDS) are reversed. The expected amount is minus the freight on both legs. This reproduces the brief's ORD-W-204377 (−₹96). A returned marketplace order therefore expects ₹0. **verify per channel contract** | Expected-amount engine |
| A16 | A parcel heavier than a courier's top weight slab is priced at the top slab's price. | Expected-amount engine |
| A17 | Seed rate cards (`backend/app/services/reference_data.py`) are illustrative and chosen to reproduce the brief's three sample orders exactly. Website: gateway 2%. Marketplace 1: commission 20% + fixed fee ₹60.20. Marketplace 2: 18% + ₹50. Marketplace 3: 22% + ₹45. QuickCom 1: 25% + ₹25. QuickCom 2: 24% + ₹30. All marketplace/quick-commerce channels: TCS 0.5%, TDS 0.1%. Courier A: COD fee ₹30, slabs ₹60/85/125/210/360 up to 0.5/1/2/5/10 kg. Courier B: COD fee 2%, slabs ₹48/71/110/190/320. Return leg priced like forward. **replace with real contracts** | Seed data |
| A18 | "Received" for an order = settlement net + TCS/TDS withheld (added back, since they are tax credits) + COD remitted − courier charges invoiced (freight + COD fee). It is compared with the expected amount before tax, so tax never shows up as a difference. | Matching |
| A19 | Percentage amounts are rounded half up to the paisa, per line item. | Expected-amount engine |
| A20 | TCS and TDS are computed on the order value including GST, because the brief gives no GST split. Statutorily they are on the taxable value, so this is the main point to confirm with the CA (see A6). | Expected-amount engine |
| A21 | Marketplace and quick-commerce orders are shipped by the channel's own logistics, and that cost sits inside the channel's fixed fee. Only website orders ship through Courier A or B, so only they carry courier freight, COD fees and COD remittances. | Expected-amount engine, sample data |
| A22 | The website's payment gateway settles prepaid orders T+3 days after delivery. | Matching (due dates) |
| A23 | The A8 window runs 7 days from `returned_date` (the date the courier marked the return/RTO). It is configurable as `RETURN_RECEIPT_DAYS`. | Matching |
| A24 | Partners report the brand's own order ID. Couriers may report only the AWB (Courier B's COD remittance and freight invoice do), so matching falls back to AWB via the order's AWB. | Matching, sample data |
| A25 | Sample month: 30,000 orders placed 21 Sep – 20 Oct 2026. Mix: Website 40%, Marketplace 1/2/3 20/15/10%, QuickCom 1/2 9/6%. Average order ≈ ₹1,200. 55% of website orders are COD. Injected leakage ≈ 1.6% of order value across unremitted COD, unpaid marketplace settlements, excess fees, wrong weight slabs and lost returns. All customers are invented. | Sample data |
| A26 | A partner line whose canonical values are identical to one already stored for that partner is the same line uploaded again: it is skipped and counted as a duplicate, not double-counted. An exact repeat inside one file is rejected as a duplicate row. Orders are upserted by order ID, so a later report can update a delivery status. | Uploads |
| A27 | Dates are read day-first (DD/MM/YYYY, as used in India). The format is detected per column from the values. A weight column whose header mentions "kg" is in kilograms; otherwise in grams. | Parsing |
| A28 | Customer addresses are not stored at all; only the pincode is kept. Names and phones are stored masked. | Ingestion (DPDP) |
| A29 | A file whose header fingerprint matches the source's active mapping is processed without review. A file matching an older version is proposed from that version but still needs approval. Any other layout goes to the AI (or fuzzy fallback) and must be reviewed on 20 rows and approved. | Uploads |
| A30 | Uploaded files wait on the server's disk for at most 24 hours between inspection and processing, then are deleted. On Render this is the instance's ephemeral disk, which is fine for that short window. | Uploads, deployment |
| A31 | A return counts as received if the warehouse scanned it at any time, even after the 7-day window. Only returns with no scan once the window has passed are `return_not_received`. A return still inside its window with no scan is `pending`. | Matching |
| A32 | The partner who owes an order's money (used for claims and the dashboard): the courier for COD it collected, the courier for freight overcharges and for lost returns it carried, otherwise the sales channel. | Matching, claims |
| A33 | "Due date" for ageing: the paying partner's settlement cycle after delivery. For a lost return, the end of the receipt window. For a freight overcharge, the courier's cycle after the shipment's last event. | Money at risk |
| A34 | Money at risk per flagged order is the shortfall (expected − received, if positive). For a lost return it is the order value plus any shortfall. Settled and pending orders carry none. | Money at risk, claims |
| A35 | Auto-match rate = share of orders where money should have moved (delivered or returned, not pending) that were linked to at least one partner line by order ID or AWB without manual work. | Dashboard KPI |
| A36 | Only the latest reconciliation run's per-order results are kept. Every run's timing and summary stays in `recon_runs`. Claims keep their own evidence snapshot, so they do not depend on old results. | Matching |
| A37 | An order is claimed at most once. Once its claim is filed, recovered or rejected it is not added to a new claim automatically, even if it is still flagged. A rejected claim means the partner disputed it, and re-raising is a manual decision. | Claims |
| A38 | Each partner has at most one open claim, which reconciliation keeps up to date. Filing it freezes its contents and amounts, and any newly flagged orders start a new open claim. | Claims |
| A39 | The PDF evidence summary uses "Rs" instead of the ₹ sign, because the PDF's built-in fonts have no ₹ glyph. This avoids shipping a font file. The CSV and the app use ₹ or plain numbers. | Evidence export |
