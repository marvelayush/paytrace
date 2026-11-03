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
| A6 | TCS and TDS rates are configurable per channel on the rate card. Default: GST TCS 0.5% and income-tax TDS 0.1% of taxable value on marketplace and quick-commerce settlements; none on the own website. They are shown separately and never counted as leakage. **verify with the client's CA** | Expected-amount engine |
| A7 | Claims have manual statuses: open → filed → recovered / rejected. The user files claims outside the app (automatic filing is out of scope). | Claims |
| A8 | "Return not received" means the courier marked the order returned/RTO but no warehouse receipt scan arrived within 7 days (configurable). | Matching |
| A9 | Freight is charged by weight slab on the higher of dead weight and volumetric weight. The rate card defines slabs per courier and leg. | Expected-amount engine |
| A10 | All money is stored as integer paise in the database and the engines, and displayed as ₹ with 2 decimals in Indian digit grouping. | Everywhere |
| A11 | Orders that are not yet due and have no payment are `pending`. This status is not in the brief's list and does not count as money at risk. | Matching, dashboard |
| A12 | Orders overpaid by more than ₹10 keep the status `settled` and carry an `overpaid` flag shown in the UI. | Matching, orders screen |
| A13 | Sessions last 8 hours (JWT expiry, configurable). After that the user signs in again. No refresh tokens. | Auth |
| A14 | Login is rate-limited to 5 failed attempts per minute per IP and email, counted in memory (one backend instance). | Auth |
