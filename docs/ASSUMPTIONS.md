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
